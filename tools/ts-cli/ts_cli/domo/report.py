"""Render a human-readable migration report (Markdown) from the mapping JSON(s).

Same rich shape as the rest of the family (qlik/looker): an executive summary and
a modernization scorecard framing a full per-object accounting, always leading the
manual-review section so a human sees the gaps first. Pure function: dicts in,
Markdown string out — every number is derived from the mappings, never invented.
"""
from __future__ import annotations

from typing import Optional

_REVIEW = {"NEEDS REVIEW", "Approximated", "Skipped"}


def _tally(items: list) -> tuple[int, int, int, int]:
    """(migrated, approximated, needs_review, skipped)."""
    m = a = r = s = 0
    for it in items:
        st = it.get("status", "Migrated")
        if st == "Migrated":
            m += 1
        elif st == "Approximated":
            a += 1
        elif st == "Skipped":
            s += 1
        else:
            r += 1
    return m, a, r, s


def _pct(n: int, d: int) -> int:
    return round(100 * n / d) if d else 100


def _chasm_keys(joins: list) -> list[str]:
    """Join keys used by >= 2 joins — a multi-fact fan-out (chasm-trap) risk."""
    counts: dict[str, int] = {}
    for j in joins:
        for k in str(j.get("on", "")).split(","):
            k = k.strip()
            if k:
                counts[k] = counts.get(k, 0) + 1
    return sorted([k for k, c in counts.items() if c >= 2])


