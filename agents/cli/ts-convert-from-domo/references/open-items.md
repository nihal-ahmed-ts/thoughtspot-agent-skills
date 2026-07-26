# Domo skill — open items & known quirks

Tracks unverified assumptions and deferred work. Update as the CLI implementation (Phase 2)
verifies each against real Domo payloads.

## Verified against fixtures (`tests/fixtures/domo/`)
- Dataset schema shape (`schema.columns[{type,name}]`, types STRING/DATETIME/DOUBLE/LONG). ✓
- Beast Mode get-all shape (`results[{id,name,formula,dataSourceId,global,links[]}]`). ✓
- Card shapes: `kpi` uses `summaryNumber`; `bar`/`table` use `chartBody`; both carry
  `calculatedFields[]`, `quickFilters[]`; KPI carries `conditionalFormats[]`. ✓
- Page shape (`cardIds[]`, `collectionIds[]`, `children[]`). ✓
- ID cross-refs: page.cardIds ↔ card.urn; card.dataSetId / beastmode.dataSourceId ↔ dataset.id. ✓

## Unverified / needs real-instance confirmation
1. **Live API field parity** — the get-chart-card-definition and retrieve-a-page **live**
   payloads may carry more/renamed fields than the synthetic fixtures. Confirm against a real
   tenant before trusting `domo-cloud` field paths (the fixtures model the documented shape, not
   a live capture).
2. **Domo OAuth2 scope** — which scopes are needed to read card *definitions* (not just data).
   The public Datasets API is well documented; **card/page definitions may require additional
   scope or the internal content API**. `ts-profile-domo` must capture the right client scopes.
3. **Join inference** — Domo carries no relationship metadata; shared-column-name inference is a
   heuristic. Always emit inferred joins as NEEDS REVIEW; prefer `overrides.json`.
4. **`chartVersion`** — fixtures are `"2.0"`. Older card versions may nest the query differently;
   only 2.0 is handled initially.
5. **Relative-date operands** — the operand→preset table (coverage matrix) is best-effort; verify
   `LAST_N_DAYS` / fiscal (`chartBody.fiscal`) semantics against ThoughtSpot presets.
6. **Column format → number format** — Domo `format` (CURRENCY/NUMBER/percent/precision) → TS
   number format string mapping needs a fidelity pass.
7. **Tabs** — `collectionIds` is empty in the fixture; multi-tab (grouping) handling is untested
   until a page with populated `collectionIds` / `children` is available (see README "Extending").

## Deferred (future coverage)
- Cards with `dateRangeFilter` (relative date handling).
- Multi-page apps and Domo "collections" → multi-tab Liveboards.
- Card drill paths / links between cards.
