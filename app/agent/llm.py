"""LLM factory: the only provider-aware code. Defaults to a local Ollama server
over its OpenAI-compatible API; switch provider via LLM_BASE_URL/API_KEY/MODEL.
"""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.config import get_settings


def get_chat_model(temperature: float | None = None) -> ChatOpenAI:
    s = get_settings()
    kwargs: dict = dict(
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        model=s.llm_model,
        # Allow callers (e.g. the eval judge) to force determinism with temperature=0.
        temperature=s.llm_temperature if temperature is None else temperature,
        max_tokens=s.llm_max_tokens,   # cap reply length -> fewer tokens, faster
        timeout=s.llm_timeout,
    )
    # Provider-specific knobs to control resource use / suppress Qwen3 "thinking".
    extra: dict = {}
    base = s.llm_base_url
    if "11434" in base or "localhost" in base:
        extra["keep_alive"] = s.llm_keep_alive  # keep Ollama model resident
    if "groq.com" in base and "qwen" in s.llm_model.lower() and s.llm_disable_thinking:
        # Groq/Qwen3 ignores the "/no_think" prompt token; disable reasoning here.
        extra["reasoning_effort"] = "none"
    if extra:
        kwargs["extra_body"] = extra
    return ChatOpenAI(**kwargs)
