"""Execution-accuracy eval: does the agent's SQL return the same data as a reference query?

    python eval/run_eval.py [--model anthropic:claude-sonnet-4-5]

Comparison ignores column names and row order, and rounds floats to 1 decimal.
Writes eval/results.json so you can track accuracy across prompt / model changes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AUDIT_DISABLED", "1")

from agent.db import run_query  # noqa: E402
from agent.graph import Session, build_graph  # noqa: E402
from agent.llm import get_llm  # noqa: E402


def normalize(rows: list[list]) -> list[tuple]:
    def cell(v):
        return round(float(v), 1) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
    return sorted((tuple(cell(v) for v in r) for r in rows), key=repr)


def results_match(expected: list[list], got: list[list]) -> bool:
    """Match if every expected column appears (in order) within the agent's columns.
    Lets the agent return extra helpful columns (e.g. a name next to an id)."""
    if len(expected) != len(got):
        return False
    if not expected:
        return True
    n_exp, n_got = len(expected[0]), len(got[0])
    from itertools import combinations
    for idx in combinations(range(n_got), n_exp):
        if normalize([[r[i] for i in idx] for r in got]) == normalize(expected):
            return True
    return False


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model")
    args = p.parse_args()
    golden = json.loads((ROOT / "eval" / "golden.json").read_text())
    session = Session(build_graph(get_llm(args.model), require_approval=False))

    results, passed = [], 0
    for case in golden:
        _, expected = run_query(case["sql"])
        out = session.ask(case["question"])
        ok = out.get("status") == "done" and results_match(expected, out.get("rows", []))
        passed += ok
        results.append({"question": case["question"], "pass": ok, "agent_sql": out.get("sql"),
                        "attempts": out.get("attempts"), "error": out.get("error")})
        print(f"[{'PASS' if ok else 'FAIL'}] {case['question']}")

    print(f"\nExecution accuracy: {passed}/{len(golden)} = {100 * passed / len(golden):.0f}%")
    (ROOT / "eval" / "results.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
