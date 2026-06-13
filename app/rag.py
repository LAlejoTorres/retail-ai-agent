"""RAG over unstructured policy documents (warranty, shipping, returns, FAQ).

This is the *correct* place for retrieval: free-text policy knowledge the agent
must ground its answers in. The structured catalog is deliberately NOT here — it
is filtered deterministically in domain/recommender.py.

Indexing is idempotent: documents are chunked by markdown section, embedded with
a local Ollama model, and stored in a persistent Chroma collection.
"""
from __future__ import annotations

import re

import chromadb
from langchain_ollama import OllamaEmbeddings

from app.config import get_settings

_COLLECTION = "policies"


def _embeddings() -> OllamaEmbeddings:
    s = get_settings()
    return OllamaEmbeddings(model=s.embed_model, base_url=s.embed_base_url)


def _chunk_markdown(text: str) -> list[tuple[str, str]]:
    """Split a policy doc into (section_title, body) chunks by '## ' headers."""
    parts = re.split(r"\n(?=## )", text)
    chunks: list[tuple[str, str]] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        first_line = part.splitlines()[0]
        title = first_line.lstrip("# ").strip()
        chunks.append((title, part))
    return chunks


def _client() -> chromadb.ClientAPI:
    s = get_settings()
    s.chroma_path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(s.chroma_path))


def build_index(force: bool = False) -> int:
    """(Re)build the policy index. Returns the number of chunks indexed."""
    client = _client()
    if force:
        try:
            client.delete_collection(_COLLECTION)
        except Exception:
            pass
    collection = client.get_or_create_collection(_COLLECTION)
    if collection.count() > 0 and not force:
        return collection.count()

    settings = get_settings()
    embedder = _embeddings()
    ids, docs, metadatas = [], [], []
    for path in sorted(settings.policies_dir.glob("*.md")):
        for i, (title, body) in enumerate(_chunk_markdown(path.read_text("utf-8"))):
            ids.append(f"{path.stem}-{i}")
            docs.append(body)
            metadatas.append({"source": path.name, "section": title})

    embeddings = embedder.embed_documents(docs)
    collection.add(ids=ids, documents=docs, embeddings=embeddings, metadatas=metadatas)
    return len(ids)


def search_policies(query: str, k: int = 3) -> list[dict]:
    """Return top-k policy passages relevant to the query, with sources."""
    collection = _client().get_or_create_collection(_COLLECTION)
    if collection.count() == 0:
        build_index()
        collection = _client().get_or_create_collection(_COLLECTION)

    query_emb = _embeddings().embed_query(query)
    res = collection.query(query_embeddings=[query_emb], n_results=k)
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    return [
        {"text": d, "source": m.get("source"), "section": m.get("section")}
        for d, m in zip(docs, metas)
    ]


if __name__ == "__main__":
    n = build_index(force=True)
    print(f"Indexed {n} policy chunks into Chroma.")
