"""Single source of truth for Domo column -> ThoughtSpot Model display names.

Why this module exists
----------------------
A Model cannot expose two columns with the same DISPLAY name, but a name shared
across joined tables (typically the join key) must stay physically present on both
tables or the join stops resolving. So a colliding column keeps its physical
`db_column_name` and gets a disambiguated display name (`Revenue (Refunds)`).

That rename has to be applied in three places which previously computed it — or
failed to compute it — independently:

1. the Model's `columns[]` (it did),
2. the body of every translated Beast Mode formula (it did NOT — `sum([Revenue])`
   defined on Refunds silently bound to `Orders::Revenue`),
3. every Answer's `answer_columns` / `search_query` (it did NOT — same failure).

Beast Mode (formula) names are resolved here for the same reason. Two datasets may
carry the same Beast Mode name, so one of them is renamed — and a card referencing the
renamed one would otherwise emit the original name and dangle.

`build-model` and `build-liveboard` are separate CLI invocations that each re-parse
the bundle, so passing a rename map between them is not possible without a file
handshake. The fix is to make the mapping a **pure function of the parsed IR**:
both stages call `build_column_index(app)` and get byte-identical answers because
the dataset order and the collision rule are deterministic.

Every consumer resolves through `ColumnIndex`. Nothing recomputes the rule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .ir import DomoApp

# `[Column Name]` references inside a translated formula or a search query.
_REF = re.compile(r"\[([^\[\]]+)\]")


@dataclass
class ColumnIndex:
    """Resolved display names for every (dataset, column) in a bundle."""

    # dataset id -> {raw column name -> model display name}
    by_dataset: dict[str, dict[str, str]] = field(default_factory=dict)
    # dataset NAME -> {raw column name -> model display name}
    by_table: dict[str, dict[str, str]] = field(default_factory=dict)
    # every column display name the Model exposes
    display_names: set[str] = field(default_factory=set)
    # report rows: [{table, from, to}]
    renames: list[dict] = field(default_factory=list)
    # (dataset id, Domo Beast Mode name) -> Model formula display name
    formulas: dict[tuple[str, str], str] = field(default_factory=dict)
    # every formula display name the Model exposes
    formula_names: set[str] = field(default_factory=set)
    # Beast Mode renames, for the report: [{dataset, from, to}]
    formula_renames: list[dict] = field(default_factory=list)

    def display(self, dataset_id: Optional[str], column: str) -> Optional[str]:
        """Display name for `column` as seen from `dataset_id`, or None."""
        return (self.by_dataset.get(dataset_id or "") or {}).get(column)

    def formula(self, dataset_id: Optional[str], name: str) -> Optional[str]:
        """Model formula display name for a Beast Mode on `dataset_id`, or None."""
        return self.formulas.get((dataset_id or "", name))

    def resolve(self, dataset_id: Optional[str], name: str) -> Optional[str]:
        """Resolve a Domo name to what the Model exposes — column or formula."""
        return (self.display(dataset_id, name)
                or self.formula(dataset_id, name)
                or (name if name in self.formula_names else None))

    def rewrite(self, expr: str, dataset_id: Optional[str]) -> tuple[str, list[str]]:
        """Rewrite `[raw]` refs in `expr` to Model display names for one dataset.

        Returns `(rewritten, unresolved)`. A ref is unresolved when it names no
        column on that dataset AND no display name the Model exposes — that is a
        reference the Model cannot bind, so the caller must flag it rather than
        ship a formula that silently reads the wrong column.
        """
        scoped = self.by_dataset.get(dataset_id or "") or {}
        unresolved: list[str] = []

        def _sub(m: re.Match) -> str:
            raw = m.group(1)
            if raw.startswith("formula_"):       # formula-to-formula reference
                return m.group(0)
            if raw in scoped:
                return f"[{scoped[raw]}]"
            if raw in self.display_names or raw in self.formula_names:
                return m.group(0)                # already a name the Model exposes
            formula = self.formula(dataset_id, raw)
            if formula:
                return f"[{formula}]"
            unresolved.append(raw)
            return m.group(0)

        return _REF.sub(_sub, expr), unresolved


def build_column_index(app: DomoApp) -> ColumnIndex:
    """Compute the display-name mapping for a parsed bundle.

    Deterministic: driven only by `app.datasets` order (which `parse_app` derives
    from a sorted file glob) and the first-wins collision rule. Two independent CLI
    invocations over the same bundle therefore produce the same index.
    """
    index = ColumnIndex()
    used: set[str] = set()
    for ds in app.datasets:
        per_id: dict[str, str] = {}
        per_table: dict[str, str] = {}
        for c in ds.columns:
            display = c.name
            if display.lower() in used:
                display = f"{c.name} ({ds.name})"
                index.renames.append({"table": ds.name, "from": c.name, "to": display})
            used.add(display.lower())
            per_id[c.name] = display
            per_table[c.name] = display
            index.display_names.add(display)
        index.by_dataset[ds.id] = per_id
        index.by_table[ds.name] = per_table
    _index_formulas(app, index)
    return index


def deduped_beast_modes(app: DomoApp) -> list:
    """Global Beast Modes then card-local calculated fields, deduped by (dataset, name).

    The ONE definition of "which Beast Modes exist". `build_model` consumes this rather
    than re-deriving it: the naming rule below and the translation loop must agree on
    both the set and its order, or the formula ids stop matching the references — which
    is the class of divergence that produced the wrong-table bindings in the first place.
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


def _index_formulas(app: DomoApp, index: ColumnIndex) -> None:
    """Resolve Beast Mode display names, in place.

    A name used by more than one dataset is disambiguated with the dataset name.
    `build_model_tml` derives each formula's id from this name, so it must be unique.
    """
    all_bm = deduped_beast_modes(app)
    ds_name = {d.id: d.name for d in app.datasets}
    counts: dict[str, int] = {}
    for bm in all_bm:
        counts[bm.name] = counts.get(bm.name, 0) + 1

    used: set = set()
    for bm in all_bm:
        key = (bm.data_source_id or "", bm.name)
        name = bm.name
        if counts.get(bm.name, 0) > 1 and name in used:
            suffix = ds_name.get(bm.data_source_id) or str(bm.data_source_id)
            name = f"{bm.name} ({suffix})"
        candidate, i = name, 2
        while candidate in used:
            candidate, i = f"{name} {i}", i + 1
        name = candidate
        used.add(name)

        index.formulas[key] = name
        index.formula_names.add(name)
        if name != bm.name:
            index.formula_renames.append({
                "dataset": ds_name.get(bm.data_source_id) or "",
                "from": bm.name, "to": name})
