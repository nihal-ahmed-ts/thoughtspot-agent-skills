# Open items — ts-convert-from-domo

Assumptions, quirks and follow-ups. Status vocabulary: `TO VERIFY | VERIFIED | KNOWN |
DEFERRED | WONT-FIX`. Each must reach VERIFIED, or be explicitly KNOWN/DEFERRED with a
reason, before shipping.

## #1 — Offline chain: model + liveboard import cleanly — VERIFIED

The full offline chain (`parse` → `build-model` → `ts tml lint` → `ts tml import` →
`build-liveboard` → import) was run against a live cluster and the emitted Table, Model,
Answer and Liveboard TML import without errors. Two fixes came out of that run and are in
the converter:

- **Join side + cardinality.** The shared model emitter writes each join on *both* tables
  (bidirectional), which the model schema rejects. `_apply_join_fixes` keeps the join on
  the source (FK/MANY) side only and sets an explicit `cardinality`.
- **Display-name collisions.** A column name shared across joined tables (typically the
  join key) must stay physically present on both tables or the join stops resolving, but a
  Model cannot expose two columns with the same display name. Colliding columns are kept
  and their *display* name disambiguated; `db_column_name` stays the physical name.

## #2 — Fixture-derived shapes match the documented Domo payloads — VERIFIED

Verified against `tests/fixtures/domo/`:
- Dataset schema shape (`schema.columns[{type,name}]`, types STRING/DATETIME/DOUBLE/LONG).
- Beast Mode get-all shape (`results[{id,name,formula,dataSourceId,global,links[]}]`).
- Card shapes: `kpi` uses `summaryNumber`; `bar`/`table` use `chartBody`; both carry
  `calculatedFields[]` and `quickFilters[]`; KPI carries `conditionalFormats[]`.
- Page shape (`cardIds[]`, `collectionIds[]`, `children[]`).
- ID cross-refs: `page.cardIds` ↔ `card.urn`; `card.dataSetId` / `beastmode.dataSourceId`
  ↔ `dataset.id`.

These fixtures model the **documented** shape, not a live capture — see #3.

## #3 — A card's analyzer query is not reachable from any Domo API — KNOWN (structural)

Probed against a real instance with an `X-DOMO-Developer-Token`:

- **Reachable:** datasets (`/api/data/v3/datasources`), pages (`/api/content/v1/pages`,
  `/pages/{id}/cards`, `/api/content/v3/stacks/{id}/cards`), card **metadata incl.
  chartType** (`/api/content/v1/cards?urns=…&parts=metadata,…`), Beast Modes
  (`POST /api/query/v1/functions/search`). `ts_cli/domo/client.py` wraps these.
- **Not reachable:** the card's **analyzer query** — which measure/dimension/aggregation/
  filter it plots. Every candidate endpoint (`…/analyzer`, `…/definition`, `…/render`,
  `parts=problem,columns,dataset`, `v3/cards`) returned 404/405 or metadata only. The
  internal dataset *column list* endpoint was also not found (the schema endpoint returns
  `columnCount` but not columns; the public Developer API `GET /v1/datasets/{id}` does
  return `schema.columns`).

**Consequence, and why the skill is offline-only:** faithful card → Answer conversion needs
the analyzer query, and no token can reach it. The skill therefore converts from an offline
bundle and asks for the **dashboard PDF** to read chart/axes; without it, cards degrade to
title + chart-type placeholders and are flagged. This is a Domo platform limitation, not a
gap in the converter — hence KNOWN rather than DEFERRED.

## #4 — Live (`domo-cloud`) mode is not wired into `parse_app` — DEFERRED

