# Open Items — ts-convert-from-qlik-manual

Tracks unverified behaviour, deferred work, and known gaps.
Status: OPEN | VERIFIED | DEFERRED | WONT-FIX

---

## #1 — Live end-to-end smoke test — DEFERRED

A repeatable smoke test needs a `.qvf` fixture, a matching dashboard PDF, a live
ThoughtSpot instance, and a warehouse connection with the source tables. No shared
fixture bundle exists yet, so the skill is on the `check_smoke_tests.py` ALLOWLIST.

Status: DEFERRED — BL-116 (filed 2026-07-16); remove from the ALLOWLIST when a
`.qvf` + PDF + recorded warehouse-introspection fixture lands.

---

## #2 — `.qvf` offline parsing recovers almost nothing — VERIFIED

**Finding:** a `.qvf` is Qlik's proprietary chunked binary format. There is no
official offline parser; a byte-scan recovers only fragments (load-script text, some
field names) and effectively **0 charts**. This is why the dashboard is read from the
PDF instead.

Status: VERIFIED — expected behaviour; the PDF is the dashboard source of truth on
this path. Do not attempt to reconstruct charts from the `.qvf`.

---

## #3 — Dashboard fidelity depends on the PDF — OPEN

**Question:** how much of a chart's definition can be inferred from a static export?

**Current handling:** chart type, title, and the visible dimension(s)/measure(s) are
inferred and flagged INFERRED. Exact measure expressions, hidden filters, and
interactive selections are not recoverable and are surfaced for user confirmation
(placeholder `# TODO` where unknown).

**Action:** where fidelity matters, recommend the user obtain Qlik Cloud API access
and re-run with `ts-convert-from-qlik`, which reads the real definitions.

---

## #4 — Warehouse type introspection is manual — OPEN

**Finding:** the data model's column types must be read from the warehouse to set
`db_column_properties.data_type`; there is no bundled `ts` helper that emits a
`{table: {column: ts_type}}` map. Wrong types fail import with `DataType ... does not
match CDW DataType`.

**Action:** shared with `ts-convert-from-qlik` open-item #3 — evaluate folding a
type-introspection helper into the `ts` CLI.

---

## #5 — Inferred tile layout is approximate — OPEN

**Finding:** tile positions are inferred from the PDF's visual layout and mapped onto
the ThoughtSpot 12-column grid. The result is a reasonable approximation, not a
pixel-faithful reproduction.

**Action:** present the layout to the user for adjustment after import; consider a
layout-confirmation prompt before generating the liveboard TML.
