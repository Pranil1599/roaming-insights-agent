"""Read-only access to the SQLite database."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "roaming.db"


def connect_readonly(db_path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    """Open the DB in read-only mode, so even a bad query cannot change data."""
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run: python data/generate_data.py")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def get_schema(db_path: Path | str = DEFAULT_DB, sample_rows: int = 3) -> str:
    """Return CREATE statements plus a few sample rows per table, for the LLM prompt."""
    con = connect_readonly(db_path)
    try:
        parts = []
        tables = con.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        for name, ddl in tables:
            cur = con.execute(f'SELECT * FROM "{name}" LIMIT {int(sample_rows)}')
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            sample = "\n".join(" | ".join(str(v) for v in r) for r in rows)
            parts.append(f"{ddl.strip()};\n/* sample rows ({' | '.join(cols)}):\n{sample}\n*/")
        return "\n\n".join(parts)
    finally:
        con.close()


def run_query(sql: str, db_path: Path | str = DEFAULT_DB, timeout_s: float = 5.0) -> tuple[list[str], list[list]]:
    """Execute a SELECT and return (columns, rows). Aborts queries running longer than timeout_s."""
    import time

    con = connect_readonly(db_path)
    deadline = time.monotonic() + timeout_s
    con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [list(r) for r in cur.fetchall()]
        return cols, rows
    finally:
        con.close()
