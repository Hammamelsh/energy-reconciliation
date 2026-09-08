"""Load one archive member into the warehouse.

Rerun policy (ING-001): content-addressed replace, scoped to one archive+member.
An unchanged member is skipped outright; a changed one replaces its own rows. A load
runs in a single transaction, so a failure leaves the previously published dataset and
its registry entry exactly as they were.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa

from ..profiling import validation as v
from ..profiling.reader import ReadOutcome, member_identity, stream_records
from ..profiling.report import code_identity, hash_python_sources
from .warehouse import DECIMAL_PRECISION, DECIMAL_SCALE, connect

BATCH = 20_000
TIMEZONE_STATUS = "unresolved"
INTERVAL_ANCHOR_STATUS = "unresolved"

REJECT_FIELD_COUNT = "wrong_field_count"
REJECT_TIMESTAMP = "invalid_timestamp"
REJECT_PRECISION = "excessive_precision"
REJECT_OVERFLOW = "value_overflow"

MAX_INTEGER_DIGITS = DECIMAL_PRECISION - DECIMAL_SCALE


@dataclass(frozen=True, slots=True)
class LoadResult:
    """What a load did. `skipped` means the identical content was already present."""

    load_id: str
    archive_name: str
    member_name: str
    skipped: bool
    replaced_previous: bool
    records_read: int
    records_published: int
    records_rejected: int
    reject_reasons: dict[str, int]
    complete: bool
    failure: str | None


def classify_for_storage(value: Decimal) -> str | None:
    """Return a rejection reason if the value cannot be stored exactly, else None.

    Storing a reading that does not fit would mean rounding it, which silently changes
    a measurement. Such values are rejected with their source text preserved instead.
    """
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -DECIMAL_SCALE:
        return REJECT_PRECISION
    if abs(value) >= Decimal(10) ** MAX_INTEGER_DIGITS:
        return REJECT_OVERFLOW
    return None


def pipeline_fingerprint() -> str:
    """Identify the transformation, so a code change forces a rebuild.

    Source content alone is not enough to decide a reload is unnecessary. If the
    parsing rules or the stored decimal shape change, previously loaded rows were
    produced by different logic and must be rebuilt even though the file is untouched.
    """
    profiling = Path(__file__).parent.parent / "profiling"
    ingest_digest, _ = hash_python_sources(Path(__file__).parent)
    profiling_digest, _ = hash_python_sources(profiling)
    shape = f"decimal({DECIMAL_PRECISION},{DECIMAL_SCALE})"
    combined = f"{ingest_digest}:{profiling_digest}:{shape}".encode()
    return hashlib.sha256(combined).hexdigest()


def member_content_digest(archive: Path, member: str) -> str:
    """SHA-256 of the member's decompressed bytes, without parsing anything.

    This runs before any write. It is what decides whether a load is needed at all,
    so an unchanged member costs only this pass -- no CSV parsing, no database work.
    """
    digest = hashlib.sha256()
    with zipfile.ZipFile(archive) as z, z.open(member) as raw:
        while chunk := raw.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _precision_detail() -> str:
    """Why a value was rejected rather than stored."""
    spec = f"DECIMAL({DECIMAL_PRECISION},{DECIMAL_SCALE})"
    return f"value not representable as {spec} without rounding"


def _insert_readings(con, rows: list[tuple]) -> None:
    """Insert a batch of readings.

    Rows are handed to DuckDB as an Arrow table rather than through executemany.
    Row-at-a-time binding of Decimal values is orders of magnitude slower, and a
    million-row member makes that difference the whole runtime.

    Separated into its own function so tests can make publication fail partway.
    """
    if not rows:
        return
    cols = list(zip(*rows, strict=True))
    batch = pa.table(
        {
            "load_id": pa.array(cols[0], pa.string()),
            "archive_name": pa.array(cols[1], pa.string()),
            "member_name": pa.array(cols[2], pa.string()),
            "source_record_no": pa.array(cols[3], pa.int64()),
            "household_id": pa.array(cols[4], pa.string()),
            "tariff_group": pa.array(cols[5], pa.string()),
            "source_timestamp_text": pa.array(cols[6], pa.string()),
            "observed_at_naive": pa.array(cols[7], pa.timestamp("us")),
            "timezone_status": pa.array(cols[8], pa.string()),
            "interval_anchor_status": pa.array(cols[9], pa.string()),
            "on_half_hour_grid": pa.array(cols[10], pa.bool_()),
            "consumption_kwh": pa.array(
                cols[11], pa.decimal128(DECIMAL_PRECISION, DECIMAL_SCALE)
            ),
            "consumption_raw_text": pa.array(cols[12], pa.string()),
            "value_category": pa.array(cols[13], pa.string()),
        }
    )
    con.register("_reading_batch", batch)
    try:
        con.execute("INSERT INTO readings SELECT * FROM _reading_batch")
    finally:
        con.unregister("_reading_batch")


def _insert_rejects(con, rows: list[tuple]) -> None:
    con.executemany("INSERT INTO rejected_records VALUES (?,?,?,?,?,?,?)", rows)


def previous_load(con, archive_name: str, member_name: str):
    """The last published load of this member: (load_id, content_sha, pipeline_fp)."""
    return con.execute(
        "SELECT load_id, member_content_sha256, pipeline_fingerprint FROM load_registry "
        "WHERE archive_name = ? AND member_name = ? AND status = 'published' "
        "ORDER BY loaded_at_utc DESC LIMIT 1",
        [archive_name, member_name],
    ).fetchone()


def load_member(
    archive: Path,
    member: str,
    database: Path,
) -> LoadResult:
    """Load one member. Idempotent for unchanged content; replaces changed content.

    Rows stream from the archive straight into batched inserts inside one
    transaction, so memory does not grow with the size of the member.
    """
    identity = member_identity(archive, member)
    archive_name = Path(archive).name
    content_sha = member_content_digest(archive, member)
    pipeline_fp = pipeline_fingerprint()
    # A load id identifies one load EVENT, so it carries the moment as well as the
    # content and pipeline digests. Superseded loads stay in the registry, and
    # reverting a code change reproduces an earlier content+pipeline pair; without
    # the timestamp that would collide with the row it is meant to supersede.
    loaded_at = datetime.now(UTC).replace(tzinfo=None)
    load_id = (
        f"{content_sha[:12]}+{pipeline_fp[:8]}@{loaded_at.strftime('%Y%m%dT%H%M%S%f')}"
    )

    con = connect(database)
    try:
        previous = previous_load(con, archive_name, member)
        unchanged = (
            previous is not None
            and previous[1] == content_sha
            and previous[2] == pipeline_fp
        )
        if unchanged:
            prior_read = con.execute(
                "SELECT records_read FROM load_registry WHERE load_id = ?",
                [previous[0]],
            ).fetchone()
            return LoadResult(
                previous[0],
                archive_name,
                member,
                True,
                False,
                int(prior_read[0]) if prior_read else 0,
                0,
                0,
                {},
                True,
                None,
            )

        outcome = ReadOutcome()
        reject_reasons: dict[str, int] = {}
        reading_batch: list[tuple] = []
        reject_batch: list[tuple] = []
        published = rejected = 0
        replaced = previous is not None

        con.begin()
        try:
            if replaced:
                # Rows are replaced, but the registry keeps the earlier load marked
                # superseded. The old readings are gone -- recovering them means
                # re-loading the earlier source file -- yet the record that a
                # different load once existed, and when, survives.
                for table in ("readings", "rejected_records"):
                    con.execute(
                        f"DELETE FROM {table} WHERE archive_name = ? AND member_name = ?",
                        [archive_name, member],
                    )
                con.execute(
                    "UPDATE load_registry SET status = 'superseded', "
                    "superseded_at_utc = ? "
                    "WHERE archive_name = ? AND member_name = ? AND status = 'published'",
                    [datetime.now(UTC).replace(tzinfo=None), archive_name, member],
                )

            def flush() -> None:
                nonlocal published, rejected
                if reading_batch:
                    _insert_readings(con, reading_batch)
                    published += len(reading_batch)
                    reading_batch.clear()
                if reject_batch:
                    _insert_rejects(con, reject_batch)
                    rejected += len(reject_batch)
                    reject_batch.clear()

            def reject(n: int, reason: str, detail: str, sample: str) -> None:
                reject_reasons[reason] = reject_reasons.get(reason, 0) + 1
                reject_batch.append(
                    (load_id, archive_name, member, n, reason, detail, sample)
                )

            for n, row in stream_records(archive, member, outcome):
                if len(row) != v.EXPECTED_FIELD_COUNT:
                    reject(
                        n,
                        REJECT_FIELD_COUNT,
                        f"expected {v.EXPECTED_FIELD_COUNT} fields, found {len(row)}",
                        "|".join(row[:8]),
                    )
                else:
                    household, tariff, ts_raw, val_raw = row
                    stamp = v.classify_timestamp(ts_raw)
                    if not stamp.valid:
                        reject(
                            n,
                            REJECT_TIMESTAMP,
                            f"does not match {v.TIMESTAMP_FORMAT}",
                            ts_raw,
                        )
                    else:
                        cons = v.classify_consumption(val_raw)
                        stored = None
                        storable = True
                        if cons.category == v.FINITE_NUMERIC and cons.value is not None:
                            reason = classify_for_storage(cons.value)
                            if reason is not None:
                                reject(n, reason, _precision_detail(), val_raw)
                                storable = False
                            else:
                                stored = cons.value
                        if storable:
                            reading_batch.append(
                                (
                                    load_id,
                                    archive_name,
                                    member,
                                    n,
                                    household,
                                    tariff,
                                    ts_raw,
                                    stamp.parsed,
                                    TIMEZONE_STATUS,
                                    INTERVAL_ANCHOR_STATUS,
                                    stamp.on_grid,
                                    stored,
                                    val_raw,
                                    cons.category,
                                )
                            )
                if len(reading_batch) >= BATCH or len(reject_batch) >= BATCH:
                    flush()
            flush()

            if not outcome.complete:
                # The member could not be read to the end. Nothing may be published
                # from a partial read, so roll the whole thing back.
                con.rollback()
                return LoadResult(
                    load_id,
                    archive_name,
                    member,
                    False,
                    False,
                    outcome.records_read,
                    0,
                    0,
                    reject_reasons,
                    False,
                    outcome.failure,
                )

            con.execute(
                "INSERT INTO load_registry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    load_id,
                    archive_name,
                    identity.archive_sha256,
                    member,
                    content_sha,
                    loaded_at,
                    outcome.records_read,
                    published,
                    rejected,
                    code_identity()["package_source_sha256"],
                    pipeline_fp,
                    "published",
                    None,
                ],
            )
            con.commit()
        except BaseException:
            con.rollback()
            raise

        return LoadResult(
            load_id,
            archive_name,
            member,
            False,
            replaced,
            outcome.records_read,
            published,
            rejected,
            reject_reasons,
            True,
            None,
        )
    finally:
        con.close()
