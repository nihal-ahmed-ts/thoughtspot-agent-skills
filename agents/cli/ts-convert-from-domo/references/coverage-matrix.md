# Domo → ThoughtSpot coverage matrix

What the converter maps today, what it approximates, and what it flags `NEEDS REVIEW`. Statuses:
**Migrated** (faithful), **Approximated** (close, verify), **NEEDS REVIEW** (emitted verbatim /
skipped, human required).

## Objects

| Domo object | ThoughtSpot target | Status | Notes |
|---|---|---|---|
| Dataset (`schema.columns`) | Table TML | Migrated | type map: STRING/DATETIME/DOUBLE/LONG |
| Dataset-to-dataset join (no ETL) | Model join | Approximated | **inferred by shared column name** — no join metadata; confirm cardinality |
| Magic ETL join graph (`--etl`) | Model joins | Approximated | `MergeJoin` keys + type → model joins (preferred over inference); side/cardinality star-to-fact, flagged NEEDS REVIEW |
| Beast Mode (global) | Model formula | Migrated / see formula map | window/LOD → NEEDS REVIEW |
| Card-local `calculatedFields` | Model formula | Migrated | deduped against global by `(dataset, name)` |
| Card `kpi` | Answer (KPI/headline) | Migrated | from `summaryNumber` |
| Card `bar` | Answer (BAR) | Migrated | from `chartBody` |
| Card `table` | Answer (TABLE) | Migrated | from `chartBody` |
| Card (other chartType) | Answer | NEEDS REVIEW | until added to the chart-type map |
| Page | Liveboard | Migrated | one Liveboard per page |
| Page `collectionIds` / `children` | Liveboard tabs | Approximated | tab grouping approximated |
| Card layout (`preferredFullWidth/Height`) | Liveboard tile size | Approximated | grid approximation |

## Card query constructs

| Domo | ThoughtSpot | Status |
|---|---|---|
| `groupBy[]` | attribute columns (rows / x) | Migrated |
| `columns[].aggregation` | measure aggregation | Migrated (see AGG_MAP) |
| `orderBy[]` (`ASCENDING`/`DESCENDING`) | column sort | Migrated |
| `limit` | Answer row limit / top-N | Migrated |
| `columns[].format` (CURRENCY / NUMBER / percent / precision) | number format | Approximated |
| `conditionalFormats[]` | conditional formatting rule | Approximated |
| `quickFilters[]` | Liveboard filter chip | Approximated |

## Filter operands (`filters[].operand`)

| Domo operand | ThoughtSpot filter | Status |
|---|---|---|
| `IN` | IN | Migrated |
| `NOT_IN` | NOT_IN | Migrated |
| `GREATER_THAN` / `LESS_THAN` | GT / LT | Migrated |
| `BETWEEN` | BW_INC | Approximated |
| `LAST_90_DAYS` / `LAST_N_DAYS` | relative last-N-days preset | Approximated |
| `THIS_MONTH` / `THIS_QUARTER` / `YTD` | matching relative-date preset | Approximated |
| any other operand | — | NEEDS REVIEW |

## Beast Mode formulas

See [../../../shared/mappings/domo/beastmode-thoughtspot-formula-translation.md](../../../shared/mappings/domo/beastmode-thoughtspot-formula-translation.md) for the function/aggregation table. Deterministic subset → Migrated; multi-branch `CASE`, `DATEDIFF` → Approximated; window / running / LOD → NEEDS REVIEW.