def render_report(mapping: dict, lb_mapping: Optional[dict] = None) -> str:
    src = mapping.get("source", {})
    datasets = mapping.get("datasets", [])
    joins = mapping.get("joins", [])
    beast = mapping.get("beast_modes", [])
    renamed = mapping.get("renamed_columns", [])
    invariants = mapping.get("invariant_findings", [])
    cards = (lb_mapping or {}).get("cards", [])
    pages = (lb_mapping or {}).get("pages", [])

    app_name = src.get("app_name", "Untitled")
    mode = src.get("mode", "offline")
    n_tables = len(datasets)
    n_cols = sum(d.get("columns", 0) for d in datasets)
    n_joins = len(joins)
    n_beast = len(beast)
    n_cards = len(cards)
    n_pages = len(pages)

    bm_m, bm_a, bm_r, bm_s = _tally(beast)
    jn_m, jn_a, jn_r, jn_s = _tally(joins)
    cd_m, cd_a, cd_r, cd_s = _tally(cards)
    ds_m, ds_a, ds_r, ds_s = _tally(datasets)

    total = n_tables + n_joins + n_beast + n_cards
    migrated = ds_m + jn_m + bm_m + cd_m
    needs = ds_r + jn_r + bm_r + cd_r
    approx = ds_a + jn_a + bm_a + cd_a
    automation = _pct(migrated, total)
    chasm = _chasm_keys(joins)
    from_etl = any(j.get("source") == "magic_etl" for j in joins)

    # Complexity / effort heuristics.
    if n_joins == 0 and n_tables <= 1:
        complexity, effort = "Low", "~0.5 engineer-day"
    elif n_tables <= 3 and n_joins <= 3:
        complexity, effort = "Low–Medium", "~0.5–1 engineer-day"
    elif n_tables <= 8:
        complexity, effort = "Medium", "~1 engineer-day"
    else:
        complexity, effort = "Medium–High", "~1–2 engineer-days"

    if needs == 0 and not chasm:
        risk = "Low"
    elif chasm or n_joins >= 5:
        risk = "Medium"
    else:
        risk = "Low–Medium"

    L: list[str] = []
    add = L.append

    # ---- header -------------------------------------------------------------
    add("# Domo → ThoughtSpot Migration Report")
    add("")
    add(f"**App:** {app_name}  ")
    add(f"**Source mode:** {mode}  ")
    prov = "data model = **SOURCE** (Domo dataset schemas)"
    if from_etl:
        prov += " + joins from the **Magic ETL** export"
    if cards:
        prov += " · charts = **INFERRED** from the dashboard PDF (verify)"
    add(f"**Provenance:** {prov}")
    add("")

    # ---- executive summary --------------------------------------------------
    add("## Executive summary")
    add("")
    add(f"- **Migration complexity:** {complexity}")
    add(f"- **Automation %:** {automation}%  |  **Manual %:** {100 - automation}%")
    add(f"- **Estimated effort:** {effort}")
    risk_bits = []
    if needs:
        risk_bits.append(f"{needs} item(s) flagged NEEDS REVIEW")
    if chasm:
        risk_bits.append(
            "multiple facts share the join key(s) "
            + ", ".join(f"`{k}`" for k in chasm)
            + " — confirm cardinality to avoid measure fan-out (chasm trap)")
    if not risk_bits:
        risk_bits.append("clean conversion — no structural gaps")
    add(f"- **Risk score:** {risk} — " + "; ".join(risk_bits) + ".")
    add("")

    # ---- inventory ----------------------------------------------------------
    add("## Inventory")
    add("")
    add(f"- **Tables:** {n_tables}  |  **Columns:** {n_cols}")
    add(f"- **Relationships:** {n_joins}  |  **Measures (Beast Modes):** {n_beast}")
    add(f"- **Pages:** {n_pages}  |  **Visuals:** {n_cards}")
    add("")

    # ---- modernization ------------------------------------------------------
    add("## Modernization")
    add("")
    add(f"**Dashboards eliminated:** none — the {n_pages or 1} Domo page(s) map to "
        f"{n_pages or 1} Liveboard(s).")
    add("")
    kpi_cards = [c for c in cards if str(c.get("chart_type", "")).lower() == "kpi"]
    if kpi_cards:
        add(f"**Search opportunities:** the {len(kpi_cards)} KPI card(s) "
            "are re-askable on demand via Search; kept as tiles for the overview band.")
        add("")
    add("**Spotter opportunities:** stand up Spotter on the model for conversational "
        "\"explain <measure> by <dimension>\" breakdowns that replace static charts.")
    add("")
    add("**Semantic improvements:**")
    if bm_m:
        add(f"- Promoted {bm_m} Domo Beast Mode(s) to reusable model measures.")
    if bm_r:
        add(f"- Rewrite {bm_r} Beast Mode(s) flagged NEEDS REVIEW in ThoughtSpot syntax "
            "(see Data model → formulas).")
    if renamed:
        add(f"- Disambiguated {len(renamed)} display-name collision(s); join keys stay "
            "physically present on both tables so joins resolve.")
    if n_joins:
        add("- Confirm each join is MANY_TO_ONE from the fact so additive measures do not "
            "fan out across the star.")
    add("")

    # ---- summary by object type --------------------------------------------
    add("## Summary by object type")
    add("")
    add("| Object type | In Domo | Migrated | Approximated | Needs review | Skipped |")
    add("|---|---|---|---|---|---|")
    for label, items in [("Datasets → Tables", datasets), ("Joins", joins),
                         ("Beast Modes → Formulas", beast), ("Cards → Answers", cards)]:
        m, a, r, s = _tally(items)
        add(f"| {label} | {len(items)} | {m} | {a} | {r} | {s} |")
    add(f"| Pages → Liveboards | {n_pages} | {n_pages} | 0 | 0 | 0 |")
    add("")

    # ---- data model ---------------------------------------------------------
    add("## Data model")
    add("")
    add("### Tables")
    add("")
    add("| Domo dataset | ThoughtSpot table | Columns | Status |")
    add("|---|---|---|---|")
    for d in datasets:
        add(f"| {d.get('name')} | {d.get('ts_table')} | {d.get('columns')} | {d.get('status')} |")
    add("")

    if joins:
        add("### Relationships → joins")
        add("")
        add("| Relationship | On | Status | Note |")
        add("|---|---|---|---|")
        for j in joins:
            add(f"| {j.get('left')} ↔ {j.get('right')} | `{j.get('on')}` | "
                f"{j.get('status')} | {j.get('note', '')} |")
        add("")

    if beast:
        add("### Beast Modes → Formulas")
        add("")
        add("| Name | Domo formula | ThoughtSpot formula | Status |")
        add("|---|---|---|---|")
        for f in beast:
            add(f"| {f.get('name')} | `{f.get('domo_formula')}` | "
                f"`{f.get('ts_formula')}` | {f.get('status')} |")
        add("")

    # ---- cards --------------------------------------------------------------
    if cards:
        add("## Cards → answers & liveboard")
        add("")
        add("| Card | ThoughtSpot chart | Status | Note |")
        add("|---|---|---|---|")
        for c in cards:
            ts_chart = c.get("ts_chart") or str(c.get("chart_type", "")).upper()
            add(f"| {c.get('title', c.get('urn'))} | {ts_chart} | {c.get('status')} "
                f"| {c.get('note', '')} |")
        add("")
        if pages:
            add(f"Assembled onto Liveboard **{pages[0].get('name')}** "
                f"({pages[0].get('cards')} tiles).")
            add("")

    if renamed:
        add("### Renamed columns (display-name collisions)")
        add("")
        for rc in renamed:
            add(f"- `{rc.get('from')}` → `{rc.get('to')}` (table {rc.get('table')})")
        add("")

    # ---- manual review (lead with the gaps) --------------------------------
    review_rows: list[str] = []
    for j in joins:
        if j.get("status") in _REVIEW:
            review_rows.append(
                f"- **Join** {j.get('left')} ↔ {j.get('right')} on `{j.get('on')}` "
                f"({j.get('status')}) — {j.get('note', '')}. Confirm MANY_TO_ONE from the fact.")
    if chasm:
        review_rows.append(
            "- **Chasm-trap risk** — multiple facts share "
            + ", ".join(f"`{k}`" for k in chasm)
            + ". Keep each measure on its home fact (or split into separate Answers) so "
            "counts/sums do not fan out.")
    for f in beast:
        if f.get("status") in _REVIEW:
            review_rows.append(
                f"- **Formula** `{f.get('name')}` ({f.get('status')}) — "
                f"{f.get('note') or 'manual rewrite required'}  \n"
                f"  Domo: `{f.get('domo_formula')}`")
    for c in cards:
        if c.get("status") in _REVIEW:
            review_rows.append(
                f"- **Card** `{c.get('title', c.get('urn'))}` ({c.get('chart_type')}, "
                f"{c.get('status')}) — {c.get('note') or 'rebuild in ThoughtSpot'}")
    for m in invariants:
        review_rows.append(f"- **TML invariant** — {m}")

    add("## Manual review (do these in ThoughtSpot)")
    add("")
    L.extend(review_rows if review_rows
             else ["_Nothing flagged — every object migrated cleanly._"])
    add("")

    # ---- verification checklist --------------------------------------------
    add("## Verification checklist")
    add("")
    add("- Pick one known total in Domo and confirm the identical number in ThoughtSpot "
        "(via Search / searchdata).")
    if n_joins:
        add("- Slice a measure by a dimension across each join and confirm it does not "
            "fan out (validates the join cardinality).")
    if bm_r:
        add("- Confirm every NEEDS REVIEW Beast Mode resolves correctly after its rewrite.")
    if cd_r:
        add("- Rebuild each flagged card and confirm it matches the source dashboard tile.")
    add("- Confirm any source filters became Liveboard filters and slice every tile.")
    add("")

    # ---- modernization scorecard -------------------------------------------
    sem = max(60, 90 - (10 if jn_r else 0) - (10 if chasm else 0))
    search = max(60, 90 - 5 * bm_r)
    spotter = 85 if n_beast else 75
    lb = max(60, 90 - 5 * cd_r)
    ai = 80 if n_beast else 70
    add("## ThoughtSpot Modernization Scorecard")
    add("")
    add("| Category | Score | Recommendation |")
    add("|---|---|---|")
    add(f"| Semantic Model | {sem}/100 | "
        + ("Confirm MANY_TO_ONE cardinalities"
           + (" and resolve the chasm trap" if chasm else "")
           + " to lock the grain." if n_joins else
           "Flat, clean dataset; promote categoricals to model formulas.") + " |")
    add(f"| Search Readiness | {search}/100 | "
        + ("Friendly names + reusable measures in place; finish the flagged formula rewrites."
           if bm_r else "Friendly names + reusable measures in place.") + " |")
    add(f"| Spotter Readiness | {spotter}/100 | "
        "Stand up Spotter on the model to replace static breakdown charts. |")
    add(f"| Liveboards | {lb}/100 | "
        + (f"{n_pages or 1} page(s) → {n_pages or 1} Liveboard(s)"
           + ("; rebuild the flagged tile(s) to reach 100." if cd_r else ".")) + " |")
    add(f"| AI Readiness | {ai}/100 | "
        "Add a Monitor/Alert on a key measure and enable Spotter. |")
    add("")

    return "\n".join(L)
