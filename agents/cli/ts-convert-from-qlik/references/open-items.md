# Open Items — ts-convert-from-qlik

Tracks unverified behaviour, deferred work, and known gaps.
Status: OPEN | VERIFIED | DEFERRED | WONT-FIX

---

## #1 — Live end-to-end smoke test — DEFERRED

A repeatable smoke test needs a Qlik Cloud tenant with an API key (Developer role) plus
a live ThoughtSpot instance and a warehouse connection. No shared fixture tenant exists
yet, so the skill is on the `check_smoke_tests.py` ALLOWLIST.

Status: DEFERRED — BL-116 (filed 2026-07-16); remove from the ALLOWLIST when a fixture
tenant + recorded QIX responses land.

---

## #2 — Set Analysis coverage is partial — OPEN

**Current handling:** the fixed-value and ignore-selection forms (`{1}`, `{<F={'v'}>}`,
`{$}`) translate to `group_aggregate(...)`. Current-selection context (`{$<…>}`) and
dollar-expansion (`$(=Max(Year))`) are surfaced and approximated, not translated
faithfully — selection state has no ThoughtSpot equivalent.

**Action:** collect real-world set-analysis expressions from a migrated app and expand
the rewrite table in `references/coverage-matrix.md`; confirm each approximation with a
live `search` comparison against the Qlik value before trusting it.

---

## #3 — Warehouse type introspection is not automated — OPEN

**Question:** the skill relies on reading warehouse column types to set
`db_column_properties.data_type`. There is no bundled `ts` sub-command that dumps a
`{table: {column: ts_type}}` map for Qlik-sourced tables.

**Current handling:** introspect types via the connection (or `ts connections`) and set
them manually, per the Snowflake mapping in Step 4. Wrong types fail import with
`DataType ... does not match CDW DataType`.

**Action:** evaluate folding a type-introspection helper into the `ts` CLI so the map is
generated, not hand-built.

---

## #4 — Variables are extracted but not substituted — OPEN

**Finding:** `GetLayout` on the `variablelist` returns variable definitions, but the
skill does not auto-substitute `$(vVar)` occurrences inside master/inline expressions.

**Action:** when an expression references a variable, surface it and either inline the
resolved value or recreate the variable as a ThoughtSpot parameter, with the user's
confirmation. Never guess the runtime value.

---

## #5 — `combochart` / unsupported charts collapse to a simpler type — VERIFIED

**Finding:** `combochart` (line + column) maps to `COLUMN` and genuinely unsupported
viz types (sankey, extensions) default to `TABLE`. Both are real losses, logged in the
migration report rather than silently dropped.

Status: VERIFIED — behaviour is intentional; the loss is surfaced in the report.
