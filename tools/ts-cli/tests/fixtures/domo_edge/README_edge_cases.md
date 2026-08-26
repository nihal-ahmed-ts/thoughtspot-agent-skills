# Domo edge-case fixture bundle

Deliberately awkward inputs that the happy-path bundle in `../domo/` does not exercise.
Kept separate so `../domo/` stays a readable worked example (and so the committed
`migration-report.example.md` stays the clean case) while these paths still have
regression coverage.

Each file exists because a real defect shipped through the gap it covers — see the
PR #440 review:

| File | Covers |
|---|---|
| `domo_table_orders.json` / `domo_table_refunds.json` | two datasets sharing a Beast Mode name, and an id-like join key alongside incidental shared columns (`Region`, `Date`) |
| `domo_model_beastmodes.json` | string functions with no ThoughtSpot equivalent (`UPPER`, `TRIM`, `REPLACE`), a simple-form `CASE expr WHEN`, and a duplicate `Net Revenue` name across both datasets |
| `domo_card_500001_table_min_price.json` | a card with a non-SUM (`MIN`) per-column aggregation |
| `domo_liveboard_page_edge.json` | the page wiring for the card above |
