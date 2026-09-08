"""ANL-003 step 1: the committed dbt macro is generated, and drift is detected.

The macro file exists because dbt has to read SQL from disk. It is generated from
``policy.py`` so that the rules keep **one** definition. That arrangement is only worth
anything if a disagreement between the two is caught, so it is checked here.

**Nothing in this file writes the macro.** A check that regenerated on failure would
turn "these disagree" into "these agree now", which is the failure it is meant to
report. The deliberate-edit test therefore works on a **copy in a temp directory** and
never touches the repository's own file.
"""

from __future__ import annotations

import shutil

from energy_reconciliation import dbt_macros, policy


def test_the_committed_macro_matches_a_fresh_render():
    """The one that fails if someone edits policy.py without regenerating."""
    assert dbt_macros.drift() is None, (
        "dbt/macros/generated_policy.sql disagrees with policy.py. "
        f"Run `{dbt_macros.REGENERATE_COMMAND}`."
    )


def test_rendering_is_deterministic():
    """No timestamp, no path, no environment: two renders are the same bytes."""
    assert dbt_macros.render() == dbt_macros.render()


def test_the_render_carries_the_policy_sql_not_a_copy_of_it():
    text = dbt_macros.render()
    assert "{% macro distinct_readings(readings) %}" in text
    assert "{% macro conflicting_labels(readings) %}" in text
    # the signature expression is the policy's, character for character
    assert policy.SIGNATURE in text
    # and the relation is dbt's to fill in
    assert "FROM {{ readings }}" in text


def test_the_file_says_it_is_generated_and_how_to_regenerate_it():
    committed = dbt_macros.macro_file().read_text()
    assert "DO NOT EDIT" in committed
    assert dbt_macros.REGENERATE_COMMAND in committed


def test_a_hand_edit_is_detected(tmp_path):
    """A deliberate one-character edit to a COPY of the tree must be reported.

    The copy matters: this proves detection without the test depending on, or risking,
    the repository's own file.
    """
    root = tmp_path / "repo"
    target = root / dbt_macros.MACRO_PATH
    target.parent.mkdir(parents=True)
    shutil.copyfile(dbt_macros.macro_file(), target)
    assert dbt_macros.drift(root) is None, "the copy should start clean"

    original = target.read_text()
    target.write_text(original.replace("value_signature", "value_signatureX", 1))
    problem = dbt_macros.drift(root)
    assert problem is not None
    assert dbt_macros.REGENERATE_COMMAND in problem

    target.write_text(original)
    assert dbt_macros.drift(root) is None, "restoring the bytes clears the drift"


def test_a_missing_macro_file_is_drift_not_silence(tmp_path):
    problem = dbt_macros.drift(tmp_path / "empty")
    assert problem is not None
    assert "does not exist" in problem


def test_check_mode_reports_without_writing(tmp_path, capsys):
    """`--check` on a clean tree returns 0 and leaves the file's bytes alone."""
    before = dbt_macros.macro_file().read_bytes()
    assert dbt_macros.main(["--check"]) == 0
    assert dbt_macros.macro_file().read_bytes() == before
