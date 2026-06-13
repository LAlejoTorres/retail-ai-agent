"""LLM factory. The only place that knows which provider we talk to.

Default target is a local Ollama server via its OpenAI-compatible API, so the
exact same code runs against OpenAI / Groq / OpenRouter / vLLM / Gemini-compat
by changing LLM_BASE_URL / LLM_API_KEY / LLM_MODEL in the environment.
"""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.config import get_settings


def get_chat_model() -> ChatOpenAI:
    s = get_settings()
    kwargs: dict = dict(
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        model=s.llm_model,
        temperature=s.llm_temperature,
        max_tokens=s.llm_max_tokens,   # cap reply length -> fewer tokens, faster
        timeout=120,
    )
    # Provider-specific extras. Each endpoint has its own knob to suppress Qwen3's
    # "thinking" tokens and to control resource use.
    extra: dict = {}
    base = s.llm_base_url
    if "11434" in base or "localhost" in base:
        # Ollama: keep the model resident to avoid cold reloads (thinking is
        # disabled via the "/no_think" directive in the system prompt).
        extra["keep_alive"] = s.llm_keep_alive
    if "groq.com" in base and "qwen" in s.llm_model.lower() and s.llm_disable_thinking:
        # Groq/Qwen3: disable reasoning here — it ignores the "/no_think" prompt
        # token, and reasoning tokens otherwise dominate latency. (qwen-only knob.)
        extra["reasoning_effort"] = "none"
    if extra:
        kwargs["extra_body"] = extra
    return ChatOpenAI(**kwargs)
