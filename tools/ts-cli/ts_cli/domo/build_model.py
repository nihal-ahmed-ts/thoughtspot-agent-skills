"""DomoApp IR -> Table TML(s) + Model TML + mapping report.

Pure: returns dicts the command layer serializes with tml_common.dump_tml_yaml.
Delegates model assembly to ts_cli.model_builder.build_model_tml (shared emitter).
"""
from __future__ import annotations

import re
from typing import Optional

from ts_cli.databricks.mv_tml import validate_tml_invariants
from ts_cli.formula_common import resolve_name_collisions
from ts_cli.model_builder import build_model_tml

from .functions import translate
from .ir import Dataset, DomoApp
from .naming import ColumnIndex, build_column_index

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


# An id-like column name: a trailing `id`/`key`/`code`/`urn` TOKEN, not a trailing
# substring — `endswith("id")` also matched Paid, Void, Valid, Rapid and Overpaid, so
# two tables could end up joined on a boolean flag.
_KEY_TOKENS = {"id", "ids", "key", "keys", "code", "codes", "urn", "guid", "uuid", "pk", "fk"}
_KEY_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _looks_like_key(name: str) -> bool:
    """True when the LAST word of the name is an id-like token.

    Splits camelCase humps before lowercasing, so `customerId` tokenizes to
    ["customer", "id"] and matches, while `Paid`/`Void`/`Valid`/`Rapid` do not.
    """
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name.strip())
    tokens = [t for t in _KEY_TOKEN_RE.split(spaced.lower()) if t]
    return bool(tokens) and tokens[-1] in _KEY_TOKENS


def _pick_join_key(shared: set[str]) -> tuple[str | None, str]:
    """Choose ONE join key for a dataset pair. Returns (key, note_suffix)."""
    ranked = sorted(shared)
    keyish = [c for c in ranked if _looks_like_key(c)]
    if len(keyish) == 1:
        others = [c for c in ranked if c != keyish[0]]
        if others:
            return keyish[0], (f"joined on '{keyish[0]}'; {len(others)} other shared "
                               f"column(s) ({', '.join(others)}) were not used")
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
                             type_overrides: Optional[dict],
                             index: ColumnIndex) -> tuple[dict, list, list, list]:
    """Return (table_docs, tables, model_columns, renamed_cols).

    Display names come from the shared `ColumnIndex`. The collision rule itself lives
    in ts_cli/domo/naming.py so that the formula bodies and the Answer columns resolve
    through exactly the same mapping — see that module for why.
    """
    table_docs: dict[str, dict] = {}
    tables: list[dict] = []
    columns: list[dict] = []

    for ds in app.datasets:
        table_docs[f"{_slug(ds.name)}.table.tml"] = _build_table_doc(
            ds, connection_name, db, schema, type_overrides)
        tables.append({"name": ds.name, "db_table": ds.name})
        for c in ds.columns:
            ts_type = _ts_type(c.domo_type, type_overrides, c.name)
            columns.append({
                "name": index.display(ds.id, c.name) or c.name,
                "db_column_name": c.name, "table": ds.name,
                "column_type": _col_type(ts_type),
            })
    return table_docs, tables, columns, list(index.renames)


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


# Translations that are mapped but need a human to confirm semantics: marker -> the
# caveat to report. `build_model_tml` derives each formula's id from its NAME, so a
# duplicate name means a duplicate id (see _translate_beast_modes).
_APPROXIMATE_MARKERS: tuple[tuple[str, str], ...] = (
    ("diff_days(", "DATEDIFF → diff_days assumes DAY grain and ThoughtSpot argument "
                   "order (a−b) — verify the sign and the unit"),
    ("stddev(", "verify sample vs population"),
    ("variance(", "verify sample vs population"),
)


def _formula_status(ts_expr: str, review: bool) -> tuple[str, str]:
    """Map a translation onto the report's three-value status vocabulary."""
    if review:
        return "NEEDS REVIEW", ""
    low = ts_expr.lower()
    for marker, caveat in _APPROXIMATE_MARKERS:
        if marker in low:
            return "Approximated", caveat
    return "Migrated", ""


def _dedupe_beast_modes(app: DomoApp) -> list:
    """Global Beast Modes then card-local calculated fields, deduped by (dataset, name)."""
    all_bm = list(app.beast_modes)
    for card in app.cards:
        all_bm.extend(card.calc_fields)
    seen: set = set()
    out = []
    for bm in all_bm:
        key = (bm.data_source_id or "", bm.name)
        if not bm.name or key in seen:
            continue
        seen.add(key)
        out.append(bm)
    return out


def _translate_one(bm, index: ColumnIndex) -> tuple[str, str, list[str]]:
    """Translate one Beast Mode. Returns (ts_expr, status, notes)."""
    ts_expr, review, reason = translate(bm.formula)

    # Bind the formula to the Model's names for ITS dataset. Without this a Beast Mode
    # defined on the second dataset reads the FIRST dataset's column of the same name —
    # a clean import with wrong numbers.
    ts_expr, unresolved = index.rewrite(ts_expr, bm.data_source_id)
    if unresolved:
        review = True
        reason = "; ".join(x for x in [
            reason,
            "references column(s) the Model does not expose: "
            + ", ".join(sorted(set(unresolved)))] if x)

    status, extra = _formula_status(ts_expr, review)

    # A flagged formula is emitted VERBATIM — by definition not valid ThoughtSpot
    # syntax. Left bare it makes the whole model TML unimportable, so the user loses
    # every other measure too. Wrap it in a comment marker, as ts_cli/qlik does: the
    # rest of the model imports and the original survives for the human.
    if review:
        ts_expr = f"/* TODO review: {ts_expr} */"

    return ts_expr, status, [x for x in (reason, extra) if x]


