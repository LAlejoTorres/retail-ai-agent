"""Typed configuration from environment / .env. The only place that reads it, so
swapping LLM provider means changing LLM_BASE_URL / LLM_API_KEY / LLM_MODEL only.
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
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1024         # room for reasoning + a full reply (see .env)
    llm_keep_alive: str = "30m"        # keep model resident on Ollama (avoid reloads)
    llm_timeout: float = 300.0         # tolerate a slow first/cold turn on CPU spill

    # Embeddings (local Ollama)
    embed_model: str = "nomic-embed-text"
    embed_base_url: str = "http://localhost:11434"

    # Storage
    sqlite_path: Path = Field(default=PROJECT_ROOT / "app" / "data" / "retail.db")
    chroma_path: Path = Field(default=PROJECT_ROOT / "app" / "data" / "chroma")

    # App (loopback por defecto: no exponer el demo a la red local)
    api_host: str = "127.0.0.1"
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
