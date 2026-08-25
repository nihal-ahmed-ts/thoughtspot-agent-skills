<!-- coverage-matrix last-reviewed: 2026-08-26 -->
# Coverage matrix — Domo → ThoughtSpot

Every Domo construct and its conversion status. Cite in the migration report. Within
Mapped: **Migrated** (faithful/deterministic) · **Approximated** (mapped with a caveat,
verify). Anything a human must resolve is **NEEDS REVIEW** and is listed under Unmapped
Constructs. Source of truth for the formula rows is
`tools/ts-cli/ts_cli/domo/functions.py` (`AGG_MAP` / `FUNCTION_MAP` / `UNSUPPORTED`).

## Mapped Constructs

### Objects

| Construct | ThoughtSpot target | Status | Notes |
|---|---|---|---|
| Dataset (`schema.columns`) | Table TML | Migrated | type map: STRING/DATETIME/DOUBLE/LONG |
| Dataset-to-dataset join (no ETL) | Model join | Approximated | **inferred by shared column name** — Domo carries no relationship metadata; confirm cardinality |
| Magic ETL join graph (`--etl`) | Model joins | Approximated | `MergeJoin` keys + type → model joins (preferred over inference); side resolved star-to-fact, flagged NEEDS REVIEW |
| Beast Mode (global) | Model formula | Migrated | deterministic subset only; window/LOD → NEEDS REVIEW |
| Card-local `calculatedFields` | Model formula | Migrated | deduped against global Beast Modes by `(dataset, name)` |
| Card `kpi` | Answer (KPI/headline) | Migrated | from `summaryNumber` |
| Card `bar` | Answer (BAR) | Migrated | from `chartBody` |
| Card `table` | Answer (TABLE) | Migrated | from `chartBody` |
| Page | Liveboard | Migrated | one Liveboard per page |
| Page `collectionIds` / `children` | Liveboard tabs | Approximated | tab grouping approximated; not exercised against a populated `collectionIds` payload |
| Card layout (`preferredFullWidth`/`preferredFullHeight`) | Liveboard tile size | Approximated | grid approximation |

### Card query constructs

| Construct | ThoughtSpot target | Status | Notes |
|---|---|---|---|
| `groupBy[]` | attribute columns (rows / x-axis) | Migrated | |
| `columns[].aggregation` | measure aggregation | Migrated | see `AGG_MAP` |
| `orderBy[]` (`ASCENDING`/`DESCENDING`) | column sort | Migrated | |
| `limit` | Answer row limit / top-N | Migrated | |
| `columns[].format` (CURRENCY / NUMBER / percent / precision) | number format | Approximated | format-string fidelity pass outstanding |
| `conditionalFormats[]` | conditional formatting rule | Approximated | threshold rules only |
| `quickFilters[]` | Liveboard filter chip | Approximated | promoted to a cross-viz Liveboard filter |

### Filter operands (`filters[].operand`)

| Construct | ThoughtSpot target | Status | Notes |
|---|---|---|---|
| `IN` | IN | Migrated | |
| `NOT_IN` | NOT_IN | Migrated | |
| `GREATER_THAN` / `LESS_THAN` | GT / LT | Migrated | |
| `BETWEEN` | BW_INC | Approximated | inclusive bounds assumed |
| `LAST_90_DAYS` / `LAST_N_DAYS` | relative last-N-days preset | Approximated | operand→preset table is best-effort |
| `THIS_MONTH` / `THIS_QUARTER` / `YTD` | matching relative-date preset | Approximated | fiscal (`chartBody.fiscal`) semantics not verified |

### Beast Mode formulas

See [../../../shared/mappings/domo/beastmode-thoughtspot-formula-translation.md](../../../shared/mappings/domo/beastmode-thoughtspot-formula-translation.md)
for the full function/aggregation table.

| Construct | ThoughtSpot target | Status | Notes |
|---|---|---|---|
| Arithmetic, comparison, logical operators | same operators | Migrated | |
| `SUM` / `AVG` / `MIN` / `MAX` / `COUNT` / `COUNT DISTINCT` | `sum` / `average` / `min` / `max` / `count` / `unique count` | Migrated | |
| Single-branch `CASE WHEN … THEN … ELSE … END` | `if (…) then … else …` | Migrated | |
| Multi-branch `CASE` | nested `if/else` | Approximated | branch order preserved; verify fall-through |
| `DATEDIFF` | `diff_days` | Approximated | Domo grain argument dropped — day grain assumed |
| String functions (`CONCAT`, `UPPER`, `LOWER`, `SUBSTRING`, …) | same-named TS functions | Migrated | |

## Unmapped Constructs

Emitted as a flagged placeholder or skipped entirely — never silently downgraded to a
wrong-but-valid substitute. Each appears as `NEEDS REVIEW` in `mapping.json` and the
migration report.

| Construct | Why unmapped | Notes |
|---|---|---|
| Card **analyzer query** (which measure/dimension/aggregation a card plots) | No Domo API a token can reach exposes it, and it is absent from the offline card JSON for some card versions | The dominant fidelity limit. Supply the dashboard PDF to read chart/axes by hand; otherwise cards degrade to title + chart-type placeholders |
| Live (`domo-cloud`) fetch | Not wired into `parse_app` — `ts_cli/domo/client.py` is a probed foundation only (datasets, pages, card metadata, Beast Modes) | Offline bundle is the only supported input today. Tracked in `open-items.md` |
| Card `chartType` outside `kpi` / `bar` / `table` | Not in the chart-type map | Answer emitted with the closest type and flagged |
| `chartVersion` other than `"2.0"` | Older versions nest the query differently | Only 2.0 is parsed |
| Window / running-total / LOD Beast Modes | No deterministic ThoughtSpot equivalent via string translation | Formula emitted verbatim and flagged for a human |
| `dateRangeFilter` on a card | Relative-date range semantics unverified | Deferred |
| Card drill paths and card-to-card links | No ThoughtSpot equivalent modelled yet | Deferred |
| Multi-page Domo apps | One page → one Liveboard today | Deferred |
| Domo column `format` → exact TS number-format string | Needs a fidelity pass against real formats | Approximated where possible (see above), flagged otherwise |
