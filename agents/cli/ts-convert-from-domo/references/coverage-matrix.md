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
| Page `collectionIds` / `children` | Liveboard tabs | Approximated | single-tab path only; never exercised against a populated `collectionIds` payload |
| Card layout (`preferredFullWidth`/`preferredFullHeight`) | Liveboard tile size | Approximated | grid approximation |

### Card query constructs

| Construct | ThoughtSpot target | Status | Notes |
|---|---|---|---|
| `groupBy[]` | attribute columns (rows / x-axis) | Migrated | |
| `columns[].aggregation` | measure aggregation | Migrated | see `AGG_MAP` |
| `limit` | Answer row limit (`top N`) | Migrated | not applied to KPI cards |
| `chartType` `kpi` / `bar` / `table` | Answer `display_mode` + `chart.type` | Migrated | |

Everything else a card carries — sort, filters, quick filters, number formats,
conditional formatting — is **not** emitted. See Unmapped Constructs.

### Filter operands

None. Card `filters[].operand` values are parsed into the IR but no filter is emitted
onto the Answer or Liveboard — see Unmapped Constructs.

### Beast Mode formulas

See [../../../shared/mappings/domo/beastmode-thoughtspot-formula-translation.md](../../../shared/mappings/domo/beastmode-thoughtspot-formula-translation.md)
for the full function/aggregation table.

| Construct | ThoughtSpot target | Status | Notes |
|---|---|---|---|
| Arithmetic, comparison, logical operators | same operators | Migrated | |
| `SUM` / `AVG` / `MIN` / `MAX` / `COUNT` / `COUNT DISTINCT` | `sum` / `average` / `min` / `max` / `count` / `unique count` | Migrated | |
| `DATEDIFF` | `diff_days` | Approximated | Domo grain argument dropped — day grain assumed; verify arg order (Domo may return b−a) |
| `STDDEV` / `VARIANCE` | `stddev` / `variance` | Approximated | verify sample vs population |
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
| Window / running-total / LOD Beast Modes (`OVER`, `PARTITION BY`, `RANK`, `LAG`/`LEAD`) | No deterministic ThoughtSpot equivalent via string translation | Formula emitted verbatim and flagged |
| `CASE WHEN … END` — single- **and** multi-branch | The token translator cannot faithfully restructure control flow | Emitted verbatim and flagged. Recommended rewrite (`if (c) then x else y`) is in the Beast Mode mapping reference |
| `IFNULL` / `COALESCE` / `NULLIF` / `CAST` | Need a structural rewrite, not a token swap | Emitted verbatim and flagged; recommended rewrites in the mapping reference |
| `MEDIAN` / `PERCENTILE` | No clean ThoughtSpot TML keyword | Emitted verbatim and flagged |
| Card `orderBy[]` (sort) | Not emitted onto the Answer | Parsed into the IR, then dropped — reported per card as `Approximated` with the sort spelled out |
| Card `filters[]` — incl. `IN`, `NOT_IN`, `BETWEEN`, `LAST_N_DAYS`, `THIS_MONTH`, `YTD`, `dateRangeFilter` | No filter is emitted onto the Answer or Liveboard | Parsed into the IR, then dropped — reported per card. **The Answer will show unfiltered, all-time data** |
| Card `quickFilters[]` | Not emitted as a Liveboard filter chip | Parsed into the IR, then dropped — reported per card |
| Card `conditionalFormats[]` | Not emitted | Parsed into the IR, then dropped — reported per card |
| Domo column `format` (CURRENCY / NUMBER / percent / precision) | No number format is emitted | Parsed into the IR, then dropped — reported per card |
| Card drill paths and card-to-card links | No ThoughtSpot equivalent modelled yet | Deferred |
| Multi-page Domo apps | One page → one Liveboard today | Deferred |
