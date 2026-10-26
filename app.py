"""Streamlit UI:  streamlit run app.py"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from agent.graph import Session, build_graph
from agent.llm import get_llm

st.set_page_config(page_title="Roaming Insights Agent", layout="wide")
st.title("Roaming Insights Agent")
st.caption("Ask about roaming partners, IREG test results and traffic. Every query is reviewed by you before it runs.")

EXAMPLES = [
    "Which 5 partners have the highest LTE attach failure rate?",
    "What are the most common failure causes for VoLTE tests?",
    "Monthly outbound data traffic in GB for African partners",
    "Which partners in Testing status have failed IR.38 tests in the last 60 days?",
]


@st.cache_resource
def get_graph(model: str | None):
    return build_graph(get_llm(model or None))


with st.sidebar:
    model = st.text_input("Model", placeholder="openai:gpt-4o-mini")
    st.markdown("**Try:**")
    for ex in EXAMPLES:
        if st.button(ex, use_container_width=True):
            st.session_state.question = ex

if "session" not in st.session_state:
    st.session_state.session = Session(get_graph(model))

question = st.text_input("Question", key="question")
if st.button("Generate SQL", type="primary", disabled=not question):
    with st.spinner("Writing SQL..."):
        st.session_state.result = st.session_state.session.ask(question)

result = st.session_state.get("result")
if result and result.get("needs_review"):
    st.subheader("Review the query")
    sql = st.text_area("SQL (edit if needed)", result["review"]["sql"], height=180)
    c1, c2, _ = st.columns([1, 1, 4])
    if c1.button("Approve & run", type="primary"):
        action = "edit" if sql.strip() != result["review"]["sql"].strip() else "approve"
        with st.spinner("Running..."):
            st.session_state.result = st.session_state.session.review(action, sql)
        st.rerun()
    if c2.button("Reject"):
        st.session_state.result = st.session_state.session.review("reject")
        st.rerun()
elif result:
    if result.get("answer"):
        st.success(result["answer"])
    if result.get("rows"):
        df = pd.DataFrame(result["rows"], columns=result["columns"])
        chart = result.get("chart")
        if chart:
            fig = (px.line if chart["type"] == "line" else px.bar)(df, x=chart["x"], y=chart["y"])
            st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df, use_container_width=True)
        with st.expander("SQL that ran"):
            st.code(result.get("sql", ""), language="sql")
