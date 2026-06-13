.PHONY: setup models seed index api ui test eval all-checks

# One-time setup
setup:
	uv pip install -e ".[dev]"

# Pull the local models (requires Ollama running: `ollama serve`)
models:
	ollama pull qwen3:14b
	ollama pull nomic-embed-text

# (Re)build data stores
seed:
	python -m app.data.seed

index:
	python -m app.rag

# Run the backend API (http://localhost:8000, docs at /docs)
api:
	uvicorn app.main:app --reload

# Run the Streamlit demo UI (expects the API to be running)
ui:
	streamlit run ui/streamlit_app.py

# Fast, deterministic unit tests (no LLM)
test:
	pytest tests/ -q

# Behavioral eval suite against the live agent (needs Ollama + models)
eval:
	python -m evals.run

all-checks: test eval
