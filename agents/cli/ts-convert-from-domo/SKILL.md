---
name: ts-convert-from-domo
description: Convert or import a Domo dashboard into ThoughtSpot — parses Domo datasets, Beast Modes, cards and pages (live via the Domo API, or from a captured offline bundle directory), generates Table + Model TML and Answers/tabbed Liveboard, translates Beast Mode formulas, validates and imports. Direction is always Domo → ThoughtSpot. Not for ThoughtSpot → Domo or standalone TML exports.
---

# Domo → ThoughtSpot

Converts a Domo dashboard into ThoughtSpot objects through the `ts domo` CLI: parse the Domo
objects (datasets, Beast Modes, cards, page) → build Table + Model TML → build Answers and one
tabbed Liveboard → validate and import. Anything it cannot faithfully translate — window Beast
Modes, unknown chart types, unresolved fields — is flagged `NEEDS REVIEW` in the migration report
(`mapping.json`), never silently downgraded to a wrong-but-valid substitute.

A Domo "app" is assembled from **four API objects** (dataset schema, Beast Modes, card
definition, page). Two source modes:
- **`domo-cloud`** — pulls exact definitions live from a Domo instance (**SOURCE provenance — no
  guessing**). Needs `--instance <url>` and OAuth2 client credentials via the `ts-profile-domo`
  skill (never entered in this conversation).
- **`offline`** — a **directory** of captured Domo JSON (one file per dataset / the beast-mode
  list / each card / the page — the layout of `tests/fixtures/domo/`). Best-effort; flags gaps.

Ask one question at a time for **dependent** decisions (where the next depends on the answer);
**batch independent** questions into a single prompt to keep the migration fast.

## References

| File | Purpose |
|---|---|
| [../../shared/mappings/domo/beastmode-thoughtspot-formula-translation.md](../../shared/mappings/domo/beastmode-thoughtspot-formula-translation.md) | Beast Mode → ThoughtSpot formula/function + data-type mapping. Consult before declaring any formula untranslatable. |
| [../../shared/schemas/domo-app-ir.md](../../shared/schemas/domo-app-ir.md) | The IR contract between `ts domo parse` and the builders |
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML structure + critical invariants |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML structure |
| [../../shared/schemas/thoughtspot-answer-tml.md](../../shared/schemas/thoughtspot-answer-tml.md) | Answer/visualization TML structure |
| [../../shared/schemas/thoughtspot-liveboard-tml.md](../../shared/schemas/thoughtspot-liveboard-tml.md) | Liveboard TML structure |
| [../../shared/schemas/thoughtspot-chart-types.md](../../shared/schemas/thoughtspot-chart-types.md) | Verified `answer.chart.type` enum |
| [../ts-profile-domo/SKILL.md](../ts-profile-domo/SKILL.md) | Domo auth setup (OAuth2 client credentials) |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth setup |
| [references/coverage-matrix.md](references/coverage-matrix.md) | Mapped/unmapped Domo construct + Beast Mode matrix |
| [references/migration-report-format.md](references/migration-report-format.md) | Required `mapping.json` / report format |
| [references/open-items.md](references/open-items.md) | Known quirks / unverified items |

## Prerequisites

- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not.
- `ts` CLI installed: `pip install -e tools/ts-cli`. For `domo-cloud`, also configure a Domo
  profile — run `/ts-profile-domo`.
- A Domo source, one of two `--mode` values:
  - **`domo-cloud`** — live. `--instance <url> --page-id <id>` (client credentials from the Domo
    profile). Exact definitions.
  - **`offline`** — a directory of captured Domo JSON matching `tests/fixtures/domo/`
    (`domo_table_*.json`, `domo_model_beastmodes.json`, `domo_card_*.json`,
    `domo_liveboard_page_*.json`).
- The source tables already exist in a warehouse and a ThoughtSpot connection exposes them.
  This skill creates ThoughtSpot *logical* objects (Table, Model, Answers, Liveboard) over
  existing physical tables; it does not load data. For a demo, `ts load` can provision synthetic
  tables.

## Workflow

### Step 0 — Parse
```bash
ts domo parse --mode offline --input <bundle-dir> --output /tmp/domo_inv.json
# or, live:
ts domo parse --mode domo-cloud --instance <url> --page-id <id> --profile <domo-profile> \
  --output /tmp/domo_inv.json
```
Emits datasets, columns, Beast Modes, cards and page (see the IR schema), plus `notes`. Read it;
note any `needs_review` notes — the parser flags what it could not confidently read rather than
guessing.

### Step 1 — Build the model
```bash
ts domo build-model --input <bundle-dir> --connection "<TS connection>" \
  --database <DATABASE> --schema <SCHEMA> --model-name "<Model name>" --out out/ \
  [--overrides overrides.json]
```
Emits Table TML(s) + Model TML + `mapping.json`. Dataset columns map by the type table
(`STRING→VARCHAR` attr, `DOUBLE/LONG→MEASURE`, …). Beast Modes become `[formula_<name>]`
id-referenced formulas (single-pass import). **Joins are not in Domo metadata** — inferred by
shared column name (e.g. `Customer ID`) or taken from `--overrides`, and every inferred join is
flagged `NEEDS REVIEW`. Read `mapping.json`.

### Step 2 — Validate & import the model
```bash
ts tml lint --dir out/
ts tml import --dir out/ --order tableau --policy ALL_OR_NONE --profile <name>
```
`--order tableau` imports tables before the model. If the engine rejects a formula, drop it (and
any dependent column) and re-import — what lands is guaranteed to work, and the report records
what was pruned.

### Step 3 — Build the liveboard
```bash
ts domo build-liveboard --input <bundle-dir> --model-name "<Model name>" --out out/ \
  [--model-fqn <model-guid>] [--report-name "<Liveboard name>"]
```
Resolve `page.cardIds` → cards → Answers, assembled onto one Liveboard in page order.
`chartType` picks the viz (`kpi`→KPI, `bar`→BAR, `table`→TABLE); `groupBy`→attributes,
aggregated `columns`→measures, `orderBy`→sort, column `format`→number format,
`conditionalFormats`→conditional formatting, `quickFilters`→cross-viz Liveboard filter chips, and
a `filters` operand like `LAST_90_DAYS` → the matching relative-date filter. `collectionIds` /
page `children` become Liveboard tabs. Anything unmapped is flagged, never silently downgraded.
Then import:
```bash
ts tml import --dir out/ --order tableau --policy ALL_OR_NONE --profile <name>
```

### Step 4 — Migration report
`mapping.json` accounts for every dataset, Beast Mode, card and page with a status (Migrated /
Approximated / NEEDS REVIEW / Skipped), plus `notes`. Hand it to the user as the deliverable,
calling out every NEEDS REVIEW row (window Beast Modes, inferred joins, unknown cards) for manual
rebuild.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 0.1.0 | (scaffold) | Skill structure, IR contract, Beast Mode mapping, fixtures — CLI impl pending |
