"""Model factory. Pick any provider LangChain supports via the LLM_MODEL env var, e.g.

    LLM_MODEL=anthropic:claude-sonnet-4-5   (needs ANTHROPIC_API_KEY)
    LLM_MODEL=openai:gpt-4o-mini            (needs OPENAI_API_KEY)
    LLM_MODEL=ollama:llama3.1               (local, needs langchain-ollama)
"""
from __future__ import annotations

import os

DEFAULT_MODEL = "openai:gpt-4o-mini"


def get_llm(model: str | None = None, temperature: float = 0.0):
    from langchain.chat_models import init_chat_model

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    return init_chat_model(model or os.getenv("LLM_MODEL", DEFAULT_MODEL), temperature=temperature)
