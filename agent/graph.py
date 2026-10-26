"""LangGraph wiring: schema -> generate -> guard -> HUMAN REVIEW -> execute (retry) -> summarize.

    load_schema -> generate_sql -> guard_sql --ok--> human_review --approve/edit--> execute_sql --ok--> summarize -> END
                       ^               |                  |                            |
                       +----retry------+                reject -> END                  +--error (retry)--> generate_sql
"""
from __future__ import annotations

import uuid
from functools import partial

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

try:
    from langgraph.checkpoint.memory import InMemorySaver
except ImportError:  # older langgraph
    from langgraph.checkpoint.memory import MemorySaver as InMemorySaver

from . import db, nodes
from .nodes import AgentState


def build_graph(llm, db_path=db.DEFAULT_DB, require_approval: bool = True, checkpointer=None):
    def human_review(state: AgentState) -> AgentState:
        if not require_approval:
            return nodes.apply_review(state, {"action": "auto"})
        # Pauses the graph. The UI/CLI resumes it with Command(resume={"action": ..., "sql": ...}).
        decision = interrupt({"question": state["question"], "sql": state["sql"], "attempt": state.get("attempts")})
        return nodes.apply_review(state, decision)

    g = StateGraph(AgentState)
    g.add_node("load_schema", partial(nodes.load_schema, db_path=db_path))
    g.add_node("generate_sql", partial(nodes.generate_sql, llm=llm))
    g.add_node("guard_sql", nodes.guard_sql)
    g.add_node("human_review", human_review)
    g.add_node("execute_sql", partial(nodes.execute_sql, db_path=db_path))
    g.add_node("summarize", partial(nodes.summarize, llm=llm))

    g.add_edge(START, "load_schema")
    g.add_edge("load_schema", "generate_sql")
    g.add_edge("generate_sql", "guard_sql")
    g.add_conditional_edges("guard_sql", nodes.route_after_guard,
                            {"human_review": "human_review", "generate_sql": "generate_sql", "end": END})
    g.add_conditional_edges("human_review", nodes.route_after_review, {"execute_sql": "execute_sql", "end": END})
    g.add_conditional_edges("execute_sql", nodes.route_after_execute,
                            {"summarize": "summarize", "generate_sql": "generate_sql", "end": END})
    g.add_edge("summarize", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


class Session:
    """Small helper that hides thread ids / interrupts from the CLI and UI."""

    def __init__(self, graph):
        self.graph = graph
        self.config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    def pending_review(self) -> dict | None:
        snap = self.graph.get_state(self.config)
        for task in getattr(snap, "tasks", ()) or ():
            if getattr(task, "interrupts", None):
                return task.interrupts[0].value
        return None

    def ask(self, question: str) -> dict:
        self.config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        self.graph.invoke({"question": question, "attempts": 0}, self.config)
        return self.status()

    def review(self, action: str, sql: str | None = None) -> dict:
        self.graph.invoke(Command(resume={"action": action, "sql": sql}), self.config)
        return self.status()

    def status(self) -> dict:
        review = self.pending_review()
        values = dict(self.graph.get_state(self.config).values)
        return {"needs_review": review is not None, "review": review, **values}