def _translate_beast_modes(app: DomoApp, index: ColumnIndex) -> tuple[list, list]:
    """Translate every Beast Mode into a Model formula + a mapping-report row.

    Names come from the shared ColumnIndex (see ts_cli/domo/naming.py): a Beast Mode
    name used by two datasets must be disambiguated because `build_model_tml` derives
    the formula id from the name, and a card referencing the renamed one has to resolve
    to the same string. Both facts live in one place so the stages cannot disagree.
    """
    ds_name = {d.id: d.name for d in app.datasets}
    translated: list[dict] = []
    mapping_formulas: list[dict] = []

    for bm in _dedupe_beast_modes(app):
        name = index.formula(bm.data_source_id, bm.name) or bm.name
        ts_expr, status, notes = _translate_one(bm, index)
        if name != bm.name:
            notes.append(f"renamed from '{bm.name}' — the same Beast Mode name exists on "
                         "another dataset and formula ids must be unique")
        translated.append({"name": name, "expr": ts_expr, "column_type": "MEASURE"})
        mapping_formulas.append({
            "name": name, "domo_name": bm.name, "domo_formula": bm.formula,
            # The owning dataset — needed to verify the formula binds to the right
            # table, which is not derivable from the name once names collide.
            "dataset": ds_name.get(bm.data_source_id) or "",
            "dataset_id": bm.data_source_id or "",
            "ts_formula": ts_expr, "status": status, "note": "; ".join(notes),
        })
    return translated, mapping_formulas


# Domo `relationshipType` -> what we can honestly assert about cardinality.
# ThoughtSpot has no many-to-many join, so MTM cannot be expressed at all: emitting
# MANY_TO_ONE over it silently changes the grain. Only the directional forms are
# trusted; anything else falls back to the row-count heuristic and says so.
_DOMO_CARDINALITY = {
    "MTO": "MANY_TO_ONE",
    "MANY_TO_ONE": "MANY_TO_ONE",
    "OTM": "ONE_TO_MANY",
    "ONE_TO_MANY": "ONE_TO_MANY",
    "OTO": "ONE_TO_ONE",
    "ONE_TO_ONE": "ONE_TO_ONE",
}
_DOMO_UNSUPPORTED_CARDINALITY = {"MTM", "MANY_TO_MANY"}


def _declared_cardinality(join: dict) -> tuple[Optional[str], Optional[str]]:
    """Return (cardinality, warning) from the join's Domo `relationshipType`."""
    declared = str(join.get("domo_relationship") or "").strip().upper()
    if not declared:
        return None, None
    if declared in _DOMO_UNSUPPORTED_CARDINALITY:
        return None, (
            f"{join.get('left_table')} ↔ {join.get('right_table')}: Domo declares this "
            "relationship MANY-TO-MANY, which ThoughtSpot cannot express as a join. "
            "The emitted cardinality is a row-count guess — a many-to-many needs a "
            "bridge table, and measures WILL fan out until it has one")
    mapped = _DOMO_CARDINALITY.get(declared)
    if mapped:
        return mapped, None
    return None, (f"{join.get('left_table')} ↔ {join.get('right_table')}: unrecognized "
                  f"Domo relationshipType {declared!r} — cardinality inferred instead")


def _apply_join_fixes(model_tml: dict, joins: list, app: DomoApp) -> None:
    """Fix two things the shared model emitter does not, in place.

    1. A join must declare a cardinality (the emitter sets only type).
    2. A join must live on the source (FK/MANY) side ONLY — the emitter emits it on
       both tables (bidirectional), which fails model schema validation.

    The source side is the declared left_table of each join (the fact for ETL chains,
    the first dataset for inferred joins); cardinality is refined by row count when
    known, else MANY_TO_ONE.
    """
    directed = {(j["left_table"], j["right_table"]): j for j in joins}
    rows_by_table = {ds.name: (ds.rows or 0) for ds in app.datasets}
    for mt in model_tml.get("model", {}).get("model_tables", []):
        name = mt.get("name")
        kept = []
        for j in mt.get("joins", []):
            other = j.get("with")
            source = directed.get((name, other))
            if source is None:  # keep only on the source side
                continue
            declared, _warning = _declared_cardinality(source)
            if declared:
                j["cardinality"] = declared
            else:
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

    index = build_column_index(app)
    table_docs, tables, columns, renamed_cols = _build_tables_and_columns(
        app, connection_name, db, schema, type_overrides, index)
    joins, join_notes, join_source, join_warnings = _resolve_joins(app, explicit_joins)
    translated, mapping_formulas = _translate_beast_modes(app, index)

    rows_by_table = {ds.name: (ds.rows or 0) for ds in app.datasets}
    # `join_warnings` so far are genuine DROPS; orientation/cardinality notes are
    # advisory and must not be counted as dropped joins.
    joins_dropped = len(join_warnings)
    join_warnings += _orient_joins(joins, rows_by_table)
    for j in joins:
        _c, warning = _declared_cardinality(j)
        if warning:
            join_warnings.append(warning)
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
        # report parsed-but-dropped ETL joins. `joins_dropped` counts DROPS only; the
        # advisory orientation/cardinality notes live in mapping["join_warnings"].
        "counts": {"tables": len(tables), "formulas": len(translated),
                   "joins": len(joins), "joins_dropped": joins_dropped},
    }
