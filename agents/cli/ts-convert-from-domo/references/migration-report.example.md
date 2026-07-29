# Domo → ThoughtSpot Migration Report

**App:** Sales Overview  
**Source mode:** offline

## Summary

| Object type | Count | Migrated | Approximated | NEEDS REVIEW |
|---|---|---|---|---|
| Datasets → Tables | 2 | 2 | 0 | 0 |
| Joins | 1 | 0 | 0 | 1 |
| Beast Modes → Formulas | 3 | 3 | 0 | 0 |
| Cards → Answers | 3 | 3 | 0 | 0 |

## ⚠️ Needs review

- **Join** Customer Master ↔ Sample Sales Transactions on `Customer ID` — inferred by shared column name

## Datasets → Tables

| Domo dataset | ThoughtSpot table | Columns | Status |
|---|---|---|---|
| Customer Master | Customer Master | 6 | Migrated |
| Sample Sales Transactions | Sample Sales Transactions | 10 | Migrated |

## Beast Modes → Formulas

| Name | Domo formula | ThoughtSpot formula | Status |
|---|---|---|---|
| Net Revenue | `SUM(`Revenue`) - SUM(`Discount`)` | `sum([Revenue]) - sum([Discount])` | Migrated |
| Avg Order Value | `SUM(`Revenue`) / COUNT(DISTINCT `Transaction ID`)` | `sum([Revenue]) / unique count([Transaction ID])` | Migrated |
| Discount Rate % | `(SUM(`Discount`) / SUM(`Revenue`)) * 100` | `(sum([Discount]) / sum([Revenue])) * 100` | Migrated |

## Cards → Answers

| Card | Chart type | Status |
|---|---|---|
| Net Revenue | kpi | Migrated |
| Revenue by Region | bar | Migrated |
| Sales Rep Performance | table | Migrated |

Assembled onto Liveboard **Sales Overview** (3 tiles).

## Renamed columns (display-name collisions)

- `Customer ID` → `Customer ID (Sample Sales Transactions)` (table Sample Sales Transactions)
