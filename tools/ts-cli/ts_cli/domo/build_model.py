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


def _build_tables_and_columns(app: DomoApp, connection_name: str, db: str, schema: str,
                             type_overrides: Optional[dict]) -> tuple[dict, list, list, list]:
    """Return (table_docs, tables, model_columns, renamed_cols).

    A model cannot expose two columns with the same DISPLAY name, but a name shared
    across joined tables (typically the join key, e.g. Customer ID) must stay
    physically present on BOTH tables so the join resolves. So on a display collision
    we keep the column and disambiguate its display name (appending the table),
    leaving db_column_name = the physical name the join references.
    """
    table_docs: dict[str, dict] = {}
    tables: list[dict] = []
    columns: list[dict] = []
    renamed_cols: list[dict] = []
    used_display: set = set()

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
    return table_docs, tables, columns, renamed_cols


def _resolve_joins(app: DomoApp,
                   explicit_joins: Optional[list]) -> tuple[list, list, str]:
    """Return (joins, join_notes, join_source) — ETL-derived joins win over inference."""
    if explicit_joins is not None:
        notes = [
            (j["left_table"], j["right_table"],
             ", ".join(k["left"] for k in j.get("keys", [])))
            for j in explicit_joins]
        return explicit_joins, notes, "magic_etl"
    joins, notes = _infer_joins(app.datasets)
    return joins, notes, "shared_column_name"


def _translate_beast_modes(app: DomoApp) -> tuple[list, list]:
    """Translate global + card-local Beast Modes, deduped by (data_source_id, name)."""
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
    return translated, mapping_formulas


def _apply_join_fixes(model_tml: dict, joins: list, app: DomoApp) -> None:
    """Fix two things the shared model emitter does not, in place.

    1. A join must declare a cardinality (the emitter sets only type).
    2. A join must live on the source (FK/MANY) side ONLY — the emitter emits it on
       both tables (bidirectional), which fails model schema validation.

    The source side is the declared left_table of each join (the fact for ETL chains,
    the first dataset for inferred joins); cardinality is refined by row count when
    known, else MANY_TO_ONE.
    """
    directed = {(j["left_table"], j["right_table"]) for j in joins}
    rows_by_table = {ds.name: (ds.rows or 0) for ds in app.datasets}
    for mt in model_tml.get("model", {}).get("model_tables", []):
        name = mt.get("name")
        kept = []
        for j in mt.get("joins", []):
            other = j.get("with")
            if (name, other) not in directed:  # keep only on the source side
                continue
            here, there = rows_by_table.get(name, 0), rows_by_table.get(other, 0)
            j["cardinality"] = ("ONE_TO_MANY" if (here and there and here < there)
                                else "MANY_TO_ONE")
            kept.append(j)
        if kept:
            mt["joins"] = kept
        else:
            mt.pop("joins", None)


def _build_mapping(app: DomoApp, join_notes: list, join_source: str,
                   mapping_formulas: list, renamed_cols: list,
                   table_docs: dict) -> dict:
    invariant_findings: list[str] = []
    for fn, doc in table_docs.items():
        invariant_findings += [f"{fn}: {m}" for m in validate_tml_invariants(doc)]
    note = ("from Magic ETL join graph" if join_source == "magic_etl"
            else "inferred by shared column name")
    return {
        "source": {"mode": app.extraction_mode, "app_name": app.app_name},
        "datasets": [
            {"domo_id": d.id, "name": d.name, "ts_table": d.name,
             "columns": len(d.columns), "status": "Migrated"} for d in app.datasets],
        "joins": [
            {"left": a, "right": b, "on": k, "inferred": True, "source": join_source,
             "status": "NEEDS REVIEW", "note": note}
            for (a, b, k) in join_notes],
        "beast_modes": mapping_formulas,
        "renamed_columns": renamed_cols,
        "invariant_findings": invariant_findings,
    }


def build_model_artifacts(app: DomoApp, *, connection_name: str, db: str, schema: str,
                          model_name: Optional[str] = None,
                          type_overrides: Optional[dict] = None,
                          explicit_joins: Optional[list] = None) -> dict:
    """Build Table + Model TML + mapping.

    ``explicit_joins`` (e.g. from a Magic ETL export, see magic_etl.parse_etl) — a
    list of ``{left_table, right_table, type, keys:[{left,right}]}`` — overrides the
    shared-column-name inference. Each is still flagged NEEDS REVIEW because the
    join side/cardinality is inferred without full column lineage.
    """
    model_name = model_name or f"{app.app_name} Model"

    table_docs, tables, columns, renamed_cols = _build_tables_and_columns(
        app, connection_name, db, schema, type_overrides)
    joins, join_notes, join_source = _resolve_joins(app, explicit_joins)
    translated, mapping_formulas = _translate_beast_modes(app)

    model_tml = build_model_tml(
        model_name=model_name, connection_name=connection_name, tables=tables,
        columns=columns, joins=joins, parameters=[], translated_formulas=translated)
    _apply_join_fixes(model_tml, joins, app)

    return {
        "tables": table_docs,
        "model": {"filename": f"{_slug(model_name)}.model.tml", "tml": model_tml},
        "mapping": _build_mapping(app, join_notes, join_source, mapping_formulas,
                                  renamed_cols, table_docs),
        "counts": {"tables": len(tables), "formulas": len(translated),
                   "joins": len(joins)},
    }
