"""Terminal interface with a human approval step.

    python cli.py                         # interactive
    python cli.py "Top 5 partners by LTE attach failure rate"
    python cli.py --auto "..."            # skip approval (demo only)
"""
from __future__ import annotations

import argparse

from agent.graph import Session, build_graph
from agent.llm import get_llm
from agent.nodes import to_markdown


def review_loop(session: Session, result: dict) -> dict:
    while result["needs_review"]:
        print("\nProposed SQL:\n" + "-" * 60 + f"\n{result['review']['sql']}\n" + "-" * 60)
        choice = input("[a]pprove / [e]dit / [r]eject? ").strip().lower()[:1]
        if choice == "e":
            print("Paste the corrected SQL, then an empty line:")
            lines = iter(input, "")
            result = session.review("edit", "\n".join(lines))
        elif choice == "r":
            result = session.review("reject")
        else:
            result = session.review("approve")
    return result


def show(result: dict) -> None:
    if result.get("rows"):
        print("\n" + to_markdown(result["columns"], result["rows"], 20))
        if len(result["rows"]) > 20:
            print(f"... {len(result['rows'])} rows total")
    print(f"\nAnswer: {result.get('answer', '(none)')}\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("question", nargs="?")
    p.add_argument("--auto", action="store_true", help="skip human approval")
    p.add_argument("--model", help="e.g. openai:gpt-4o-mini or anthropic:claude-sonnet-4-5")
    args = p.parse_args()

    session = Session(build_graph(get_llm(args.model), require_approval=not args.auto))
    questions = [args.question] if args.question else iter(lambda: input("Ask (blank to quit): ").strip(), "")
    for q in questions:
        show(review_loop(session, session.ask(q)))


if __name__ == "__main__":
    main()