`client.py` is a working foundation (see #3 for what it reaches) but `parse_app` only reads
a directory of JSON; the `--mode` flag records the mode and changes nothing. Because #3
caps live mode at *partial* fidelity anyway, wiring it is deferred rather than blocking.
`ts domo signin` exercises the client so the credential path stays honest and testable.

**Workaround:** capture the bundle (by hand, or with the client's endpoints) and run the
offline chain.

## #5 — Domo auth: developer token, not OAuth2 client credentials — VERIFIED

An earlier draft assumed OAuth2 client-credentials with a `data`/`dashboard` scope. The
endpoints the converter actually needs (#3) are Domo's internal ones, which authenticate
with an `X-DOMO-Developer-Token`, not a scoped OAuth2 bearer token. `ts-profile-domo` and
`ts profiles add --platform domo --auth-type developer-token` reflect that; the public
Datasets scope question is moot for this path.

## #6 — Join inference is a heuristic — KNOWN

Domo carries no relationship metadata. Without a Magic ETL export, joins are inferred by
shared column name. With `--etl`, they come from the dataflow's `MergeJoin` graph (keys +
type) — much better, but the join *side* is resolved by following each `MergeJoin.step1`
down to its primary `LoadFromVault` (star-to-fact), so a dim→dim join (e.g. Products →
Category Translation on `product_category_name`) attaches to the fact instead of Products.
Correct lineage needs the dataset schemas.

**Every** join from either path is therefore emitted `NEEDS REVIEW`, and the report warns on
a chasm trap when facts share a join key. Prefer `--etl`, and confirm cardinality by hand.

## #7 — Only `chartVersion` 2.0 is parsed — DEFERRED

Fixtures are `"2.0"`. Older card versions may nest the query differently; other versions are
flagged rather than guessed. Revisit when a pre-2.0 capture is available.

## #8 — Relative-date operands and fiscal semantics — DEFERRED

The operand → ThoughtSpot preset table in the coverage matrix (`LAST_N_DAYS`, `THIS_MONTH`,
`YTD`, …) is best-effort, and `chartBody.fiscal` semantics have not been reconciled against
ThoughtSpot's fiscal presets. Mapped rows are marked Approximated; anything unrecognised is
flagged. Cards carrying `dateRangeFilter` are deferred entirely.

## #9 — Column format → ThoughtSpot number format — DEFERRED

Domo `format` (CURRENCY / NUMBER / percent / precision) → TS number-format string needs a
fidelity pass. Mapped as Approximated today.

## #10 — Multi-tab pages are untried against a populated payload — DEFERRED

`collectionIds` is empty in the fixture, so `collectionIds` / `children` → Liveboard tab
grouping is exercised only on the single-tab path. Multi-page Domo apps, and card drill
paths / card-to-card links, are out of scope for this release (see the coverage matrix).

## #11 — Card sort / filters / formats are parsed but not emitted — KNOWN

`parsing.py` reads `orderBy`, `filters` (incl. relative-date operands), `quickFilters`,
`conditionalFormats` and per-column `format` into the IR, but `answers.py` emits none of
them. An Answer therefore lands **unsorted and unfiltered — showing all-time data** even
when the source card was scoped to, say, `LAST_90_DAYS`.

Found by auditing the emitted TML against the fixtures rather than trusting the coverage
matrix: the fixture card `Revenue by Region` carries a `DESCENDING` sort, a `LAST_90_DAYS`
filter and a `Product Category` quick filter, and the emitted Liveboard TML contained no
sort, filter or format node at all.

The dangerous part was not the gap but the **silence**: those cards were reported
`Migrated` with an empty note, and the report claimed 89% automation. `_dropped_constructs`
now detects each dropped construct per card, downgrades the card to `Approximated`, names
the constructs in the note, and surfaces them in the report's Manual review section — the
same fixture bundle now honestly reports 56% automation.

Emitting them for real is deferred: card filters need an operand→ThoughtSpot-preset
mapping that is still unverified (#8), and Liveboard filter chips need the `quickFilters`
→ filter-chip binding designed. Tracked here rather than silently carried.

## #12 — Six string functions had no ThoughtSpot equivalent — VERIFIED (fixed)

`UPPER`/`LOWER`/`TRIM`/`LTRIM`/`RTRIM`/`REPLACE` were mapped to same-named ThoughtSpot
functions. None of those exist (BL-170/BL-171, live-disproved on se-thoughtspot
2026-06-13 and 2026-07-29/30) — a bare call is rejected at import with `error_code
14516` — and because the translator considered them mapped, the affected formulas were
reported `Migrated`.

They now go through the shared `formula_common.wrap_passthrough_calls` into a
`sql_string_op` pass-through, the same mechanism `ts qlik` and `ts powerbi` use.
`SUBSTRING` was separately mapped to `substring`, which is also not a ThoughtSpot
function; it now maps to `substr`.

Two gates were blind to this and both are closed:
- `check_formula_catalog.py` only scans markdown **table rows**, and the Domo function
  map was written as prose bullets, so ~40 names were never checked. The map is now a
  set of tables in call form (`| \`ABS(x)\` | \`abs(x)\` | |`) — the shape the validator's
  regex actually matches. Injecting `upper` into any row now fails the validator.
- No fixture exercised a string function. `tests/fixtures/domo_edge/` now does, and
  `tests/test_domo_functions.py::TestMapIntegrity` cross-checks every emitted name
  against the catalog directly, so a future edit cannot reintroduce the class of bug.

Eight emitted names (`exp`, `hour`, `log`, `minute`, `quarter`, `sign`, `to_date`,
`week`) are not *in* the catalog — unverified rather than disproved. All eight are
emitted by the tableau/qlik/sisense maps too, so this converter is no more exposed than
the rest of the family; the validator warns rather than errors on them.

## #13 — Duplicate Beast Mode names produced a dangling formula reference — VERIFIED (fixed)

`build_model_tml` derives a formula's id from its name, so two datasets each carrying a
"Net Revenue" Beast Mode — ordinary in Domo — produced two formulas with the same id.
Downstream dedup then stripped **both**, leaving model columns pointing at a
`formula_id` that no longer existed (import fails), while the mapping still reported
both as `Migrated`. Colliding names are now disambiguated by dataset and the rename is
reported. The converter also now adopts `formula_common.resolve_name_collisions` for
column↔formula name clashes, which it previously did not handle at all.

## #14 — Join inference was unsound — VERIFIED (fixed)

Three separate problems, all now addressed:
- One join was emitted **per shared column per dataset pair**, so a pair sharing
  `id`, `Region` and `Date` produced three joins to the same table.
- Pairs whose only shared columns were incidental (`Region`, `Date`, `Status`, …) were
  joined anyway, which fans measures out across the star. Such a pair is now left
  unjoined and reported instead.
- The join **side** was decided by dataset iteration order — i.e. bundle filename sort
  — so the same two datasets could emit `MANY_TO_ONE` or `ONE_TO_MANY` depending on
  file names. Row counts now decide, and the join is placed on the many (fact) side.

## #15 — `--etl` joins were counted but silently dropped — VERIFIED (fixed)

Magic ETL carries dataflow **action** names, which need not match dataset names. Joins
whose tables did not resolve were counted in `counts.joins` and listed in
`mapping.json`, then filtered out of the TML — so the report claimed "Relationships: 7"
(and emitted a chasm-trap warning) over a model with no joins at all. Names are now
reconciled against the bundle's datasets; unmatched joins are dropped with a named
warning, surfaced in the report's Manual review section and counted separately as
`counts.joins_dropped`. `counts` now describes what was emitted, not what was seen.

