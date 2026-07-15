# Coverage Matrix: Qlik Sense (Qlik Cloud API) → ThoughtSpot Model + Liveboard

What `ts-convert-from-qlik` maps from a Qlik Sense app pulled via the Qlik Cloud
REST + Engine (QIX) APIs, and what it does not. The data model and expressions are
read from the live engine (SOURCE), so the gaps below are ThoughtSpot-translation
limits, not extraction limits.

Notes column convention: blank = verified/direct; otherwise the caveat is stated.

## Mapped Constructs

### Structure and Schema

| # | Qlik Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 1 | Data-model table (`GetTablesAndKeys`) | Table TML | One per physical warehouse table |
| 2 | Field → physical column | `columns[]` entry with `db_column_name` | Type introspected from the warehouse |
| 3 | Key association between tables | Model `model_tables[].joins[]` | `with` / `'on'` / `type` / `cardinality`; `'on'` quoted |
| 4 | Association cardinality | `MANY_TO_ONE` / `ONE_TO_MANY` / `ONE_TO_ONE` | Confirmed with the user when ambiguous |
| 5 | Data connection (`/api/v1/data-connections`) | `connection.name` on every table | By name, never GUID (invariant I6) |
| 6 | Warehouse column type | `db_column_properties.data_type` | NUMBER scale 0→INT64, scale>0→DOUBLE, etc. |

### Formula Translation — Aggregations

| # | Qlik Function | ThoughtSpot formula | Notes |
|---|---|---|---|
| 7 | `Sum(x)` | `sum ( [T::x] )` | |
| 8 | `Avg(x)` | `average ( [T::x] )` | ThoughtSpot uses the full word |
| 9 | `Count(x)` | `count ( [T::x] )` | |
| 10 | `Count(DISTINCT x)` | `unique count ( [T::x] )` | Never `aggregation: COUNT_DISTINCT` (I5) |
| 11 | `Min(x)` / `Max(x)` | `min ( [T::x] )` / `max ( [T::x] )` | |
| 12 | `Stdev(x)` / `Median(x)` | `stddev ( [T::x] )` / `median ( [T::x] )` | |
| 13 | `Sum(TOTAL x)` | `group_aggregate ( sum ( [T::x] ) , {} , {} )` | Ignores row grouping |
| 14 | `Sum(TOTAL <dim> x)` | `group_aggregate ( sum ( [T::x] ) , {dim} , {} )` | |

### Formula Translation — Conditional and Cross-Level

| # | Qlik Function | ThoughtSpot formula | Notes |
|---|---|---|---|
| 15 | `Sum(If(cond, x))` | `sum_if ( cond , [T::x] )` | |
| 16 | `Count(If(cond, x))` | `count_if ( cond , [T::x] )` | |
| 17 | `Count(DISTINCT If(cond, x))` | `unique_count_if ( cond , [T::x] )` | |
| 18 | `Aggr(Sum(m), dim)` | `group_sum ( m , dim )` | Also `group_average` / `group_count` / `group_max` / `group_min` |

### Formula Translation — Date, Numeric, Passthrough

| # | Qlik Function | ThoughtSpot formula | Notes |
|---|---|---|---|
| 19 | `Year/Month/Day/Quarter(d)` | `year/month/day/quarter ( [T::d] )` | Qlik `Month` returns a name; ThoughtSpot returns 1–12 |
| 20 | `AddMonths(d, n)` / `AddYears(d, n)` | `add_months ( [T::d] , n )` / `add_years ( [T::d] , n )` | Native functions |
| 21 | date subtraction / `NetworkDays(a, b)` | `diff_days ( [T::a] , [T::b] )` | Calendar days only — no business-day logic |
| 22 | passthrough SQL (int/double/date/string/bool) | `sql_int_op('…')` / `sql_double_op` / `sql_date_op` / `sql_string_op` / `sql_bool_op` | For expressions with no native equivalent |

### Set Analysis

| # | Qlik Construct | ThoughtSpot formula | Notes |
|---|---|---|---|
| 23 | `Sum({1} x)` | `group_aggregate ( sum ( [T::x] ) , {} , {} )` | Ignore-all-selections |
| 24 | `Sum({$} x)` | `sum ( [T::x] )` | Current selection = ThoughtSpot default |
| 25 | `Sum({<F={'v'}>} x)` | `group_aggregate ( sum ( [T::x] ) , {dim} , {F = 'v'} )` | Fixed value filter |

### Sheets → Liveboards

| # | Qlik viz | ThoughtSpot chart | Notes |
|---|---|---|---|
| 26 | `barchart` / `bar` | `COLUMN` / `BAR` | Vertical vs horizontal |
| 27 | `linechart` | `LINE` | |
| 28 | `piechart` | `PIE` | Needs `x` (slice) + `y` (measure) axis_configs |
| 29 | `kpi` / `gauge` | `KPI` | `gauge` loses the gauge visual |
| 30 | `scatterplot` | `SCATTER` | |
| 31 | `table` / `pivot-table` | `TABLE` / `PIVOT_TABLE` | Table tiles omit the `chart:` block |
| 32 | `treemap` / `map` | `TREEMAP` / `GEO_AREA` | |
| 33 | `combochart` | `COLUMN` | Combo (line+bar) collapses to column — logged as a loss |

## Unmapped Constructs (Limitations)

### HIGH — Functionality loss, no clean workaround

| # | Qlik Construct | Limitation | Workaround |
|---|---|---|---|
| L1 | Set Analysis current-selection `{$<…>}` / `$`-expansion `$(=…)` | Selection state is not preserved in ThoughtSpot | Surface; translate an approximation with `group_aggregate` + `query_filters()` the user confirms |
| L2 | Alternate states / alternate dimensions | No ThoughtSpot equivalent | Rebuild as separate vizzes / filters; flagged |
| L3 | Section Access | No automated mapping | Recreate as ThoughtSpot row-level security manually |
| L4 | Variables (`$(vVar)` in expressions) | Not auto-substituted into formulas | Inline the resolved value or recreate as a model formula/parameter; flagged |

### MEDIUM — Approximation or manual step

| # | Qlik Construct | Limitation | Workaround |
|---|---|---|---|
| L5 | Load-script ETL / transforms | Not reproduced (ThoughtSpot reads physical tables) | Handle in the warehouse ETL; listed in the report |
| L6 | Mapping loads (`ApplyMap` / `MapSubString`) | No direct equivalent | `if/then/else`, `replace()`, or a pre-mapped warehouse column |
| L7 | Inter-record / script functions (`Peek`, `Previous`, `Lookup`, `Above`, `RowNo`) | No row-context equivalent | Resolve in ETL or via joins; flagged |
| L8 | Synthetic keys / circular references | Not auto-detected | Resolve into explicit star-schema joins in the Model TML |

### LOW — Cosmetic or edge-case

| # | Qlik Construct | Limitation | Workaround |
|---|---|---|---|
| L9 | Sheet/chart theming, colors, number formats | Not carried into TML | Re-apply in ThoughtSpot after import |
| L10 | Unsupported chart types (sankey, extensions) | No ThoughtSpot chart | Default to `TABLE`; logged as a loss |

### Notes on limitations

Nothing is silently dropped — every unmapped construct is written to the migration
report's "Needs confirmation / human intervention" checklist. Set Analysis, variables,
and script logic are the usual review items; the data model and simple aggregations
convert cleanly.
