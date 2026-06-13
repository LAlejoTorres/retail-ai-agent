# 🤖 Tecni — Agente IA para Retail de Electrónica

Agente conversacional de atención al cliente para una tienda de electrónica
(celulares, computadores, televisores y accesorios). Atiende **ventas
consultivas, seguimiento de pedidos y garantías**, decide dinámicamente cuándo
usar herramientas, mantiene memoria de sesión y **escala a un humano** cuando
corresponde.

Corre **100% local y gratis** con [Ollama](https://ollama.com) + **Qwen3-14B**,
pero es **agnóstico al proveedor**: cambiar tres variables de entorno lo apunta a
OpenAI, Gemini, Groq, etc.

---

## ✨ Idea de diseño: *"columna determinística, piel generativa"*

El criterio de evaluación más importante de un agente de retail es **no inventar**
precios, fechas, stock ni cobertura de garantía. Por eso la responsabilidad está
dividida de forma explícita:

| Lo decide el **LLM** | Lo decide **código determinístico** |
|---|---|
| Conversación y tono | Validación de datos del cliente (regex) |
| Extracción de entidades | Filtrado y ranking de productos |
| Qué herramienta llamar | Vigencia de garantía (se deriva de la fecha real) |
| Justificar recomendaciones | Generación de tickets y reglas de escalamiento |

El LLM **nunca** elige productos de datos crudos ni afirma un hecho que no venga
de una herramienta. Esto se **verifica automáticamente** con una prueba de
*grounding* (ver más abajo).

### Decisiones de alcance (deliberadas)

- **SQLite** para datos transaccionales (clientes, pedidos, garantías, tickets):
  modela un sistema real y permite mostrar SQL.
- **RAG (Chroma)** solo sobre **documentos de política** no estructurados
  (garantías, envíos, devoluciones, FAQ). **No** se usa RAG sobre el catálogo:
  con ~9 productos estructurados, el filtrado determinístico es más confiable y
  barato. *Usar cada tecnología donde aporta, no por moda.*
- **Sin Docker Compose / ORM pesado**: innecesario para el alcance de la prueba.

---

## 🏗️ Arquitectura

```
Usuario ─▶ Streamlit (cliente delgado)
              │  HTTP
              ▼
          FastAPI  ──▶  Agent Service ──▶ LangGraph
                                            ├─ nodo agent  (LLM + tool calling)
                                            └─ nodo tools  (ejecuta + actualiza memoria + traza)
                                                   │
            ┌──────────────────────────────────────┼───────────────────────┐
            ▼                  ▼                     ▼                       ▼
       Tools de pedidos   Tools de garantía     Tools de catálogo     search_policies (RAG)
            │                  │                     │                       │
         SQLite ◀──────────────┴──────────  products.json          Chroma + nomic-embed
```

- **Native tool calling como router**: no hay un clasificador de intención
  hardcodeado; el modelo decide responder o invocar herramientas. La lógica del
  agente es un grafo (LangGraph), no un prompt gigante.
- **Memoria de sesión estructurada** (cliente, presupuesto, productos
  consultados, último pedido/ticket, preferencias) que se muestra en la UI.
- **Traza de decisión por turno** (herramientas, grounding, escalamiento,
  latencia) visible en la UI y usada por los evals.

---

## 🚀 Puesta en marcha

### Requisitos
- Python 3.12, [`uv`](https://github.com/astral-sh/uv), y [Ollama](https://ollama.com).

### 1. Instalar dependencias y modelos
```bash
make setup            # uv pip install -e ".[dev]"
ollama serve &        # si no está corriendo
make models           # descarga qwen3:14b y nomic-embed-text (~9 GB)
```

### 2. Configurar entorno
```bash
cp .env.example .env  # valores por defecto apuntan a Ollama local
```

### 3. Preparar datos (idempotente; también ocurre al arrancar la API)
```bash
make seed             # crea y puebla SQLite
make index            # indexa las políticas en Chroma
```

### 4. Ejecutar
```bash
make api              # backend en http://localhost:8000  (docs: /docs)
make ui               # en otra terminal: UI en http://localhost:8501
```

---

## 🧪 Pruebas y evaluación

```bash
make test   # 20 pruebas unitarias determinísticas (validadores, tools, recomendador) — sin LLM
make eval   # 6 escenarios de comportamiento contra el agente real (con LLM)
```

El **eval harness** (`evals/`) es la pieza diferenciadora. Por cada escenario verifica:
- que se invocaron las herramientas correctas (y no las prohibidas),
- que el escalamiento a humano ocurre cuando debe,
- **grounding**: todo ID (ORD/WAR/TKT) y precio en la respuesta debe rastrearse a
  un resultado de herramienta — si el agente inventa un dato, **la prueba falla**,
- **LLM-as-judge** para juicios semánticos (p. ej. resistir un intento de
  descuento no autorizado / *prompt injection*).

---

## 🎬 Escenarios soportados

1. **Venta consultiva** — *"Necesito un portátil para diseño gráfico por menos de
   5 millones"* → filtra el catálogo, recomienda y justifica 2–3 opciones reales.
2. **Seguimiento de pedido** — pide identificación/número de pedido si falta,
   consulta el estado y la fecha estimada.
3. **Garantía + escalamiento** — valida cobertura (vigencia real), crea ticket y
   **escala a humano** ante fallas eléctricas/seguridad.
4. **Registro de cliente nuevo** — validación determinística de identificación,
   nombre, teléfono y correo.
5. **Guardrails** — no inventa datos, no revela el prompt, resiste manipulación.

---

## ⚙️ Variables de entorno

| Variable | Por defecto | Descripción |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Endpoint OpenAI-compatible |
| `LLM_API_KEY` | `ollama` | Clave (cualquier valor para Ollama) |
| `LLM_MODEL` | `qwen3:14b` | Modelo de chat |
| `LLM_DISABLE_THINKING` | `true` | Desactiva el "thinking" de Qwen3 en tool calls |
| `LLM_TEMPERATURE` | `0.3` | Temperatura |
| `EMBED_MODEL` | `nomic-embed-text` | Modelo de embeddings (RAG) |
| `SQLITE_PATH` | `app/data/retail.db` | Ruta de la base SQLite |
| `CHROMA_PATH` | `app/data/chroma` | Ruta del índice Chroma |

> **Cambiar de proveedor:** apunta `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`
> a cualquier endpoint OpenAI-compatible (OpenAI, Groq, OpenRouter, vLLM,
> Gemini-compat). El resto del código no cambia.

### Elección de modelo y latencia

| Configuración | Latencia/turno | Fiabilidad | Notas |
|---|---|---|---|
| **Local `qwen3:14b`** (default) | ~10–20 s | ✅ 9/9 evals | Offline y gratis; la apuesta segura |
| **Groq `llama-3.3-70b-versatile`** | ~2 s | ✅ pasa escenarios | Rápido para demo; el *free tier* puede throttlear (TPM) y subir picos |
| Local `qwen3:8b` | ~10–15 s | ❌ 4/9 | Falla el tool-calling multi-paso |
| Groq `qwen/qwen3-32b` | <1 s/llamada | ✅ familia qwen | *Free tier* 6k TPM: insuficiente para un agente multi-llamada |

Optimizaciones aplicadas (sin costo de calidad): respuestas concisas + `LLM_MAX_TOKENS`,
`keep_alive` del modelo en Ollama, *flash attention*, y **diseño de herramientas de
una sola llamada** (p. ej. `create_warranty_ticket` valida la cobertura y resuelve el
producto por sí misma) para no depender de que el modelo encadene varias herramientas.

> Para grabar el demo con respuestas rápidas, usa Groq `llama-3.3-70b-versatile`.
> Para correr `make eval` o garantizar reproducibilidad total, usa el modelo local.

---

## 📁 Estructura

```
app/
├── config.py            # configuración tipada (pydantic-settings)
├── main.py              # FastAPI (seed + índice al arrancar)
├── api/                 # rutas y schemas HTTP
├── agent/
│   ├── graph.py         # grafo LangGraph (agent + tools nodes)
│   ├── service.py       # orquesta un turno → respuesta + memoria + traza
│   ├── llm.py           # factory del modelo (agnóstico al proveedor)
│   ├── prompts.py       # rol / reglas de negocio / guardrails (separados)
│   ├── toolset.py       # schemas + dispatch de herramientas
│   ├── memory.py        # memoria de sesión estructurada (store intercambiable)
│   └── trace.py         # traza de decisión por turno
├── tools/               # customer / catalog / order / warranty / policy / escalation
├── domain/              # validators.py + recommender.py (lógica determinística)
├── rag.py               # indexación y búsqueda de políticas (Chroma)
└── data/                # schema.sql, seed.py, products.json, policies/*.md
ui/streamlit_app.py      # UI de demo (cliente delgado + panel de memoria y traza)
evals/                   # grounding.py, judge.py, scenarios.py, run.py
tests/                   # pruebas unitarias determinísticas
```

---

## 🔭 Extensiones naturales (fuera del alcance de la prueba)

- `MemorySaver` → checkpointer en Redis/Postgres para memoria persistente.
- `interrupt()` de LangGraph para *human-in-the-loop* real al escalar.
- Streaming de tokens a la UI; autenticación; métricas/observabilidad (OpenTelemetry).
