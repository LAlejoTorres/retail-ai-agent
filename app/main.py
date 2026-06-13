"""FastAPI entrypoint.

On startup it ensures the SQLite store is seeded and the policy index is built,
so a fresh clone runs with a single command.

Run:  uvicorn app.main:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.data.seed import seed
from app.rag import build_index


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed()           # idempotent: (re)creates and seeds SQLite
    build_index()    # idempotent: builds the Chroma policy index if empty
    yield


app = FastAPI(
    title="Retail AI Agent",
    description="Conversational agent for electronics retail (sales, orders, warranty).",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)
