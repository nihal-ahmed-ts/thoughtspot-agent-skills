"""Parse a Domo Magic ETL dataflow export into base tables + a join graph.

A Magic ETL export (`{contentType, data:{actions:[...]}}`) is a deterministic data
pipeline: `LoadFromVault` = a source dataset, `MergeJoin` = a join (keys + type),
`Metadata`/`Alter Columns` = column renames, `PublishToVault` = the output dataset.

This maps cleanly to a ThoughtSpot Model's join graph — far better than inferring
joins by shared column name. Join *side* resolution (which base table owns each
key) is best-effort without column schemas, so every derived join is flagged for
review (family discipline: never a silent wrong-but-valid join).
"""
from __future__ import annotations

from typing import Any, Optional


def _actions(etl: dict) -> list[dict]:
    data = etl.get("data", etl)
    return data.get("actions", []) if isinstance(data, dict) else []


def parse_etl(etl: dict) -> dict:
    """Return {tables:[{name,dataSourceId,renames}], joins:[...], output, notes}."""
    actions = _actions(etl)
    by_id = {a.get("id"): a for a in actions}

    # Base tables (LoadFromVault) keyed by action id.
    tables: dict[str, dict] = {}
    for a in actions:
        if a.get("type") == "LoadFromVault":
            tables[a["id"]] = {
                "name": a.get("name", a["id"]),
                "dataSourceId": a.get("dataSourceId"),
                "renames": [],
            }

    # Column renames from Metadata / Alter Columns tiles -> attach to the base table.
    def _base_of(aid: Optional[str], seen: Optional[set] = None) -> Optional[str]:
        """Resolve an action id to its primary base LoadFromVault (follow step1/dep)."""
        seen = seen or set()
        if not aid or aid in seen:
            return None
        seen.add(aid)
        a = by_id.get(aid)
        if not a:
            return None
        t = a.get("type")
        if t == "LoadFromVault":
            return aid
        if t == "Metadata":
            dep = (a.get("dependsOn", {}).get("0") or {}).get("actionId")
            return _base_of(dep, seen)
        if t == "MergeJoin":
            return _base_of(a.get("step1"), seen)
        return None

    for a in actions:
        if a.get("type") == "Metadata":
            base = _base_of((a.get("dependsOn", {}).get("0") or {}).get("actionId"))
            renames = [{"from": f.get("name"), "to": f.get("rename"), "type": f.get("type")}
                       for f in a.get("fields", []) if f.get("rename") and not f.get("remove")]
            if base in tables:
                tables[base]["renames"].extend(renames)

    # Joins (MergeJoin) -> resolve each side to a base table.
    joins: list[dict] = []
    notes: list[str] = []
    for a in actions:
        if a.get("type") != "MergeJoin":
            continue
        left_base = _base_of(a.get("step1"))
        right_base = _base_of(a.get("step2"))
        keys1 = a.get("keys1", []) or []
        keys2 = a.get("keys2", []) or []
        keys = [{"left": l, "right": r} for l, r in zip(keys1, keys2)]
        jtype = (a.get("joinType", "LEFT OUTER") or "LEFT OUTER").upper().replace(" ", "_")
        lt = tables.get(left_base, {}).get("name")
        rt = tables.get(right_base, {}).get("name")
        if not lt or not rt:
            notes.append(f"join '{a.get('name')}' could not resolve to base tables — skipped")
            continue
        if lt == rt:
            notes.append(f"join '{a.get('name')}' resolved both sides to '{lt}' — skipped")
            continue
        joins.append({
            "left_table": lt, "right_table": rt, "type": jtype, "keys": keys,
            "domo_relationship": a.get("relationshipType"),
            "domo_join": a.get("name"),
            "review": True,  # side/cardinality inferred without column schemas
        })

    output = None
    for a in actions:
        if a.get("type") == "PublishToVault":
            output = a.get("name") or (a.get("dataSource", {}) or {}).get("name")

    return {
        "tables": list(tables.values()),
        "joins": joins,
        "output": output,
        "notes": notes,
    }
