<!-- currency: domo — 2026-07 (Domo Beast Mode) -->
# Domo Beast Mode → ThoughtSpot formula translation

The translation map behind `ts domo build-model`. The authoritative source is
`tools/ts-cli/ts_cli/domo/beastmode.py` (`AGG_MAP` / `FUNCTION_MAP` / `UNSUPPORTED`); this doc
must agree with the code. Strategy (same as the rest of the family): deterministically translate
the common subset; emit everything else as **NEEDS REVIEW** with the original Beast Mode
preserved — never faked. Coverage → status: `AUTO → Migrated`, `PARTIAL → Approximated`,
`MANUAL → NEEDS REVIEW`.

Beast Mode syntax is SQL-like and close to ThoughtSpot's, so most translation is two mechanical
passes plus a function-name map:

1. **Column refs**: Domo backtick-quotes columns — `` `Revenue` `` → `[Revenue]`.
2. **Function/aggregation rename** (tables below).
3. **Operators** (`+ - * / ( )`, comparisons) pass through unchanged.

## Data type mapping (dataset `schema.columns[].type`)

| Domo `type` | TS `data_type` | Default `column_type` | Notes |
|---|---|---|---|
| `STRING` | `VARCHAR` | `ATTRIBUTE` | |
| `DATETIME` | `DATE_TIME` | `ATTRIBUTE` | `DATE` if time part is always midnight; override-able |
| `DOUBLE` | `DOUBLE` | `MEASURE` | |
| `LONG` | `INT64` | `MEASURE` | override to `ATTRIBUTE` for id-like longs |

`column_type` defaults are heuristic (numeric → measure); an `overrides.json` entry wins.

## Aggregations (`AGG_MAP`)

Used both as a card column `aggregation` and inside Beast Mode formulas.

| Domo | ThoughtSpot | Status | Notes |
|---|---|---|---|
| `SUM` | `sum` | Migrated | |
| `AVG` / `AVERAGE` | `average` | Migrated | |
| `MIN` | `min` | Migrated | |
| `MAX` | `max` | Migrated | |
| `COUNT` | `count` | Migrated | |
| `COUNT(DISTINCT x)` | `unique_count(x)` | Migrated | distinct-count idiom |
| `MEDIAN` | — | NEEDS REVIEW | no clean TML aggregation keyword |
| `STDDEV` / `VARIANCE` | `stddev` / `variance` | Approximated | verify sample vs population |

## Functions (`FUNCTION_MAP`) — deterministic subset

| Domo Beast Mode | ThoughtSpot | Status | Notes |
|---|---|---|---|
| `CASE WHEN … THEN … ELSE … END` | `if (…) then … else …` | Approximated | multi-branch → nested `if` |
| `IFNULL(a,b)` / `COALESCE` | `if (isnull(a)) then b else a` | Migrated | |
| `CONCAT(a,b)` | `concat(a, b)` | Migrated | |
| `UPPER` / `LOWER` | `upper` / `lower` | Migrated | |
| `ABS` / `ROUND` / `FLOOR` / `CEIL` | `abs` / `round` / `floor` / `ceil` | Migrated | |
| `DATEDIFF(a,b)` | `diff_days(a, b)` | Approximated | confirm arg order & unit |
| `YEAR`/`MONTH`/`DAY` | `year`/`month`/`day` | Migrated | |

## Unsupported → NEEDS REVIEW (`UNSUPPORTED`)

Window/running functions (`RANK`, `LAG`, `LEAD`, running totals), fixed-function / level-of-detail
patterns, `POWER`-user date-part arithmetic Domo resolves server-side, and any function with no
ThoughtSpot equivalent. Emitted verbatim with a `NEEDS REVIEW` note — never downgraded to a
wrong-but-valid substitute.

## Worked examples (from the fixture Beast Modes)

| Beast Mode (Domo) | ThoughtSpot formula | Status |
|---|---|---|
| `SUM(\`Revenue\`) - SUM(\`Discount\`)` | `sum([Revenue]) - sum([Discount])` | Migrated |
| `SUM(\`Revenue\`) / COUNT(DISTINCT \`Transaction ID\`)` | `sum([Revenue]) / unique_count([Transaction ID])` | Migrated |
| `(SUM(\`Discount\`) / SUM(\`Revenue\`)) * 100` | `(sum([Discount]) / sum([Revenue])) * 100` | Migrated |

Formulas become `[formula_<name>]` id-referenced Model formulas so they import in a single pass
(same convention as `ts qlik`).
