# Coverage Matrix: Qlik Sense (no-API / manual) → ThoughtSpot Model + Liveboard

What `ts-convert-from-qlik-manual` maps when there is no Qlik API access. The data
model is recovered from the warehouse (SOURCE); the dashboard is inferred from a
PDF/screenshots (INFERRED — every item flagged). Expression translation is identical
to the API path (`ts-convert-from-qlik`); this matrix highlights what the no-API path
loses relative to it.

Notes column convention: blank = verified/direct; otherwise the caveat is stated.

## Mapped Constructs

### Structure and Schema (SOURCE — from the warehouse)

| # | Qlik Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 1 | Data-model table (warehouse introspection) | Table TML | Reliable; confirmed against the provided data model |
| 2 | Field → physical column | `columns[]` with `db_column_name` | Type introspected, not guessed |
| 3 | Join key (from data-model viewer / load script) | Model `model_tables[].joins[]` | `'on'` quoted; `[TABLE::Col]` refs |
| 4 | Join cardinality | `MANY_TO_ONE` / `ONE_TO_MANY` / `ONE_TO_ONE` | Confirmed with the user |
| 5 | Connection | `connection.name` on every table | By name, never GUID (I6) |
| 6 | Warehouse column type | `db_column_properties.data_type` | NUMBER scale 0→INT64, scale>0→DOUBLE, etc. |

### Formula Translation (same engine as the API path)

| # | Qlik Function | ThoughtSpot formula | Notes |
|---|---|---|---|
| 7 | `Sum(x)` / `Avg(x)` / `Count(x)` | `sum` / `average` / `count ( [T::x] )` | Confirm each — measures are read from the PDF |
| 8 | `Count(DISTINCT x)` | `unique count ( [T::x] )` | Never `aggregation: COUNT_DISTINCT` (I5) |
| 9 | `Sum(If(cond, x))` | `sum_if ( cond , [T::x] )` | Also `count_if` / `unique_count_if` |
| 10 | `Aggr(Sum(m), dim)` | `group_sum ( m , dim )` | Also `group_average` / `group_count` |
| 11 | date subtraction / `AddMonths` / `AddYears` | `diff_days` / `add_months` / `add_years` | Calendar days only for diffs |
| 12 | passthrough SQL | `sql_int_op` / `sql_double_op` / `sql_date_op` / `sql_string_op` / `sql_bool_op` | For no-native-equivalent expressions |

### Dashboard → Liveboard (INFERRED — from the PDF)

| # | Qlik viz (read from PDF) | ThoughtSpot chart | Notes |
|---|---|---|---|
| 13 | bar / column | `BAR` / `COLUMN` | Chart type inferred from the export |
| 14 | line | `LINE` | |
| 15 | pie | `PIE` | Needs `x` + `y` axis_configs |
| 16 | KPI / gauge | `KPI` | |
| 17 | table / pivot | `TABLE` / `PIVOT_TABLE` | Table tiles omit the `chart:` block |
| 18 | treemap / map | `TREEMAP` / `GEO_AREA` | |

## Unmapped Constructs (Limitations)

### HIGH — Functionality loss, no clean workaround

| # | Qlik Construct | Limitation | Workaround |
|---|---|---|---|
| L1 | Chart definitions from the `.qvf` | Proprietary binary; offline parse recovers ~0 charts | Read the dashboard from the PDF (inferred) — the whole reason this path exists |
| L2 | Exact measure expressions behind a chart | Not legible in a static PDF | Infer from labels, confirm with the user, emit `# TODO` placeholders where unknown |
| L3 | Filters / selections not visible in the export | Static PDF hides interactive state | Surface; rebuild as liveboard filters with the user |
| L4 | Set Analysis current-selection / `$`-expansion | No ThoughtSpot equivalent (as in the API path) | Approximate with `group_aggregate` + `query_filters()`; flagged |
| L5 | Section Access | No automated mapping | Recreate as ThoughtSpot row-level security manually |

### MEDIUM — Approximation or manual step

| # | Qlik Construct | Limitation | Workaround |
|---|---|---|---|
| L6 | Variables (`$(vVar)`) | Not resolvable offline | Inline the value or recreate as a parameter; flagged |
| L7 | Load-script ETL / mapping loads | Not reproduced | Handle in warehouse ETL; listed in the report |
| L8 | Exact tile layout | Inferred from PDF pixel positions | Approximated on the 12-column grid; adjust after import |

### LOW — Cosmetic or edge-case

| # | Qlik Construct | Limitation | Workaround |
|---|---|---|---|
| L9 | Theming, colors, number formats | Not carried into TML | Re-apply in ThoughtSpot |
| L10 | Unsupported chart types | No ThoughtSpot chart | Default to `TABLE`; logged as a loss |

### Notes on limitations

The data model is trustworthy (recovered from the warehouse); the dashboard is a
best-effort reconstruction from a static export. Every inferred item is flagged
INFERRED in the migration report's "Needs confirmation / human intervention"
checklist. When the user has Qlik Cloud API access, prefer `ts-convert-from-qlik` —
it reads the real chart definitions and eliminates the inference in L1–L3.
