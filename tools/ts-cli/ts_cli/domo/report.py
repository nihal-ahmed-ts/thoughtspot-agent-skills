"""Render a human-readable migration report (Markdown) from the mapping JSON(s).

Same spirit as the qlik/looker migration reports: lead with everything that needs
a human, then account for every object with a status. Pure function: dicts in,
Markdown string out.
"""
from __future__ import annotations

from typing import Optional

_REVIEW = {"NEEDS REVIEW", "Approximated", "Skipped"}


def render_report(mapping: dict, lb_mapping: Optional[dict] = None) -> str:
    src = mapping.get("source", {})
    datasets = mapping.get("datasets", [])
    joins = mapping.get("joins", [])
    beast = mapping.get("beast_modes", [])
    renamed = mapping.get("renamed_columns", [])
    invariants = mapping.get("invariant_findings", [])
    cards = (lb_mapping or {}).get("cards", [])
    pages = (lb_mapping or {}).get("pages", [])

    def _tally(items):
        m = a = r = 0
        for it in items:
            s = it.get("status", "Migrated")
            if s == "Migrated":
                m += 1
            elif s == "Approximated":
                a += 1
            else:
                r += 1
        return m, a, r

    L: list[str] = []
    L.append(f"# Domo → ThoughtSpot Migration Report")
    L.append("")
    L.append(f"**App:** {src.get('app_name', 'Untitled')}  ")
    L.append(f"**Source mode:** {src.get('mode', 'offline')}")
    L.append("")

    # Summary
    L.append("## Summary")
    L.append("")
    L.append("| Object type | Count | Migrated | Approximated | NEEDS REVIEW |")
    L.append("|---|---|---|---|---|")
    for label, items in [("Datasets → Tables", datasets), ("Joins", joins),
                         ("Beast Modes → Formulas", beast), ("Cards → Answers", cards)]:
        m, a, r = _tally(items)
        L.append(f"| {label} | {len(items)} | {m} | {a} | {r} |")
    L.append("")

    # NEEDS REVIEW first
    review_rows: list[str] = []
    for j in joins:
        if j.get("status") in _REVIEW:
            review_rows.append(f"- **Join** {j.get('left')} ↔ {j.get('right')} on `{j.get('on')}` — {j.get('note', '')}")
    for f in beast:
        if f.get("status") in _REVIEW:
            review_rows.append(f"- **Formula** `{f.get('name')}` — {f.get('note') or f.get('status')}  \n  Domo: `{f.get('domo_formula')}`")
    for c in cards:
        if c.get("status") in _REVIEW:
            review_rows.append(f"- **Card** `{c.get('title', c.get('urn'))}` ({c.get('chart_type')}) — {c.get('note') or c.get('status')}")
    for m in invariants:
        review_rows.append(f"- **TML invariant** — {m}")
    L.append("## ⚠️ Needs review")
    L.append("")
    L.extend(review_rows if review_rows else ["_Nothing flagged — every object migrated cleanly._"])
    L.append("")

    # Detail: datasets
    L.append("## Datasets → Tables")
    L.append("")
    L.append("| Domo dataset | ThoughtSpot table | Columns | Status |")
    L.append("|---|---|---|---|")
    for d in datasets:
        L.append(f"| {d.get('name')} | {d.get('ts_table')} | {d.get('columns')} | {d.get('status')} |")
    L.append("")

    # Detail: beast modes
    if beast:
        L.append("## Beast Modes → Formulas")
        L.append("")
        L.append("| Name | Domo formula | ThoughtSpot formula | Status |")
        L.append("|---|---|---|---|")
        for f in beast:
            L.append(f"| {f.get('name')} | `{f.get('domo_formula')}` | `{f.get('ts_formula')}` | {f.get('status')} |")
        L.append("")

    # Detail: cards
    if cards:
        L.append("## Cards → Answers")
        L.append("")
        L.append("| Card | Chart type | Status |")
        L.append("|---|---|---|")
        for c in cards:
            L.append(f"| {c.get('title', c.get('urn'))} | {c.get('chart_type')} | {c.get('status')} |")
        L.append("")
        if pages:
            L.append(f"Assembled onto Liveboard **{pages[0].get('name')}** ({pages[0].get('cards')} tiles).")
            L.append("")

    if renamed:
        L.append("## Renamed columns (display-name collisions)")
        L.append("")
        for rc in renamed:
            L.append(f"- `{rc.get('from')}` → `{rc.get('to')}` (table {rc.get('table')})")
        L.append("")

    return "\n".join(L)
