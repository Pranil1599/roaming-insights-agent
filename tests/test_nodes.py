import tempfile
from pathlib import Path

from conftest import FakeLLM, make_db

from agent import nodes

TMP = Path(tempfile.mkdtemp())
DB = make_db(TMP)


def test_schema_contains_tables():
    schema = nodes.load_schema({}, db_path=DB)["schema"]
    for table in ("partners", "ireg_tests", "roaming_traffic"):
        assert f"CREATE TABLE {table}" in schema


def test_generate_sql_and_retry_prompt():
    llm = FakeLLM(["```sql\nSELECT bad_col FROM partners\n```", "```sql\nSELECT tadig FROM partners\n```"])
    state = {"question": "list partners", "schema": "schema", "attempts": 0}
    state.update(nodes.generate_sql(state, llm))
    assert state["sql"] == "SELECT bad_col FROM partners" and state["attempts"] == 1

    state.update(nodes.execute_sql(state, db_path=DB))
    assert "no such column" in state["error"]
    assert nodes.route_after_execute(state) == "generate_sql"

    state.update(nodes.generate_sql(state, llm))
    assert "no such column" in llm.calls[1][-1][1]  # error was fed back to the model
    assert state["sql"] == "SELECT tadig FROM partners"
    assert state["generated_sql"] == "SELECT bad_col FROM partners"


def test_execute_gives_up_after_max_attempts():
    state = {"sql": "SELECT nope FROM partners", "attempts": nodes.MAX_ATTEMPTS}
    state.update(nodes.execute_sql(state, db_path=DB))
    assert state["status"] == "failed"
    assert nodes.route_after_execute(state) == "end"


def test_guard_routes():
    s = {"sql": "DROP TABLE partners", "attempts": 1}
    s.update(nodes.guard_sql(s))
    assert nodes.route_after_guard(s) == "generate_sql"
    s["attempts"] = nodes.MAX_ATTEMPTS
    s.update(nodes.guard_sql(s))
    assert nodes.route_after_guard(s) == "end" and s["status"] == "failed"


def test_review_actions():
    base = {"question": "q", "sql": "SELECT 1"}
    assert nodes.route_after_review({**base, **nodes.apply_review(base, {"action": "approve"})}) == "execute_sql"
    rejected = nodes.apply_review(base, {"action": "reject"})
    assert rejected["status"] == "rejected" and nodes.route_after_review(rejected) == "end"
    edited = nodes.apply_review(base, {"action": "edit", "sql": "SELECT 2"})
    assert edited["sql"].startswith("SELECT 2")
    unsafe = nodes.apply_review(base, {"action": "edit", "sql": "DELETE FROM partners"})
    assert unsafe["status"] == "failed"


def test_execute_and_summarize():
    sql = ("SELECT p.operator_name, COUNT(*) AS fails FROM ireg_tests t JOIN partners p "
           "ON p.tadig = t.partner_tadig WHERE t.result='FAIL' GROUP BY 1 ORDER BY 2 DESC LIMIT 5")
    state = {"question": "top failing partners", "sql": sql}
    state.update(nodes.execute_sql(state, db_path=DB))
    assert state["columns"] == ["operator_name", "fails"] and len(state["rows"]) == 5
    assert state["chart"] == {"type": "bar", "x": "operator_name", "y": "fails"}

    llm = FakeLLM(["Partner X has the most failures."])
    state.update(nodes.summarize(state, llm))
    assert state["status"] == "done" and "most failures" in state["answer"]
    assert "| operator_name | fails |" in llm.calls[0][1][1]


def test_chart_line_for_months():
    assert nodes.suggest_chart(["month", "gb"], [["2026-01", 1.0], ["2026-02", 2.0]])["type"] == "line"
    assert nodes.suggest_chart(["n"], [[1], [2]]) is None
