"""Domo Beast Mode → ThoughtSpot formula translation.

Kept in sync with agents/shared/mappings/domo/beastmode-thoughtspot-formula-translation.md.
Strategy (family convention): deterministically translate the common subset; flag
everything else NEEDS REVIEW with the original preserved — never a wrong-but-valid
substitute. `translate()` returns (ts_formula, review_required, reason).
"""
from __future__ import annotations

import re

# Domo Beast Mode function/aggregation name -> ThoughtSpot function.
# None = no ThoughtSpot equivalent -> flag NEEDS REVIEW.
FUNCTION_MAP: dict[str, str | None] = {
    # --- aggregations ---
    "sum": "sum", "avg": "average", "average": "average", "min": "min", "max": "max",
    "count": "count", "stddev": "stddev", "stdev": "stddev",
    "variance": "variance", "var": "variance",
    "median": None, "percentile": None,
    # --- math ---
    "abs": "abs", "round": "round", "floor": "floor", "ceil": "ceil", "ceiling": "ceil",
    "power": "pow", "pow": "pow", "sqrt": "sqrt", "exp": "exp", "ln": "ln", "log": "log",
    "mod": "mod", "sign": "sign",
    # --- string ---
    "concat": "concat", "upper": "upper", "lower": "lower", "trim": "trim",
    "ltrim": "ltrim", "rtrim": "rtrim", "length": "strlen", "len": "strlen",
    "substring": "substring", "substr": "substring", "replace": "replace",
    "left": "left", "right": "right", "instr": "strpos",
    # --- date ---
    "year": "year", "month": "month", "day": "day", "hour": "hour", "minute": "minute",
    "quarter": "quarter", "week": "week", "now": "now", "current_date": "today",
    "datediff": "diff_days", "date_diff": "diff_days",
    # --- type ---
    "to_number": "to_double", "to_double": "to_double", "to_char": "to_string",
    "to_string": "to_string", "to_date": "to_date",
    # --- structural / unsupported -> NEEDS REVIEW (manual rewrite; see the
    #     mapping doc for the recommended ThoughtSpot form) ---
    "ifnull": None, "coalesce": None, "nullif": None, "cast": None,
    "rank": None, "row_number": None, "lag": None, "lead": None, "running_total": None,
}

# ThoughtSpot function names we emit ourselves — must not be flagged as "unknown"
# when the token pass re-scans the translated string.
_KNOWN_TS = {v for v in FUNCTION_MAP.values() if v} | {
    "unique_count", "unique", "if", "isnull", "to_string", "to_double",
    "diff_hours", "diff_minutes", "add_days", "add_months",
}

# Constructs the token-based translator cannot faithfully rewrite -> flag NEEDS REVIEW.
_UNSUPPORTED_RE = re.compile(
    r"\bcase\s+when\b|\bover\s*\(|\bpartition\s+by\b", re.IGNORECASE)

_BACKTICK = re.compile(r"`([^`]+)`")
# COUNT(DISTINCT [col]) -> unique_count([col])  (runs after backtick->bracket)
_COUNT_DISTINCT = re.compile(
    r"\bcount\s*\(\s*distinct\s+(\[[^\]]+\])\s*\)", re.IGNORECASE)
_FUNC_TOKEN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def translate(expr: str) -> tuple[str, bool, str]:
    """Translate a Domo Beast Mode expression into a ThoughtSpot formula."""
    if not expr or not expr.strip():
        return "", True, "empty formula"

    reasons: list[str] = []
    review = False

    # 0. structural constructs the token translator can't faithfully rewrite
    #    (multi-branch CASE, window/OVER) -> emit verbatim, flag for manual rewrite.
    if _UNSUPPORTED_RE.search(expr):
        return expr, True, "contains CASE WHEN / window construct — manual rewrite required"

    # 1. column refs: `Col Name` -> [Col Name]
    out = _BACKTICK.sub(lambda m: f"[{m.group(1)}]", expr)
    # 2. COUNT(DISTINCT [x]) -> unique count([x])
    #    ThoughtSpot's distinct-count formula function is `unique count` (a space,
    #    NOT an underscore); `unique_count`/`count_distinct` are rejected by the
    #    formula parser.
    out = _COUNT_DISTINCT.sub(lambda m: f"unique count({m.group(1)})", out)

    # 3. function-name remap (Domo -> ThoughtSpot); flag unknown / unsupported
    def _repl(m: re.Match) -> str:
        nonlocal review
        fn = m.group(1)
        low = fn.lower()
        if low == "distinct":  # leftover from a non-count DISTINCT
            return m.group(0)
        if low in FUNCTION_MAP:
            mapped = FUNCTION_MAP[low]
            if mapped is None:
                review = True
                reasons.append(f"function '{fn}' has no ThoughtSpot equivalent")
                return m.group(0)
            return f"{mapped}("
        if low in _KNOWN_TS:  # already a TS function we emitted (e.g. unique_count)
            return f"{low}("
        review = True
        reasons.append(f"unrecognized function '{fn}'")
        return m.group(0)

    out = _FUNC_TOKEN.sub(_repl, out)
    reason = "; ".join(dict.fromkeys(reasons)) if review else ""
    return out, review, reason
