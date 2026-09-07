"""REP-001 acceptance criterion 11.6: both lists exist and are non-overlapping.

Checked mechanically so the criterion cannot quietly regress as the documents grow.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
FACTS = DOCS / "rep-001-verified-facts.md"
OPEN = DOCS / "rep-001-assumptions-and-open-questions.md"

ID_PATTERN = re.compile(r"\b(VF|AQ|AS)-\d{2}\b")


def ids_in(path: Path) -> set[str]:
    return set(
        ID_PATTERN.findall(path.read_text(encoding="utf-8"))
        and ID_PATTERN.findall(path.read_text(encoding="utf-8"))
    )


def declared_ids(path: Path) -> list[str]:
    """IDs that begin a table row, i.e. entries this document actually declares."""
    return re.findall(
        r"^\|\s*((?:VF|AQ|AS)-\d{2})\s*\|",
        path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )


def test_both_lists_exist():
    assert FACTS.is_file(), "verified-facts list is required by REP-001 section 10"
    assert OPEN.is_file(), (
        "assumptions/open-questions list is required by REP-001 section 10"
    )


def test_lists_are_non_overlapping():
    """No statement may appear in both lists (acceptance criterion 11.6)."""
    facts, opens = set(declared_ids(FACTS)), set(declared_ids(OPEN))
    assert facts and opens
    assert facts.isdisjoint(opens), (
        f"IDs declared in both lists: {sorted(facts & opens)}"
    )


def test_id_prefixes_match_their_document():
    """Verified facts use VF-; open items use AQ-/AS-. A stray prefix means a mislabel."""
    assert all(i.startswith("VF-") for i in declared_ids(FACTS))
    assert all(i.startswith(("AQ-", "AS-")) for i in declared_ids(OPEN))


def test_ids_are_unique_within_each_document():
    for path in (FACTS, OPEN):
        declared = declared_ids(path)
        assert len(declared) == len(set(declared)), f"duplicate IDs in {path.name}"


def test_each_document_cross_references_the_other():
    assert OPEN.name in FACTS.read_text(encoding="utf-8")
    assert FACTS.name in OPEN.read_text(encoding="utf-8")
