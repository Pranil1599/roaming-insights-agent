"""End-to-end graph tests with a fake LLM (no API key needed)."""
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("langgraph")

from conftest import FakeLLM, make_db  # noqa: E402

from agent.graph import Session, build_graph  # noqa: E402

DB = make_db(Path(tempfile.mkdtemp()))
GOOD = "```sql\nSELECT agreement_status, COUNT(*) AS n FROM partners GROUP BY 1\n```"


def test_pauses_for_review_then_runs():
    s = Session(build_graph(FakeLLM([GOOD, "There are 3 statuses."]), db_path=DB))
    out = s.ask("partners by status")
    assert out["needs_review"] and "GROUP BY" in out["review"]["sql"]
    assert "rows" not in out  # nothing executed before approval

    out = s.review("approve")
    assert not out["needs_review"] and out["status"] == "done" and len(out["rows"]) >= 2


def test_reject_executes_nothing():
    s = Session(build_graph(FakeLLM([GOOD]), db_path=DB))
    s.ask("partners by status")
    out = s.review("reject")
    assert out["status"] == "rejected" and "rows" not in out


def test_edit_runs_reviewer_sql():
    s = Session(build_graph(FakeLLM([GOOD, "24 partners."]), db_path=DB))
    s.ask("how many partners")
    out = s.review("edit", "SELECT COUNT(*) AS partners FROM partners")
    assert out["columns"] == ["partners"] and out["review_action"] == "edit"


def test_self_correction_loop_without_approval():
    llm = FakeLLM(["```sql\nSELECT missing FROM partners\n```", GOOD, "ok"])
    s = Session(build_graph(llm, db_path=DB, require_approval=False))
    out = s.ask("partners by status")
    assert out["status"] == "done" and out["attempts"] == 2
