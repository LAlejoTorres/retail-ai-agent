"""FastAPI entrypoint. On startup it seeds SQLite and builds the policy index."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config import get_settings
from app.data.seed import seed
from app.rag import build_index

logging.basicConfig(
    level=get_settings().log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


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
