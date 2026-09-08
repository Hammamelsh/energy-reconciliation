"""The price catalogue: PUBLISHER-DOCUMENTED figures, quoted, never inferred.

A Python model because `price_gbp_per_kwh` is the pence price divided by 100 **once,
exactly, in Decimal**, in `prices.Price.gbp_per_kwh`. Writing that division in SQL is
forbidden here: DuckDB evaluates DECIMAL / integer as DOUBLE, and 1.125 * 67.2000 / 100
returns 0.7559999999999999. The typed Arrow table carries the exact values across
without a float ever existing.
"""


def model(dbt, session):  # noqa: ARG001 - dbt passes the connection; this model does not query
    dbt.config(materialized="table")

    from energy_reconciliation.tariff.dimensions import price_table

    return price_table()
