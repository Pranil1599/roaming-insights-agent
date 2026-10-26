"""Guardrails applied to every LLM-generated query before a human or the DB sees it."""
from __future__ import annotations

import re

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|truncate|grant)\b",
    re.IGNORECASE,
)
DEFAULT_LIMIT = 200


class UnsafeSQLError(ValueError):
    pass


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)


def _strip_string_literals(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def extract_sql(text: str) -> str:
    """Pull the SQL out of an LLM reply (handles ```sql fences and stray prose)."""
    fence = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    sql = fence.group(1) if fence else text
    m = re.search(r"\b(with|select)\b", sql, re.IGNORECASE)
    if m:
        sql = sql[m.start():]
    return sql.strip().rstrip(";").strip()


def validate_sql(sql: str, max_rows: int = DEFAULT_LIMIT) -> str:
    """Return a safe, single read-only statement (with a LIMIT) or raise UnsafeSQLError."""
    if not sql or not sql.strip():
        raise UnsafeSQLError("Empty query.")
    cleaned = _strip_comments(sql).strip().rstrip(";").strip()
    scan = _strip_string_literals(cleaned)
    if ";" in scan:
        raise UnsafeSQLError("Only one SQL statement is allowed.")
    if not re.match(r"^\s*(select|with)\b", scan, re.IGNORECASE):
        raise UnsafeSQLError("Only SELECT / WITH queries are allowed.")
    bad = FORBIDDEN.search(scan)
    if bad:
        raise UnsafeSQLError(f"Keyword '{bad.group(1).upper()}' is not allowed (read-only agent).")
    if not re.search(r"\blimit\s+\d+(\s*(,|offset)\s*\d+)?\s*$", scan, re.IGNORECASE):
        cleaned = f"{cleaned}\nLIMIT {max_rows}"
    return cleaned
