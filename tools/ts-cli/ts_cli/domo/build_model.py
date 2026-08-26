"""DomoApp IR -> Table TML(s) + Model TML + mapping report.

Pure: returns dicts the command layer serializes with tml_common.dump_tml_yaml.
Delegates model assembly to ts_cli.model_builder.build_model_tml (shared emitter).
"""
from __future__ import annotations

from typing import Optional

from ts_cli.databricks.mv_tml import validate_tml_invariants
from ts_cli.formula_common import resolve_name_collisions
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


# Columns whose shared name is almost never a real relationship — joining on them
# silently fans out measures. A pair whose ONLY shared column is one of these is not
# joined at all; it is reported instead.
_INCIDENTAL_KEYS = {
    "date", "day", "month", "year", "quarter", "week", "region", "country", "state",
    "city", "status", "type", "category", "name", "description", "created_at",
    "updated_at", "currency", "segment",
}


def _looks_like_key(name: str) -> bool:
    low = name.strip().lower()
    return low.endswith("id") or low.endswith("_key") or low.endswith(" key") \
        or low.endswith("code") or low.endswith("urn")


def _pick_join_key(shared: set[str]) -> tuple[str | None, str]:
    """Choose ONE join key for a dataset pair. Returns (key, note_suffix)."""
    ranked = sorted(shared)
    keyish = [c for c in ranked if _looks_like_key(c)]
    if len(keyish) == 1:
        return keyish[0], ""
    if len(keyish) > 1:
        return keyish[0], (f"{len(keyish)} id-like columns shared "
                           f"({', '.join(keyish)}) — picked the first")
    meaningful = [c for c in ranked if c.strip().lower() not in _INCIDENTAL_KEYS]
    if not meaningful:
        return None, (f"only incidental column(s) shared ({', '.join(ranked)}) — "
                      "no join inferred; supply --etl or join by hand")
    return meaningful[0], (f"no id-like column shared; picked '{meaningful[0]}' from "
                           f"{', '.join(ranked)}")


def _infer_joins(datasets: list[Dataset]) -> tuple[list[dict], list[tuple], list[str]]:
    """Domo carries no join metadata — infer ONE join per dataset pair, and flag.

    Emitting one join per shared column (the previous behaviour) produced duplicate
    `with:` entries for the same table pair and joined on incidental names like
    `Region` or `Date`, which fans measures out across the star.
    """
    joins: list[dict] = []
    notes: list[tuple] = []
    warnings: list[str] = []
    for i in range(len(datasets)):
        for j in range(i + 1, len(datasets)):
            a, b = datasets[i], datasets[j]
            shared = {c.name for c in a.columns} & {c.name for c in b.columns}
            if not shared:
                continue
            key, note = _pick_join_key(shared)
            if key is None:
                warnings.append(f"{a.name} ↔ {b.name}: {note}")
                continue
            if note:
                warnings.append(f"{a.name} ↔ {b.name}: {note}")
            joins.append({
                "left_table": a.name, "right_table": b.name, "type": "LEFT_OUTER",
                "keys": [{"left": key, "right": key}],
            })
            notes.append((a.name, b.name, key))
    return joins, notes, warnings


def _orient_joins(joins: list[dict], rows_by_table: dict[str, int]) -> list[str]:
    """Put each join on the MANY (fact) side, in place. Returns notes.

    The join must live on the source/FK side only. Which dataset that is was
    previously decided by bundle iteration order (i.e. filename sort), so the same
    two datasets could emit MANY_TO_ONE or ONE_TO_MANY depending on file names.
    Row counts decide it when known.
    """
    notes: list[str] = []
    for j in joins:
        left, right = j.get("left_table"), j.get("right_table")
        lr, rr = rows_by_table.get(left, 0), rows_by_table.get(right, 0)
        if lr and rr and lr < rr:
            # left is the smaller (dimension) side — flip so the join sits on the fact
            j["left_table"], j["right_table"] = right, left
            j["keys"] = [{"left": k.get("right"), "right": k.get("left")}
                         for k in j.get("keys", [])]
        elif not (lr and rr):
            notes.append(
                f"{left} ↔ {right}: row counts unknown, so the many-side could not be "
                f"determined — join placed on '{left}'. Confirm the direction.")
    return notes


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
                   explicit_joins: Optional[list]) -> tuple[list, list, str, list[str]]:
    """Return (joins, join_notes, join_source, warnings).

    ETL-derived joins win over inference, but only those whose table names actually
    resolve to a dataset in this bundle. Magic ETL carries dataflow ACTION names, which
    often differ from dataset names — unmatched joins were previously counted and
    reported while being silently dropped from the TML.
    """
    if explicit_joins is not None:
        known = {d.name for d in app.datasets}
        matched, warnings = [], []
        for j in explicit_joins:
            left, right = j.get("left_table"), j.get("right_table")
            missing = [t for t in (left, right) if t not in known]
            if missing:
                warnings.append(
                    f"ETL join {left} ↔ {right}: {', '.join(missing)} does not match any "
                    "dataset in the bundle (Magic ETL uses dataflow action names) — "
                    "join dropped")
                continue
            matched.append(j)
        notes = [(j["left_table"], j["right_table"],
                  ", ".join(k["left"] for k in j.get("keys", [])))
                 for j in matched]
        return matched, notes, "magic_etl", warnings
    joins, notes, warnings = _infer_joins(app.datasets)
    return joins, notes, "shared_column_name", warnings


