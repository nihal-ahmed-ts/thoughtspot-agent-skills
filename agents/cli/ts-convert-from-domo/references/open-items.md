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
