"""The band schedule, read and validated by the project's own Python.

A dbt Python model rather than SQL because the source is an Excel workbook and the rule
that a duplicated label must be refused is not expressible as a model: it has to run
before any row exists. `schedule.read_workbook` does both, and this model adds nothing to
it -- if this file contained validation of its own there would be two definitions of the
rule.

Selected with `--vars '{schedule: demo}'` for the invented schedule that lets the
committed demo archive build without the publisher's workbook. Every row records which
one it came from in `schedule_source`.
"""


def model(dbt, session):  # noqa: ARG001 - dbt passes the connection; this model does not query
    dbt.config(materialized="table")

    from energy_reconciliation.tariff.dimensions import resolve_schedule, schedule_table
    from energy_reconciliation.tariff.schedule import loaded_at

    variant = dbt.config.get("schedule") or "workbook"
    workbook = dbt.config.get("workbook") or None
    return schedule_table(resolve_schedule(variant, workbook), loaded_at())
