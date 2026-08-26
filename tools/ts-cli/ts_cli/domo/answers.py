"""DomoApp IR -> Answers embedded in one Liveboard TML.

The Liveboard is a single page of tiles — Domo `collectionIds` / page `children` are
NOT translated into Liveboard tabs (see the skill's coverage matrix).

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


def _ordered_columns(card: Card) -> tuple[list[str], list[str], list[str]]:
    """Return (attrs, measures, ordered) — group-by first, then measures, deduped."""
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
    return attrs, measures, attrs + measures


def _search_query(card: Card, ordered: list[str], ctype: str) -> str:
    parts = [f"[{c}]" for c in ordered]
    if card.query.limit and ctype != "kpi":
        parts.append(f"top {card.query.limit}")
    return " ".join(parts)


def _answer_shell(card: Card, model_name: str, model_fqn: Optional[str],
                  ordered: list[str], search_query: str) -> dict:
    table_ref = {"id": model_name, "name": model_name}
    if model_fqn:
        table_ref["fqn"] = model_fqn
    return {
        "name": card.title or "Untitled",
        "tables": [table_ref],
        "search_query": search_query,
        "answer_columns": [{"name": c} for c in ordered],
        # The `table` block is required on every viz, chart or not.
        "table": {
            "table_columns": [{"column_id": c, "show_headline": False} for c in ordered],
            "ordered_column_ids": ordered,
            "client_state": "",
            "client_state_v2": '{"tableVizPropVersion": "V1"}',
        },
    }


def _apply_display_mode(answer: dict, card: Card, ctype: str, attrs: list[str],
                        measures: list[str], ordered: list[str]) -> tuple[bool, str]:
    """Set display_mode (+ chart block). Return (review, reason)."""
    if ctype == "table":
        answer["display_mode"] = "TABLE_MODE"
        return False, ""
    if ctype in _CHART_MAP:
        # A chart needs chart_columns + axis_configs (x=attributes, y=measures);
        # an empty/absent axis is what triggers the importer's "Index: 0" error.
        answer["display_mode"] = "CHART_MODE"
        answer["chart"] = {
            "type": _CHART_MAP[ctype],
            "chart_columns": [{"column_id": c} for c in ordered],
            "axis_configs": [{"x": attrs, "y": measures}],
            "client_state": "",
        }
        return False, ""
    answer["display_mode"] = "TABLE_MODE"
    return True, f"unmapped Domo chartType '{card.chart_type}' — rendered as table"


def _answer(card: Card, model_name: str, model_fqn: Optional[str]) -> tuple[dict, bool, str]:
    attrs, measures, ordered = _ordered_columns(card)
    ctype = card.chart_type.lower()
    answer = _answer_shell(card, model_name, model_fqn, ordered,
                           _search_query(card, ordered, ctype))
    review, reason = _apply_display_mode(answer, card, ctype, attrs, measures, ordered)
    return answer, review, reason


def _describe_sort(card: Card) -> Optional[str]:
    if not card.query.order_by:
        return None
    return "sort (%s)" % ", ".join(
        f"{o.column} {o.order}".strip() for o in card.query.order_by)


def _describe_filters(card: Card) -> Optional[str]:
    if not card.query.filters:
        return None
    return "card filter(s) (%s)" % ", ".join(
        f"{f.column} {f.operand}".strip() for f in card.query.filters)


def _describe_quick_filters(card: Card) -> Optional[str]:
    if not card.quick_filters:
        return None
    return "quick filter(s) (%s)" % ", ".join(
        str(f.get("column") or f.get("name") or "?") for f in card.quick_filters)


def _describe_conditional_formats(card: Card) -> Optional[str]:
    if not card.conditional_formats:
        return None
    return f"conditional formatting ({len(card.conditional_formats)} rule(s))"


def _describe_number_formats(card: Card) -> Optional[str]:
    formatted = [c.column for c in card.query.columns if c.fmt]
    if not formatted:
        return None
    return "number format on %s" % ", ".join(formatted)


def _describe_aggregation_overrides(card: Card) -> Optional[str]:
    """A card can override the aggregation per column (MIN/MAX/AVG/COUNT).

    The Answer carries no aggregation, so the Model default (SUM for numerics)
    applies — a `MIN(Price)` card would otherwise silently render as `SUM(Price)`.
    """
    overrides = [f"{c.column}={c.aggregation.upper()}" for c in card.query.columns
                 if c.aggregation and c.aggregation.upper() not in ("SUM", "")]
    if not overrides:
        return None
    return ("non-SUM aggregation (%s) — the Answer falls back to the Model default"
            % ", ".join(overrides))


# Each describer returns a human-readable string, or None when the card does not
# carry that construct. Adding a newly-dropped construct means adding one describer.
_DROPPED_DESCRIBERS = (
    _describe_sort,
    _describe_filters,
    _describe_quick_filters,
    _describe_conditional_formats,
    _describe_number_formats,
    _describe_aggregation_overrides,
)


def _dropped_constructs(card: Card) -> list[str]:
    """Constructs present on the Domo card that the emitted Answer does NOT carry.

    These are parsed into the IR but not translated (see references/open-items.md #11).
    Reporting them per card is the point: without this, a card whose sort, date filter
    and quick filters were all left behind still counted as fully "Migrated", which is
    exactly the silent downgrade this converter is supposed to refuse to do.
    """
    return [d for d in (describe(card) for describe in _DROPPED_DESCRIBERS) if d]


def _viz_guid() -> str:
    return str(uuid.uuid4())


def _card_mapping_row(card: Card, ans: dict, review: bool, reason: str,
                      dropped: list[str]) -> dict:
    """One card's row in the liveboard mapping — the report's source of truth."""
    notes = [reason] if reason else []
    if dropped:
        notes.append("not carried onto the Answer — rebuild by hand: "
                     + "; ".join(dropped))
    return {
        "urn": card.urn, "title": card.title, "chart_type": card.chart_type,
        "ts_chart": ans.get("chart", {}).get("type", "TABLE"),
        "status": ("NEEDS REVIEW" if review
                   else "Approximated" if dropped else "Migrated"),
        "note": " | ".join(notes),
        "dropped_constructs": dropped,
    }


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
    row_h = 0
    idx = 0
    for urn in order:
        card = card_by_urn.get(str(urn))
        if not card:
            mapping_cards.append({"urn": str(urn), "status": "Skipped",
                                  "note": "card id in page not found among cards"})
            continue
        idx += 1
        ans, review, reason = _answer(card, model_name, model_fqn)
        dropped = _dropped_constructs(card)
        vid = f"Viz_{idx}"
        vizzes.append({"id": vid, "answer": ans, "viz_guid": _viz_guid()})
        w = max(card.pref_width or 6, 3)
        h = max(card.pref_height or 4, 2)
        if x + w > 12:
            # Advance by the TALLEST tile in the row being closed, not by the height of
            # the tile that happens to wrap — otherwise a short tile wrapping under a
            # tall one lands inside it and the tiles overlap.
            x = 0
            y += row_h
            row_h = 0
        tiles.append({"visualization_id": vid, "x": x, "y": y, "width": w, "height": h})
        x += w
        row_h = max(row_h, h)
        mapping_cards.append(_card_mapping_row(card, ans, review, reason, dropped))

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
