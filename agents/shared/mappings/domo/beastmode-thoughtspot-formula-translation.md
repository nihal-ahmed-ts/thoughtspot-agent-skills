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
| `COUNT(DISTINCT x)` | `unique count(x)` | Migrated | distinct-count idiom (TS: `unique count`, a space not underscore) |
| `MEDIAN` | — | NEEDS REVIEW | no clean TML aggregation keyword |
| `STDDEV` / `VARIANCE` | `stddev` / `variance` | Approximated | verify sample vs population |

## Functions (`FUNCTION_MAP`) — deterministic 1:1 name maps (Migrated)

Function names are token-rewritten; arguments pass through unchanged.

**Math** — `ABS`→`abs`, `ROUND`→`round`, `FLOOR`→`floor`, `CEIL`/`CEILING`→`ceil`,
`POWER`/`POW`→`pow`, `SQRT`→`sqrt`, `EXP`→`exp`, `LN`→`ln`, `LOG`→`log`, `MOD`→`mod`, `SIGN`→`sign`.

**String** — `CONCAT`→`concat`, `UPPER`→`upper`, `LOWER`→`lower`, `TRIM`→`trim`, `LTRIM`→`ltrim`,
`RTRIM`→`rtrim`, `LENGTH`/`LEN`→`strlen`, `SUBSTRING`/`SUBSTR`→`substring`, `REPLACE`→`replace`,
`LEFT`→`left`, `RIGHT`→`right`, `INSTR`→`strpos`.

**Date** — `YEAR`→`year`, `MONTH`→`month`, `DAY`→`day`, `HOUR`→`hour`, `MINUTE`→`minute`,
`QUARTER`→`quarter`, `WEEK`→`week`, `NOW`→`now`, `CURRENT_DATE`→`today`.

**Type** — `TO_NUMBER`→`to_double`, `TO_CHAR`/`TO_STRING`→`to_string`, `TO_DATE`→`to_date`.

## Approximated (translated, verify)

| Domo Beast Mode | ThoughtSpot | Notes |
|---|---|---|
| `DATEDIFF(a,b)` / `DATE_DIFF` | `diff_days(a, b)` | verify arg order & unit — Domo may return b−a; TS `diff_days(a,b)` = a−b. For elapsed delivery time use `diff_days(delivered, purchase)`. |
| `STDDEV` / `VARIANCE` | `stddev` / `variance` | verify sample vs population |

## Structural / unsupported → NEEDS REVIEW

Emitted **verbatim** with a NEEDS REVIEW note — the token translator can't faithfully rewrite these,
so a human confirms the ThoughtSpot form (never a wrong-but-valid substitute):

| Domo Beast Mode | Recommended ThoughtSpot rewrite |
|---|---|
| `CASE WHEN c THEN x ELSE y END` | `if (c) then x else y` (nest for multi-branch) |
| `IFNULL(a,b)` / `COALESCE(a,b)` | `if (isnull(a)) then b else a` |
| `NULLIF(a,b)` | `if (a = b) then null else a` |
| `CAST(x AS t)` | `to_double` / `to_string` / `to_date` per target type |
| `RANK` / `ROW_NUMBER` / `LAG` / `LEAD` / running totals / `… OVER (PARTITION BY …)` | `rank` / window / `group_aggregate` — depends on intent, rebuild manually |
| `MEDIAN` / `PERCENTILE` | no clean TML keyword — rebuild manually |

## Worked examples (from the fixture Beast Modes)

| Beast Mode (Domo) | ThoughtSpot formula | Status |
|---|---|---|
| `SUM(\`Revenue\`) - SUM(\`Discount\`)` | `sum([Revenue]) - sum([Discount])` | Migrated |
| `SUM(\`Revenue\`) / COUNT(DISTINCT \`Transaction ID\`)` | `sum([Revenue]) / unique count([Transaction ID])` | Migrated |
| `(SUM(\`Discount\`) / SUM(\`Revenue\`)) * 100` | `(sum([Discount]) / sum([Revenue])) * 100` | Migrated |

Formulas become `[formula_<name>]` id-referenced Model formulas so they import in a single pass
(same convention as `ts qlik`).
