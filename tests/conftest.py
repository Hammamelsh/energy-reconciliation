"""Synthetic archive fixtures with known answers.

Every fixture is built in a temp directory, so tests never touch data/raw.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

HEADER = b"LCLid,stdorToU,DateTime,KWH/hh (per half hour) \r\n"
MEMBER = "Small LCL Data/LCL-June2015v2_0.csv"


def build_archive(
    tmp_path: Path, members: dict[str, bytes], name: str = "test.zip"
) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for member_name, payload in members.items():
            z.writestr(member_name, payload)
    return path


def row(lclid: str, tariff: str, ts: str, val: str) -> bytes:
    """A record written exactly as the source writes it: padded value, CRLF ending."""
    return f"{lclid},{tariff},{ts},{val}\r\n".encode("ascii")


@pytest.fixture
def mixed_member() -> bytes:
    """12 records covering every consumption and timestamp category.

    Known answers are asserted in tests/test_profiler.py.
    """
    return HEADER + b"".join(
        [
            row(
                "MAC000001", "Std", "2012-10-12 00:30:00.0000000", " 0.143 "
            ),  # 1 finite
            row(
                "MAC000001", "Std", "2012-10-12 01:00:00.0000000", " 0 "
            ),  # 2 finite, zero
            row(
                "MAC000001", "Std", "2012-10-12 01:30:00.0000000", " -1.5 "
            ),  # 3 finite, negative
            row(
                "MAC000001", "Std", "2012-10-12 02:00:00.0000000", "Null"
            ),  # 4 null token
            row("MAC000001", "Std", "2012-10-12 02:30:00.0000000", ""),  # 5 empty
            row(
                "MAC000001", "Std", "2012-10-12 03:00:00.0000000", "NULL"
            ),  # 6 unexpected token
            row(
                "MAC000001", "Std", "2012-10-12 03:30:00.0000000", " nan "
            ),  # 7 non-finite
            row(
                "MAC000001", "Std", "2012-10-12 04:00:00.0000000", " Infinity "
            ),  # 8 non-finite
            row(
                "MAC000001", "Std", "2012-12-19 12:37:27.0000000", "Null"
            ),  # 9 off-grid
            row("MAC000001", "Std", "not-a-timestamp", " 0.5 "),  # 10 invalid ts
            row(
                "MAC000002", "ToU", "2012-10-12 00:30:00.0000000", " 0.2 "
            ),  # 11 second household
            row(
                "MAC000002", "ToU", "2012-10-12 00:30:00.0000000", " 0.2 "
            ),  # 12 exact duplicate
        ]
    )


@pytest.fixture
def duplicates_member() -> bytes:
    """Exact duplicate, same-meaning duplicate, and a conflicting key collision."""
    return HEADER + b"".join(
        [
            row("MAC000001", "Std", "2012-10-12 00:30:00.0000000", " 0.2 "),  # 1
            row(
                "MAC000001", "Std", "2012-10-12 00:30:00.0000000", " 0.2 "
            ),  # 2 exact dup of 1
            row("MAC000001", "Std", "2012-10-12 01:00:00.0000000", " 0.200 "),  # 3
            row(
                "MAC000001", "Std", "2012-10-12 01:00:00.0000000", " 0.2 "
            ),  # 4 same meaning as 3
            row("MAC000001", "Std", "2012-10-12 01:30:00.0000000", " 0.3 "),  # 5
            row(
                "MAC000001", "Std", "2012-10-12 01:30:00.0000000", " 0.9 "
            ),  # 6 CONFLICTS with 5
        ]
    )


@pytest.fixture
def multiline_member() -> bytes:
    """A quoted field containing a newline: 4 physical lines, 3 logical records."""
    return (
        HEADER
        + row("MAC000001", "Std", "2012-10-12 00:30:00.0000000", " 0.1 ")
        + b'MAC000001,"Std\r\nnote",2012-10-12 01:00:00.0000000, 0.2 \r\n'
        + row("MAC000001", "Std", "2012-10-12 01:30:00.0000000", " 0.3 ")
    )


@pytest.fixture
def wrong_field_count_member() -> bytes:
    """Two well-formed records and two with the wrong number of fields."""
    return HEADER + b"".join(
        [
            row("MAC000001", "Std", "2012-10-12 00:30:00.0000000", " 0.1 "),
            b"MAC000001,Std,2012-10-12 01:00:00.0000000\r\n",  # 3 fields
            b"MAC000001,Std,2012-10-12 01:30:00.0000000, 0.3 ,extra\r\n",  # 5 fields
            row("MAC000001", "Std", "2012-10-12 02:00:00.0000000", " 0.4 "),
        ]
    )


@pytest.fixture
def wrong_header_member() -> bytes:
    """Header without the trailing space on the fourth column."""
    return b"LCLid,stdorToU,DateTime,KWH/hh (per half hour)\r\n" + row(
        "MAC000001", "Std", "2012-10-12 00:30:00.0000000", " 0.1 "
    )


@pytest.fixture
def split_household_members() -> dict[str, bytes]:
    """One household straddling two members, as the real archive does."""
    a = HEADER + b"".join(
        [
            row("MAC000001", "Std", "2012-10-12 00:30:00.0000000", " 0.1 "),
            row("MAC000002", "Std", "2012-10-12 00:30:00.0000000", " 0.2 "),
            row("MAC000002", "Std", "2012-10-12 01:00:00.0000000", " 0.3 "),
        ]
    )
    b = HEADER + b"".join(
        [
            row("MAC000002", "Std", "2012-10-12 01:30:00.0000000", " 0.4 "),
            row("MAC000003", "Std", "2012-10-12 00:30:00.0000000", " 0.5 "),
        ]
    )
    return {
        "Small LCL Data/LCL-June2015v2_0.csv": a,
        "Small LCL Data/LCL-June2015v2_1.csv": b,
    }


@pytest.fixture
def distribution_member() -> bytes:
    """Ten finite values 0.1 .. 1.0 plus one `Null`, with hand-computable answers.

    finite count 10; min 0.1; max 1.0; sum 5.5; mean 0.55.
    Nearest-rank percentiles over 10 values: rank = ceil(p/100 * 10), so
    p25 -> rank 3 -> 0.3, p50 -> rank 5 -> 0.5, p75 -> rank 8 -> 0.8, IQR 0.5.
    Rows are written out of order to prove ordering is by value, not by position.
    """
    values = ["0.7", "0.1", "1.0", "0.4", "0.9", "0.2", "0.6", "0.3", "0.8", "0.5"]
    out = [HEADER]
    for i, val in enumerate(values):
        out.append(
            row("MAC000001", "Std", f"2012-10-12 {i:02d}:30:00.0000000", f" {val} ")
        )
    out.append(row("MAC000001", "Std", "2012-10-12 20:30:00.0000000", "Null"))
    return b"".join(out)


@pytest.fixture
def negative_distribution_member() -> bytes:
    """Includes a negative value so min/range are not assumed non-negative."""
    out = [HEADER]
    for i, val in enumerate(["-0.5", "0", "0.25", "2.75"]):
        out.append(
            row("MAC000001", "Std", f"2012-10-12 {i:02d}:30:00.0000000", f" {val} ")
        )
    return b"".join(out)
