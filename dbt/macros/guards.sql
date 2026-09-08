{#
  Hand-written, unlike generated_policy.sql. This guards the run; it defines no policy.
#}

{% macro assert_warehouse_is_loaded() %}
  {% if execute %}
    {% set expected = source('warehouse', 'readings') %}
    {% set found = adapter.get_relation(
         database=expected.database, schema=expected.schema, identifier=expected.identifier) %}
    {% if found is none %}
      {% do exceptions.raise_compiler_error(
           "No 'readings' table in " ~ expected ~ ". ENERGY_RECONCILIATION_DB points at "
           ~ target.path ~ ", which is not a loaded warehouse (an unloaded or wrongly "
           ~ "named path is created as an EMPTY DuckDB file, so every model would return "
           ~ "zero rows and report success). Point it at an ingested warehouse.") %}
    {% endif %}
  {% endif %}
{% endmacro %}
