"""Builds the committed synthetic demo archive.

The bytes are deterministic: fixed member timestamp, fixed create_system and
external attributes, fixed compression. Regenerating on any platform produces an
identical file, so `tests/test_demo.py` can assert the committed archive matches.

The data is INVENTED. Household ids use a DEMO prefix that does not occur in the
real dataset, and the values are chosen so every count can be worked out by hand.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

DEMO_ARCHIVE = Path("data/demo/demo-lcl-sample.zip")
DEMO_MEMBER = "Small LCL Data/DEMO-sample_0.csv"

HEADER = b"LCLid,stdorToU,DateTime,KWH/hh (per half hour) \r\n"

#: (household, tariff, timestamp, raw value) in file order. Record numbers below are
#: 1-based and exclude the header, matching the profiler's numbering.
RECORDS: tuple[tuple[str, str, str, str], ...] = (
    ("DEMO0001", "Std", "2013-01-01 00:30:00.0000000", " 0.125 "),  # 1  finite
    ("DEMO0001", "Std", "2013-01-01 01:00:00.0000000", " 0 "),  # 2  finite, zero
    ("DEMO0001", "Std", "2013-01-01 01:30:00.0000000", " 0.250 "),  # 3  finite
    ("DEMO0001", "Std", "2013-01-01 02:00:00.0000000", " 0.375 "),  # 4  finite
    ("DEMO0001", "Std", "2013-01-01 02:30:00.0000000", "Null"),  # 5  Null, unpadded
    ("DEMO0001", "Std", "2013-01-01 03:00:00.0000000", " 0.500 "),  # 6  finite
    (
        "DEMO0001",
        "Std",
        "2013-01-01 03:00:00.0000000",
        " 0.500 ",
    ),  # 7  exact duplicate of 6
    ("DEMO0001", "Std", "2013-01-01 03:30:00.0000000", " 0.625 "),  # 8  finite
    (
        "DEMO0001",
        "Std",
        "2013-01-01 03:30:00.0000000",
        " 0.750 ",
    ),  # 9  CONFLICTS with 8
    (
        "DEMO0001",
        "Std",
        "2013-01-01 04:17:23.0000000",
        " 0.875 ",
    ),  # 10 off-grid timestamp
    (
        "DEMO0002",
        "ToU",
        "2013-01-01 00:30:00.0000000",
        " 1.000 ",
    ),  # 11 second household
    ("DEMO0002", "ToU", "2013-01-01 01:00:00.0000000", " 1.125 "),  # 12 finite
)

FIXED_DATE_TIME = (2013, 1, 1, 0, 0, 0)


def csv_bytes() -> bytes:
    body = b"".join(
        f"{lclid},{tariff},{ts},{value}\r\n".encode("ascii")
        for lclid, tariff, ts, value in RECORDS
    )
    return HEADER + body


def archive_bytes() -> bytes:
    """Return the archive as bytes, byte-identical on every platform and run."""
    import io

    buffer = io.BytesIO()
    info = zipfile.ZipInfo(DEMO_MEMBER, date_time=FIXED_DATE_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3  # pin to Unix so Windows regeneration matches
    info.external_attr = 0o644 << 16
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(info, csv_bytes())
    return buffer.getvalue()


def write(path: Path = DEMO_ARCHIVE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(archive_bytes())
    return path


if __name__ == "__main__":
    written = write()
    print(f"wrote {written} ({written.stat().st_size} bytes)")
