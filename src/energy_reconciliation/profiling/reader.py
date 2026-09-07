"""Read one CSV member from the archive, read-only, streaming.

The archive is never extracted and never modified. The member is decompressed on
the fly and discarded as it is consumed, so memory does not scale with file size.
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ARCHIVE = Path("data/raw/Partitioned LCL Data.zip")
DEFAULT_MEMBER = "Small LCL Data/LCL-June2015v2_0.csv"

# csv.field_size_limit guards against a runaway unterminated quote consuming the file.
MAX_FIELD_BYTES = 1 << 20


@dataclass(slots=True)
class ByteTally:
    """Byte-level facts gathered while the member streams past.

    These are measured from the raw decompressed bytes, independently of the CSV
    parser, so 'physical lines' and 'logical records' can be compared rather than
    assumed equal.
    """

    total_bytes: int = 0
    lf_count: int = 0  # every CRLF contains one LF, so this counts line ends
    crlf_count: int = 0
    lone_cr_count: int = 0
    non_ascii_bytes: int = 0
    ends_with_newline: bool = False
    sha256: str = ""

    @property
    def physical_lines(self) -> int:
        """Terminated lines, plus a final unterminated line if the file lacks one."""
        return self.lf_count + (0 if self.ends_with_newline else 1)


class CountingByteReader(io.RawIOBase):
    """Wraps a binary stream, tallying bytes as they are read.

    Counting happens here rather than in a second pass so the member is decompressed
    exactly once. Chunk boundaries are handled with a one-byte carry so a CRLF split
    across two reads is not miscounted.
    """

    def __init__(self, inner: io.BufferedIOBase) -> None:
        self._inner = inner
        self._hash = hashlib.sha256()
        self._pending_cr = False
        self._last_byte: int | None = None
        self.tally = ByteTally()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        chunk = self._inner.read(len(buffer))
        if not chunk:
            self._finish()
            return 0
        buffer[: len(chunk)] = chunk
        self._observe(chunk)
        return len(chunk)

    def _observe(self, chunk: bytes) -> None:
        t = self.tally
        t.total_bytes += len(chunk)
        self._hash.update(chunk)
        t.lf_count += chunk.count(b"\n")
        t.crlf_count += chunk.count(b"\r\n")
        if self._pending_cr:
            # A CR ended the previous chunk: it is a CRLF only if this chunk starts LF.
            if chunk[:1] == b"\n":
                t.crlf_count += 1
            else:
                t.lone_cr_count += 1
        cr_total = chunk.count(b"\r")
        crlf_inside = chunk.count(b"\r\n")
        self._pending_cr = chunk.endswith(b"\r")
        t.lone_cr_count += cr_total - crlf_inside - (1 if self._pending_cr else 0)
        t.non_ascii_bytes += sum(1 for b in chunk if b > 0x7F)
        self._last_byte = chunk[-1]

    def _finish(self) -> None:
        if self._pending_cr:
            self.tally.lone_cr_count += 1
            self._pending_cr = False
        self.tally.ends_with_newline = self._last_byte == 0x0A
        self.tally.sha256 = self._hash.hexdigest()


@dataclass(slots=True)
class MemberIdentity:
    """Everything needed to say exactly which bytes were profiled."""

    archive_path: str
    archive_sha256: str
    archive_bytes: int
    member_name: str
    member_uncompressed_bytes: int
    member_compressed_bytes: int
    member_crc32_hex: str
    member_zip_datetime: str
    compression: str


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def member_identity(archive: Path, member: str) -> MemberIdentity:
    """Content fingerprints taken from the archive's central directory plus the file."""
    with zipfile.ZipFile(archive) as z:
        info = z.getinfo(member)
        compression = zipfile.compressor_names.get(
            info.compress_type, str(info.compress_type)
        )
    return MemberIdentity(
        archive_path=str(archive),
        archive_sha256=file_sha256(archive),
        archive_bytes=archive.stat().st_size,
        member_name=member,
        member_uncompressed_bytes=info.file_size,
        member_compressed_bytes=info.compress_size,
        member_crc32_hex=f"{info.CRC:08x}",
        member_zip_datetime="{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}".format(
            *info.date_time
        ),
        compression=compression,
    )


class MalformedCsvError(RuntimeError):
    """Raised when the CSV parser cannot continue and cannot be resynchronised."""

    def __init__(self, message: str, records_read: int) -> None:
        super().__init__(message)
        self.records_read = records_read


@dataclass(slots=True)
class ReadOutcome:
    """Result of streaming a member: the header, the tally, and how it ended."""

    header: list[str] = field(default_factory=list)
    tally: ByteTally = field(default_factory=ByteTally)
    complete: bool = False
    failure: str | None = None
    records_read: int = 0


def stream_records(
    archive: Path, member: str, outcome: ReadOutcome
) -> Iterator[tuple[int, list[str]]]:
    """Yield ``(record_number, fields)`` for each logical CSV record after the header.

    Record numbers are 1-based and exclude the header. The caller receives the raw
    field strings with all original whitespace intact -- nothing is trimmed here.

    On an unrecoverable parser error the iterator stops and records the failure on
    ``outcome`` instead of raising, so the caller can still emit a partial report
    that is explicitly marked incomplete.
    """
    csv.field_size_limit(MAX_FIELD_BYTES)
    with zipfile.ZipFile(archive) as z, z.open(member) as raw:
        counter = CountingByteReader(raw)
        buffered = io.BufferedReader(counter)
        # newline="" hands line endings to the csv module, which is what lets a
        # quoted field legitimately contain a newline.
        text = io.TextIOWrapper(buffered, encoding="ascii", newline="", errors="strict")
        reader = csv.reader(text, delimiter=",", strict=True)

        try:
            outcome.header = next(reader)
        except StopIteration:
            outcome.tally = counter.tally
            outcome.failure = "member is empty: no header row"
            return
        except (csv.Error, UnicodeDecodeError) as exc:
            outcome.tally = counter.tally
            outcome.failure = f"could not read header: {type(exc).__name__}: {exc}"
            return

        n = 0
        while True:
            try:
                row = next(reader)
            except StopIteration:
                outcome.complete = True
                break
            except (csv.Error, UnicodeDecodeError) as exc:
                outcome.failure = (
                    f"{type(exc).__name__} after {n} records: {exc}. "
                    "Parsing stopped; the remainder of the member was NOT read."
                )
                break
            n += 1
            yield n, row

        outcome.records_read = n
        # Drain any trailing bytes so the tally covers the whole member when complete.
        if outcome.complete:
            while buffered.read(1 << 16):
                pass
        counter._finish()
        outcome.tally = counter.tally
