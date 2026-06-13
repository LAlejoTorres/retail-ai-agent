"""Centralized, typed configuration loaded from environment / .env.

Everything that varies between environments (model, provider endpoint, storage
paths) lives here so the rest of the codebase never reads os.environ directly.
Swapping LLM provider = changing LLM_BASE_URL / LLM_API_KEY / LLM_MODEL only.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM (OpenAI-compatible chat endpoint)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen3:14b"
    llm_disable_thinking: bool = True
    llm_temperature: float = 0.3
    llm_max_tokens: int = 500          # cap reply length for latency
    llm_keep_alive: str = "30m"        # keep model resident on Ollama (avoid reloads)

    # Embeddings (local Ollama)
    embed_model: str = "nomic-embed-text"
    embed_base_url: str = "http://localhost:11434"

    # Storage
    sqlite_path: Path = Field(default=PROJECT_ROOT / "app" / "data" / "retail.db")
    chroma_path: Path = Field(default=PROJECT_ROOT / "app" / "data" / "chroma")

    # App
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    @property
    def products_path(self) -> Path:
        return PROJECT_ROOT / "app" / "data" / "products.json"

    @property
    def policies_dir(self) -> Path:
        return PROJECT_ROOT / "app" / "data" / "policies"


@lru_cache
def get_settings() -> Settings:
    return Settings()