# Translations that are mapped but need a human to confirm semantics. `build_model_tml`
# derives each formula's id from its NAME, so a duplicate name means a duplicate id.
_APPROXIMATE_MARKERS = ("diff_days(", "stddev(", "variance(")


def _formula_status(ts_expr: str, review: bool) -> tuple[str, str]:
    """Map a translation onto the report's three-value status vocabulary."""
    if review:
        return "NEEDS REVIEW", ""
    low = ts_expr.lower()
    if "diff_days(" in low:
        return "Approximated", ("DATEDIFF → diff_days assumes DAY grain and TS argument "
                               "order (a−b) — verify the sign and the unit")
    if "stddev(" in low or "variance(" in low:
        return "Approximated", "verify sample vs population"
    return "Migrated", ""


def _translate_beast_modes(app: DomoApp) -> tuple[list, list]:
    """Translate global + card-local Beast Modes, deduped by (data_source_id, name).

    Names must be unique across datasets: `build_model_tml` derives each formula id
    from the name, so two datasets each carrying (say) a "Net Revenue" Beast Mode —
    ordinary in Domo — produced two formulas with the same id. Downstream dedup then
    stripped BOTH, leaving the model columns pointing at a `formula_id` that no longer
    existed (a dangling reference; import fails) while the mapping still called them
    Migrated. Collisions are therefore disambiguated by dataset.
    """
    all_bm = list(app.beast_modes)
    for card in app.cards:
        all_bm.extend(card.calc_fields)

    ds_name = {d.id: d.name for d in app.datasets}
    counts: dict[str, int] = {}
    for bm in all_bm:
        if bm.name:
            counts[bm.name] = counts.get(bm.name, 0) + 1

    seen: set = set()
    used_names: set = set()
    translated: list[dict] = []
    mapping_formulas: list[dict] = []
    for bm in all_bm:
        if not bm.name or (bm.data_source_id, bm.name) in seen:
            continue
        seen.add((bm.data_source_id, bm.name))

        name = bm.name
        if counts.get(bm.name, 0) > 1 and name in used_names:
            suffix = ds_name.get(bm.data_source_id) or str(bm.data_source_id)
            name = f"{bm.name} ({suffix})"
        n, i = name, 2
        while n in used_names:            # last-resort guard: still not unique
            n, i = f"{name} {i}", i + 1
        name = n
        used_names.add(name)

        ts_expr, review, reason = translate(bm.formula)
        status, extra = _formula_status(ts_expr, review)
        notes = [x for x in (reason, extra) if x]
        if name != bm.name:
            notes.append(f"renamed from '{bm.name}' — the same Beast Mode name exists on "
                         "another dataset and formula ids must be unique")
        translated.append({"name": name, "expr": ts_expr, "column_type": "MEASURE"})
        mapping_formulas.append({
            "name": name, "domo_name": bm.name, "domo_formula": bm.formula,
            "ts_formula": ts_expr, "status": status, "note": "; ".join(notes),
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
    joins, join_notes, join_source, join_warnings = _resolve_joins(app, explicit_joins)
    translated, mapping_formulas = _translate_beast_modes(app)

    rows_by_table = {ds.name: (ds.rows or 0) for ds in app.datasets}
    join_warnings += _orient_joins(joins, rows_by_table)
    # Re-derive the notes AFTER orientation so the report names the same sides the TML does.
    join_notes = [(j["left_table"], j["right_table"],
                   ", ".join(k["left"] for k in j.get("keys", [])))
                  for j in joins]

    # A column and a formula cannot share a display name (shared helper, used by
    # tableau / snowflake-sv / sisense / databricks) — the formula wins.
    columns, translated, _renames = resolve_name_collisions(columns, translated, [])

    model_tml = build_model_tml(
        model_name=model_name, connection_name=connection_name, tables=tables,
        columns=columns, joins=joins, parameters=[], translated_formulas=translated)
    _apply_join_fixes(model_tml, joins, app)

    mapping = _build_mapping(app, join_notes, join_source, mapping_formulas,
                             renamed_cols, table_docs)
    mapping["join_warnings"] = join_warnings
    return {
        "tables": table_docs,
        "model": {"filename": f"{_slug(model_name)}.model.tml", "tml": model_tml},
        "mapping": mapping,
        # counts describe what was EMITTED, not what was seen — the join count used to
        # report parsed-but-dropped ETL joins.
        "counts": {"tables": len(tables), "formulas": len(translated),
                   "joins": len(joins), "joins_dropped": len(join_warnings)},
    }
