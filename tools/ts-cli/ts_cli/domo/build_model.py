"""DomoApp IR -> Table TML(s) + Model TML + mapping report.

Pure: returns dicts the command layer serializes with tml_common.dump_tml_yaml.
Delegates model assembly to ts_cli.model_builder.build_model_tml (shared emitter).
"""
from __future__ import annotations

from typing import Optional

from ts_cli.databricks.mv_tml import validate_tml_invariants
from ts_cli.model_builder import build_model_tml

from .functions import translate
from .ir import Dataset, DomoApp

# Domo dataset type -> ThoughtSpot data_type
_TYPE_MAP = {
    "STRING": "VARCHAR", "DATETIME": "DATE_TIME", "DATE": "DATE",
    "DOUBLE": "DOUBLE", "LONG": "INT64", "BOOLEAN": "BOOL",
}
_NUMERIC_TS = {"DOUBLE", "INT64"}


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in (s or "")).strip("_") or "obj"


def _ts_type(domo_type: str, overrides: Optional[dict] = None, col_name: str = "") -> str:
    if overrides and col_name in overrides:
        return overrides[col_name]
    return _TYPE_MAP.get((domo_type or "STRING").upper(), "VARCHAR")


def _col_type(ts_type: str) -> str:
    return "MEASURE" if ts_type in _NUMERIC_TS else "ATTRIBUTE"


def _build_table_doc(ds: Dataset, connection_name: str, db: str, schema: str,
                     overrides: Optional[dict]) -> dict:
    columns = []
    for c in ds.columns:
        ts_type = _ts_type(c.domo_type, overrides, c.name)
        column_type = _col_type(ts_type)
        props = {"column_type": column_type}
        if column_type == "MEASURE":
            props["aggregation"] = "SUM"
        columns.append({
            "name": c.name,
            "db_column_name": c.name,
            "properties": props,
            "db_column_properties": {"data_type": ts_type},
        })
    return {"table": {
        "name": ds.name, "db": db, "schema": schema, "db_table": ds.name,
        "connection": {"name": connection_name}, "columns": columns,
    }}


def _infer_joins(datasets: list[Dataset]) -> tuple[list[dict], list[tuple]]:
    """Domo carries no join metadata — infer by shared column name and flag."""
    joins: list[dict] = []
    notes: list[tuple] = []
    for i in range(len(datasets)):
        for j in range(i + 1, len(datasets)):
            a, b = datasets[i], datasets[j]
            shared = {c.name for c in a.columns} & {c.name for c in b.columns}
            for key in sorted(shared):
                joins.append({
                    "left_table": a.name, "right_table": b.name, "type": "LEFT_OUTER",
                    "keys": [{"left": key, "right": key}],
                })
                notes.append((a.name, b.name, key))
    return joins, notes


def build_model_artifacts(app: DomoApp, *, connection_name: str, db: str, schema: str,
                          model_name: Optional[str] = None,
                          type_overrides: Optional[dict] = None) -> dict:
    model_name = model_name or f"{app.app_name} Model"

    tables: list[dict] = []
    table_docs: dict[str, dict] = {}
    columns: list[dict] = []
    # A model cannot expose two columns with the same DISPLAY name, but a name
    # shared across joined tables (typically the join key, e.g. Customer ID) must
    # stay physically present on BOTH tables so the join resolves. So on a display
    # collision we keep the column and disambiguate its display name (appending the
    # table), leaving db_column_name = the physical name the join references.
    used_display: set = set()
    renamed_cols: list[dict] = []
    for ds in app.datasets:
        table_docs[f"{_slug(ds.name)}.table.tml"] = _build_table_doc(
            ds, connection_name, db, schema, type_overrides)
        tables.append({"name": ds.name, "db_table": ds.name})
        for c in ds.columns:
            ts_type = _ts_type(c.domo_type, type_overrides, c.name)
            display = c.name
            if display.lower() in used_display:
                display = f"{c.name} ({ds.name})"
                renamed_cols.append({"table": ds.name, "from": c.name, "to": display})
            used_display.add(display.lower())
            columns.append({
                "name": display, "db_column_name": c.name, "table": ds.name,
                "column_type": _col_type(ts_type),
            })

    joins, join_notes = _infer_joins(app.datasets)

    # Beast Modes: global + card-local, deduped by (data_source_id, name).
    all_bm = list(app.beast_modes)
    for card in app.cards:
        all_bm.extend(card.calc_fields)
    seen: set = set()
    translated: list[dict] = []
    mapping_formulas: list[dict] = []
    for bm in all_bm:
        if not bm.name or (bm.data_source_id, bm.name) in seen:
            continue
        seen.add((bm.data_source_id, bm.name))
        ts_expr, review, reason = translate(bm.formula)
        translated.append({"name": bm.name, "expr": ts_expr, "column_type": "MEASURE"})
        mapping_formulas.append({
            "name": bm.name, "domo_formula": bm.formula, "ts_formula": ts_expr,
            "status": "NEEDS REVIEW" if review else "Migrated", "note": reason,
        })

    model_tml = build_model_tml(
        model_name=model_name, connection_name=connection_name, tables=tables,
        columns=columns, joins=joins, parameters=[], translated_formulas=translated)

    # Two model-join fixes the shared emitter doesn't apply:
    #  1. A join must declare a cardinality (emitter sets only type).
    #  2. A join must live on the FK/source (MANY) side ONLY — the emitter emits
    #     it on both tables (bidirectional), which fails model schema validation.
    # Derive the MANY side from row counts (larger table = fact = MANY side).
    rows_by_table = {ds.name: (ds.rows or 0) for ds in app.datasets}
    for mt in model_tml.get("model", {}).get("model_tables", []):
        here = rows_by_table.get(mt.get("name"), 0)
        kept = []
        for j in mt.get("joins", []):
            there = rows_by_table.get(j.get("with"), 0)
            if here >= there:  # this is the MANY side — keep the join here
                j["cardinality"] = "MANY_TO_ONE"
                kept.append(j)
            # else: ONE side — drop; the join belongs on the MANY side entry
        if kept:
            mt["joins"] = kept
        else:
            mt.pop("joins", None)

    invariant_findings: list[str] = []
    for fn, doc in table_docs.items():
        invariant_findings += [f"{fn}: {m}" for m in validate_tml_invariants(doc)]

    mapping = {
        "source": {"mode": app.extraction_mode, "app_name": app.app_name},
        "datasets": [
            {"domo_id": d.id, "name": d.name, "ts_table": d.name,
             "columns": len(d.columns), "status": "Migrated"} for d in app.datasets],
        "joins": [
            {"left": a, "right": b, "on": k, "inferred": True,
             "status": "NEEDS REVIEW", "note": "inferred by shared column name"}
            for (a, b, k) in join_notes],
        "beast_modes": mapping_formulas,
        "renamed_columns": renamed_cols,
        "invariant_findings": invariant_findings,
    }
    counts = {"tables": len(tables), "formulas": len(translated), "joins": len(joins)}
    return {
        "tables": table_docs,
        "model": {"filename": f"{_slug(model_name)}.model.tml", "tml": model_tml},
        "mapping": mapping,
        "counts": counts,
    }
