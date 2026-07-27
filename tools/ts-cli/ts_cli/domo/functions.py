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
    "sum": "sum", "avg": "average", "average": "average", "min": "min", "max": "max",
    "count": "count",
    "abs": "abs", "round": "round", "floor": "floor", "ceil": "ceil", "ceiling": "ceil",
    "sqrt": "sqrt", "power": "pow", "pow": "pow",
    "concat": "concat", "upper": "upper", "lower": "lower", "trim": "trim",
    "coalesce": "coalesce", "ifnull": "coalesce",
    "year": "year", "month": "month", "day": "day",
    # Unsupported / non-deterministic -> flag for review:
    "rank": None, "row_number": None, "lag": None, "lead": None,
    "median": None, "percentile": None,
}

# ThoughtSpot function names we emit ourselves — must not be flagged as "unknown"
# when the token pass re-scans the translated string.
_KNOWN_TS = {v for v in FUNCTION_MAP.values() if v} | {
    "unique_count", "if", "isnull", "to_string", "to_double",
}

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
