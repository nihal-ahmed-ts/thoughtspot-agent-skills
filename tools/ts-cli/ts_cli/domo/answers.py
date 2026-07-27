"""DomoApp IR -> Answers embedded in one tabbed Liveboard TML.

Resolves page.card_ids -> cards (page order), one Answer per card. No shared answer
emitter exists in this codebase, so the Answer/Liveboard TML is hand-built here
(same as the qlik converter did).
"""
from __future__ import annotations

import uuid
from typing import Optional

from .ir import Card, DomoApp

# Domo chartType -> ThoughtSpot chart.type (verified enum, thoughtspot-chart-types.md)
_CHART_MAP = {
    "kpi": "KPI", "bar": "BAR", "column": "COLUMN", "line": "LINE",
    "pie": "PIE", "area": "AREA", "scatter": "SCATTER",
    # "table" is handled specially -> TABLE_MODE (no chart block)
}


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in (s or "")).strip("_") or "obj"


def _answer(card: Card, model_name: str, model_fqn: Optional[str]) -> tuple[dict, bool, str]:
    # Attributes (group-by) first, then measure columns — page order, deduped.
    attrs: list[str] = []
    measures: list[str] = []
    seen: set = set()
    for g in card.query.group_by:
        if g and g not in seen:
            seen.add(g)
            attrs.append(g)
    for c in card.query.columns:
        if c.column and c.column not in seen:
            seen.add(c.column)
            (attrs if c.column in card.query.group_by else measures).append(c.column)
    ordered = attrs + measures

    ctype = card.chart_type.lower()
    parts = [f"[{c}]" for c in ordered]
    if card.query.limit and ctype != "kpi":
        parts.append(f"top {card.query.limit}")

    table_ref = {"id": model_name, "name": model_name}
    if model_fqn:
        table_ref["fqn"] = model_fqn

    answer: dict = {
        "name": card.title or "Untitled",
        "tables": [table_ref],
        "search_query": " ".join(parts),
        "answer_columns": [{"name": c} for c in ordered],
        # The `table` block is required on every viz, chart or not.
        "table": {
            "table_columns": [{"column_id": c, "show_headline": False} for c in ordered],
            "ordered_column_ids": ordered,
            "client_state": "",
            "client_state_v2": '{"tableVizPropVersion": "V1"}',
        },
    }

    review = False
    reason = ""
    if ctype == "table":
        answer["display_mode"] = "TABLE_MODE"
    elif ctype in _CHART_MAP:
        # A chart needs chart_columns + axis_configs (x=attributes, y=measures);
        # an empty/absent axis is what triggers the importer's "Index: 0" error.
        answer["display_mode"] = "CHART_MODE"
        answer["chart"] = {
            "type": _CHART_MAP[ctype],
            "chart_columns": [{"column_id": c} for c in ordered],
            "axis_configs": [{"x": attrs, "y": measures}],
            "client_state": "",
        }
    else:
        answer["display_mode"] = "TABLE_MODE"
        review = True
        reason = f"unmapped Domo chartType '{card.chart_type}' — rendered as table"
    return answer, review, reason


def _viz_guid() -> str:
    return str(uuid.uuid4())


def build_liveboard_artifacts(app: DomoApp, *, model_name: str,
                              model_fqn: Optional[str] = None,
                              report_name: Optional[str] = None) -> dict:
    page = app.pages[0] if app.pages else None
    report_name = report_name or (page.name if page else app.app_name) or "Domo Liveboard"
    order = page.card_ids if page else [c.urn for c in app.cards]
    card_by_urn = {c.urn: c for c in app.cards}

    vizzes: list[dict] = []
    tiles: list[dict] = []
    mapping_cards: list[dict] = []
    x = y = 0
    idx = 0
    for urn in order:
        card = card_by_urn.get(str(urn))
        if not card:
            mapping_cards.append({"urn": str(urn), "status": "Skipped",
                                  "note": "card id in page not found among cards"})
            continue
        idx += 1
        ans, review, reason = _answer(card, model_name, model_fqn)
        vid = f"Viz_{idx}"
        vizzes.append({"id": vid, "answer": ans, "viz_guid": _viz_guid()})
        w = max(card.pref_width or 6, 3)
        h = max(card.pref_height or 4, 2)
        if x + w > 12:
            x = 0
            y += h
        tiles.append({"visualization_id": vid, "x": x, "y": y, "width": w, "height": h})
        x += w
        mapping_cards.append({
            "urn": card.urn, "title": card.title, "chart_type": card.chart_type,
            "status": "NEEDS REVIEW" if review else "Migrated", "note": reason,
        })

    lb_tml = {"liveboard": {
        "name": report_name,
        "visualizations": vizzes,
        "layout": {"tiles": tiles},
    }}
    mapping = {
        "pages": [{"name": report_name, "cards": len(vizzes)}],
        "cards": mapping_cards,
    }
    return {
        "liveboard": {"filename": f"{_slug(report_name)}.liveboard.tml", "tml": lb_tml},
        "mapping": mapping,
        "counts": {"cards": len(vizzes)},
    }
