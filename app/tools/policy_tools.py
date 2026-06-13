"""Policy Q&A tool (RAG).

Grounds answers about warranty, shipping, returns and FAQs in the actual policy
documents instead of letting the model improvise terms and timeframes.
"""
from __future__ import annotations

from app.rag import search_policies as _search
from app.tools.base import ToolResponse


def search_policies(query: str) -> ToolResponse:
    """Retrieve relevant policy passages to answer a customer's question."""
    passages = _search(query, k=3)
    if not passages:
        return ToolResponse.ok(
            data={"passages": []},
            message="No encontré información de política para esa consulta.",
        )
    return ToolResponse.ok(
        data={"passages": passages},
        message=f"Se encontraron {len(passages)} fragmentos de política relevantes.",
    )
