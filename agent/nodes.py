"""Graph node logic as plain functions (easy to unit-test with a fake LLM)."""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from . import db, prompts
from .audit import log_event
from .sql_guard import UnsafeSQLError, extract_sql, validate_sql

MAX_ATTEMPTS = 3


class AgentState(TypedDict, total=False):
    question: str
    schema: str
    sql: str                 # current candidate query
    generated_sql: str       # what the LLM first proposed (kept for the audit log)
    error: str | None
    attempts: int
    review_action: str       # approve / edit / reject / auto
    columns: list[str]
    rows: list[list[Any]]
    chart: dict | None
    answer: str
    status: str              # done / rejected / failed


def _content(msg: Any) -> str:
    content = getattr(msg, "content", msg)
    if isinstance(content, list):  # some providers return content blocks
        content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content)


def load_schema(state: AgentState, db_path=db.DEFAULT_DB) -> AgentState:
    return {"schema": db.get_schema(db_path), "attempts": state.get("attempts", 0), "error": None}


def generate_sql(state: AgentState, llm) -> AgentState:
    messages = [("system", prompts.SQL_SYSTEM.format(schema=state["schema"])), ("human", state["question"])]
    if state.get("error") and state.get("sql"):
        messages.append(("ai", f"```sql\n{state['sql']}\n```"))
        messages.append(("human", prompts.SQL_RETRY.format(sql=state["sql"], error=state["error"])))
    sql = extract_sql(_content(llm.invoke(messages)))
    update: AgentState = {"sql": sql, "attempts": state.get("attempts", 0) + 1, "error": None}
    if not state.get("generated_sql"):
        update["generated_sql"] = sql
    return update


def guard_sql(state: AgentState) -> AgentState:
    try:
        return {"sql": validate_sql(state["sql"]), "error": None}
    except UnsafeSQLError as e:
        update: AgentState = {"error": f"Guardrail: {e}"}
        if state.get("attempts", 0) >= MAX_ATTEMPTS:
            update.update(status="failed", answer=f"Generated query kept failing the guardrail: {e}")
        return update


def apply_review(state: AgentState, decision: dict | None) -> AgentState:
    """Turn a reviewer decision into a state update. decision = {"action": ..., "sql": ...}."""
    decision = decision or {"action": "approve"}
    action = decision.get("action", "approve")
    log_event("review", question=state.get("question"), proposed_sql=state.get("sql"), action=action,
              edited_sql=decision.get("sql") if action == "edit" else None)
    if action == "reject":
        return {"review_action": "reject", "status": "rejected",
                "answer": "Query rejected by the reviewer, nothing was executed."}
    if action == "edit":
        try:
            return {"review_action": "edit", "sql": validate_sql(decision.get("sql", "")), "error": None}
        except UnsafeSQLError as e:
            return {"review_action": "edit", "status": "failed", "error": f"Guardrail: {e}",
                    "answer": f"Edited query blocked by guardrail: {e}"}
    return {"review_action": action}


def execute_sql(state: AgentState, db_path=db.DEFAULT_DB) -> AgentState:
    try:
        cols, rows = db.run_query(state["sql"], db_path)
    except Exception as e:  # sqlite3.Error, timeouts, etc. -> fed back to the LLM
        update: AgentState = {"error": f"{type(e).__name__}: {e}"}
        if state.get("attempts", 0) >= MAX_ATTEMPTS:
            update.update(status="failed", answer=f"Could not build a working query after "
                                                  f"{MAX_ATTEMPTS} attempts. Last error: {e}")
        return update
    log_event("executed", question=state.get("question"), sql=state["sql"], rows=len(rows))
    return {"columns": cols, "rows": rows, "error": None, "chart": suggest_chart(cols, rows)}


def suggest_chart(cols: list[str], rows: list[list]) -> dict | None:
    """Simple heuristic: first text column as x, first numeric column as y."""
    if len(rows) < 2 or len(cols) < 2:
        return None
    sample = rows[0]
    numeric = [c for c, v in zip(cols, sample) if isinstance(v, (int, float)) and not isinstance(v, bool)]
    text = [c for c, v in zip(cols, sample) if isinstance(v, str)]
    if not numeric or not text:
        return None
    x = text[0]
    kind = "line" if any(k in x.lower() for k in ("month", "date", "week", "day")) else "bar"
    return {"type": kind, "x": x, "y": numeric[0]}


def to_markdown(cols: list[str], rows: list[list], limit: int = 20) -> str:
    if not cols:
        return "(no columns)"
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows[:limit]]
    return "\n".join(lines)


def summarize(state: AgentState, llm) -> AgentState:
    rows, cols = state.get("rows", []), state.get("columns", [])
    shown = min(len(rows), 20)
    msg = prompts.ANSWER_USER.format(question=state["question"], sql=state["sql"], n_rows=len(rows),
                                     shown=shown, table=to_markdown(cols, rows, shown))
    answer = _content(llm.invoke([("system", prompts.ANSWER_SYSTEM), ("human", msg)])).strip()
    return {"answer": answer, "status": "done"}


# ---- routing -------------------------------------------------------------

def route_after_guard(state: AgentState) -> Literal["human_review", "generate_sql", "end"]:
    if not state.get("error"):
        return "human_review"
    return "generate_sql" if state.get("attempts", 0) < MAX_ATTEMPTS else "end"


def route_after_review(state: AgentState) -> Literal["execute_sql", "end"]:
    return "end" if state.get("status") in ("rejected", "failed") else "execute_sql"


def route_after_execute(state: AgentState) -> Literal["summarize", "generate_sql", "end"]:
    if not state.get("error"):
        return "summarize"
    return "end" if state.get("status") == "failed" else "generate_sql"
