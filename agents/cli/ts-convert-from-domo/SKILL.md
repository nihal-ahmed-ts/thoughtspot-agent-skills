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

## On invocation — gather the right inputs first

**Ask what the user has before running anything.** Missing inputs are the main cause of weak
results, so make the expectations explicit. Two independent choices, plus one clarification:

### 1. Source — how the Domo objects are read

| Choice | What the user provides | Gives you |
|---|---|---|
| **Offline (files)** — *default* | A **directory** of exported Domo JSON: dataset schemas, the beast-mode list, each card, the page (layout of `tests/fixtures/domo/`). | Datasets, Beast Modes, chart types, page layout. |
| **API (live)** | A Domo profile (`/ts-profile-domo`): instance URL + creds. Client-credentials → datasets + page structure; a **developer token** additionally reaches card metadata + Beast Modes (internal API). | Same as above, pulled live. |

⚠️ **Critical, learned the hard way:** *neither* the offline card JSON *nor* any Domo API reliably
exposes a card's **analyzer query** (which measure/dimension/aggregation it plots). For faithful
**cards → Answers you also need the dashboard as a PDF** (Domo → Export → PDF). Read the card's
chart/axes from the PDF — this is the "no-API / PDF + warehouse model" pattern (as in
`ts-convert-from-qlik`). Without it, cards degrade to title + chart-type placeholders (flagged).

### 2. For accurate model joins (recommended)

Ask for the **Magic ETL export JSON** of the dataflow that builds the dashboard's dataset. Pass it
via `build-model --etl` — joins come from the real `MergeJoin` graph instead of shared-column
inference.

### 3. Output — TML files, or created live in ThoughtSpot?

| Choice | Result | Requires |
|---|---|---|
| **TML files** — *default* | Table / Model / Answer / Liveboard TML + `mapping.json` land in `out/`; the user imports them. | nothing |
| **Direct create** | The skill also **imports** the TML so objects are created on the user's cluster. | a `ts-profile-thoughtspot` profile **and** the source tables already present in a connection on that cluster/org (the Model binds to them by name/GUID). |

Default to **TML files**. Only import if the user opts into direct-create, a ThoughtSpot profile
exists, **and** the underlying tables are already in the target connection — otherwise stop at the
TML and tell them how to import. Confirm the target profile/org before any import.

### Best-results checklist (state this to the user)
- ✅ Dataset schemas (offline files or live) — for tables
- ✅ Beast-mode list (offline/live) — for Model formulas
- ✅ **Dashboard PDF** — for card queries (else cards are placeholders)
- ✅ **Magic ETL export** — for accurate joins
- ✅ For live creation: a ThoughtSpot profile + the tables already loaded in the target connection

Confirm these before Step 0.

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
  --database <DATABASE> --schema <SCHEMA> --model-name "<Model name>" --output-dir out/ \
  [--etl <magic_etl_export.json>]
```
Emits Table TML(s) + Model TML + `mapping.json`. Dataset columns map by the type table
(`STRING→VARCHAR` attr, `DOUBLE/LONG→MEASURE`, …). Beast Modes become `[formula_<name>]`
id-referenced formulas (single-pass import). **Joins:** if a **Magic ETL export** is supplied
via `--etl`, joins come from the dataflow's `MergeJoin` graph (keys + type) — the accurate
source; otherwise they're inferred by shared column name. Either way each join is flagged
`NEEDS REVIEW` (side/cardinality is inferred without full column lineage). Read `mapping.json`.

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
```bash
ts domo report --output-dir out/          # -> out/migration_report.md
```
Renders `mapping.json` (+ `liveboard_mapping.json`) into a human-readable **`migration_report.md`**
(same spirit as the qlik/looker reports — see [references/migration-report.example.md](references/migration-report.example.md)):
a summary table (Migrated / Approximated / NEEDS REVIEW per object type), a **⚠️ Needs review**
section first (window Beast Modes, inferred/ETL joins, placeholder cards, TML-invariant findings),
then per-object detail (datasets, Beast Modes with Domo→TS formula, cards). Hand this to the user
as the deliverable and walk through every NEEDS REVIEW row.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 0.4.0 | (report + mapping + invocation) | Added `ts domo report` → `migration_report.md` (family-style, Needs-review-first) + worked example. Expanded the Beast Mode formula mapping (math/string/date/type + structural NEEDS-REVIEW) and the translator (`CASE`/window detection). Rewrote invocation guidance: required inputs per path incl. the **dashboard PDF** for card queries and the **Magic ETL** for joins, plus the TML-vs-live-import output gate. |
| 0.3.0 | (magic-etl + live probe) | `build-model --etl` derives model joins from a Domo Magic ETL export (`magic_etl.parse_etl`). Added `client.py` (internal-API client) as a live-path foundation; probe confirmed datasets/pages/chartType/Beast-Modes are reachable but the card **analyzer query is not** — full card fidelity stays offline (see open-items). |
| 0.2.0 | (offline build) | `ts domo` CLI implemented for **offline** mode — parse / build-model / build-liveboard, Beast Mode translation, join inference, tests green. Live `domo-cloud` client still pending. |
| 0.1.0 | (scaffold) | Skill structure, IR contract, Beast Mode mapping, fixtures — CLI impl pending |
