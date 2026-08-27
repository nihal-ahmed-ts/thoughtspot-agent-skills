"""The single naming authority for a Domo bundle.

Why this module exists
----------------------
A Model exposes ONE flat namespace of display names — tables, columns and formulas
all share it — but a name may legitimately repeat in the source: the same column on
two datasets (typically the join key), the same Beast Mode on two datasets, a Beast
Mode named after a column. Every one of those has to be resolved to a unique display
name, and every reference to it — in a formula body, in an Answer's columns, in a
search query — has to resolve to the *same* string, scoped to the dataset it came from.

Three review rounds of the same bug taught the shape of this module:

1. renames were applied to the Model's `columns[]` but not to formula bodies, so a
   Beast Mode on the second dataset read the first dataset's column;
2. nor to Answer columns, so a card on the second dataset grouped by the first
   dataset's column;
3. and once those were fixed, three more paths remained — a formula referencing a
   sibling formula, a Beast Mode colliding with a column name (which the shared
   `resolve_name_collisions` silently *dropped*, poisoning every other formula that
   referenced that column), and the same clash on one dataset producing a
   self-referential formula.

Each round fixed the reported path and the class survived, because the rule lived in
more than one place. So the rule lives here, once, and covers the whole namespace:

- `build_index(app)` resolves tables, columns and formulas together, in that order,
  and records every rename it had to make;
- `Index.rewrite()` resolves **dataset-scoped first**, and treats a bare global name
  as resolvable only when it is unambiguous — otherwise it is reported, never guessed;
- nothing else applies a naming rule. `build_model` and `build_liveboard` are separate
  CLI invocations that each re-parse the bundle, so the index is *derived* rather than
  passed: same bundle, same dataset order, same names.

A collision between a Beast Mode and a column renames the **formula**, never the
column. Dropping a column removes a dimension users search by, and silently repoints
every reference to it at a measure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .ir import DomoApp

# `[Column Name]` references inside a translated formula or a search query.
_REF = re.compile(r"\[([^\[\]]+)\]")


@dataclass
class Index:
    """Resolved Model display names for every table, column and formula in a bundle."""

    # dataset id -> {raw column name -> model display name}
    columns_by_dataset: dict[str, dict[str, str]] = field(default_factory=dict)
    # (dataset id, Domo Beast Mode name) -> model formula display name
    formulas_by_dataset: dict[tuple[str, str], str] = field(default_factory=dict)
    # dataset id -> model table name
    table_by_dataset: dict[str, str] = field(default_factory=dict)

    # every column display name / formula display name the Model exposes
    column_names: set[str] = field(default_factory=set)
    formula_names: set[str] = field(default_factory=set)

    # report rows
    renames: list[dict] = field(default_factory=list)          # columns
    formula_renames: list[dict] = field(default_factory=list)  # Beast Modes
    table_renames: list[dict] = field(default_factory=list)    # datasets

    # ---- lookups ---------------------------------------------------------

    def table(self, dataset_id: Optional[str]) -> Optional[str]:
        return self.table_by_dataset.get(dataset_id or "")

    def display(self, dataset_id: Optional[str], column: str) -> Optional[str]:
        """Model display name for `column` as seen from `dataset_id`."""
        return (self.columns_by_dataset.get(dataset_id or "") or {}).get(column)

    def formula(self, dataset_id: Optional[str], name: str) -> Optional[str]:
        """Model formula display name for a Beast Mode on `dataset_id`."""
        return self.formulas_by_dataset.get((dataset_id or "", name))

    def resolve(self, dataset_id: Optional[str], name: str) -> Optional[str]:
        """Resolve a Domo name to what the Model exposes, dataset-scoped first.

        Returns None when the name cannot be bound unambiguously — the caller must
        flag it rather than emit a reference that reads something else.
        """
        scoped = self.display(dataset_id, name) or self.formula(dataset_id, name)
        if scoped:
            return scoped
        # Not on this dataset. A bare name is only safe if exactly one thing in the
        # Model carries it; otherwise which one was meant is a guess.
        if name in self.formula_names and name not in self.column_names:
            owners = [ds for (ds, n) in self.formulas_by_dataset if n == name]
            if len(owners) == 1:
                return name
        return None

    def rewrite(self, expr: str, dataset_id: Optional[str]) -> tuple[str, list[str]]:
        """Rewrite `[raw]` refs in `expr` to Model display names for one dataset.

        Returns `(rewritten, unresolved)`. `[formula_*]` refs are already resolved
        ids and pass through untouched.
        """
        unresolved: list[str] = []

        def _sub(m: re.Match) -> str:
            raw = m.group(1)
            if raw.startswith("formula_"):
                return m.group(0)
            resolved = self.resolve(dataset_id, raw)
            if resolved is None:
                unresolved.append(raw)
                return m.group(0)
            return f"[{resolved}]"

        return _REF.sub(_sub, expr), unresolved


def _unique(candidate: str, taken: set[str], qualifier: str) -> str:
    """Return a name not already in `taken`, qualified then numbered."""
    if candidate.lower() not in taken:
        return candidate
    qualified = f"{candidate} ({qualifier})" if qualifier else candidate
    if qualified.lower() not in taken:
        return qualified
    n = 2
    while f"{qualified} {n}".lower() in taken:
        n += 1
    return f"{qualified} {n}"


def deduped_beast_modes(app: DomoApp) -> list:
    """Global Beast Modes then card-local calculated fields, deduped by (dataset, name).

    The ONE definition of "which Beast Modes exist". Every consumer uses this so the
    naming pass and the translation pass cannot disagree on the set or its order.
    """
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


def build_index(app: DomoApp) -> Index:
    """Resolve the whole namespace for a parsed bundle.

    Order matters and is deliberate: tables, then columns, then formulas. Columns are
    the user's search surface and formulas are derived, so a formula yields to a
    column on a clash — never the reverse.
    """
    index = Index()
    taken: set[str] = set()

    # --- tables -----------------------------------------------------------
    for ds in app.datasets:
        name = _unique(ds.name, taken, "dataset")
        if name != ds.name:
            index.table_renames.append({"dataset_id": ds.id, "from": ds.name,
                                        "to": name})
        taken.add(name.lower())
        index.table_by_dataset[ds.id] = name

    # --- columns ----------------------------------------------------------
    col_taken: set[str] = set()
    for ds in app.datasets:
        table = index.table_by_dataset[ds.id]
        per_id: dict[str, str] = {}
        for c in ds.columns:
            display = _unique(c.name, col_taken, table)
            if display != c.name:
                index.renames.append({"table": table, "from": c.name, "to": display})
            col_taken.add(display.lower())
            per_id[c.name] = display
            index.column_names.add(display)
        index.columns_by_dataset[ds.id] = per_id

    # --- formulas ---------------------------------------------------------
    # Share the column namespace: a Beast Mode named after a column must be renamed,
    # because the Model cannot expose both and dropping the column is destructive.
    name_taken = set(col_taken)
    for bm in deduped_beast_modes(app):
        table = index.table_by_dataset.get(bm.data_source_id) or ""
        name = _unique(bm.name, name_taken, table)
        if name != bm.name:
            reason = ("collides with a column name" if bm.name.lower() in col_taken
                      else "the same Beast Mode name exists on another dataset")
            index.formula_renames.append({
                "dataset": table, "from": bm.name, "to": name, "reason": reason})
        name_taken.add(name.lower())
        index.formulas_by_dataset[(bm.data_source_id or "", bm.name)] = name
        index.formula_names.add(name)

    return index


# Backwards-compatible aliases (the module was introduced as ColumnIndex /
# build_column_index one review round earlier).
ColumnIndex = Index
build_column_index = build_index
