# Migration report format (`mapping.json`)

`ts domo build-model` and `build-liveboard` both write/extend `mapping.json` — the single
deliverable that accounts for every Domo object and its conversion status. Same shape as the rest
of the family so downstream tooling and the audit mode can read all converters uniformly.

## Status vocabulary
- **Migrated** — faithful 1:1 conversion.
- **Approximated** — converted with a documented approximation (verify).
- **NEEDS REVIEW** — emitted verbatim or skipped; a human must rebuild/verify.
- **Skipped** — intentionally not converted (with reason).

## Shape

```json
{
  "source": { "mode": "offline|domo-cloud", "app_name": "Sales Overview" },
  "datasets": [
    { "domo_id": "61c4e63d-…", "name": "Sample Sales Transactions",
      "ts_table": "Sample Sales Transactions", "columns": 10, "status": "Migrated" }
  ],
  "joins": [
    { "left": "…", "right": "…", "on": "Customer ID", "inferred": true,
      "status": "NEEDS REVIEW", "note": "inferred by shared column name" }
  ],
  "beast_modes": [
    { "domo_id": 1001, "name": "Net Revenue",
      "domo_formula": "SUM(`Revenue`) - SUM(`Discount`)",
      "ts_formula": "sum([Revenue]) - sum([Discount])", "status": "Migrated" }
  ],
  "cards": [
    { "urn": "606665948", "title": "Net Revenue", "chart_type": "kpi",
      "ts_chart": "KPI", "status": "Migrated", "notes": [] }
  ],
  "pages": [
    { "domo_id": 421696155, "name": "Sales Overview",
      "ts_liveboard": "Sales Overview", "cards": 3, "tabs": 1, "status": "Migrated" }
  ],
  "notes": [
    { "object_type": "beast_mode", "object_id": 1099, "severity": "needs_review",
      "message": "window function RANK() has no ThoughtSpot equivalent — left verbatim" }
  ]
}
```

## Rules
- **Every** dataset, Beast Mode, card and page appears exactly once with a status.
- Every `NEEDS REVIEW` / `Approximated` row carries a `note` explaining the gap and the original
  Domo definition, so a human can rebuild without re-opening Domo.
- Inferred joins are **always** `NEEDS REVIEW`.
- The report is the hand-off: when presenting, lead with the NEEDS REVIEW rows.
