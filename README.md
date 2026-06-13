# Tecni — Agente IA para Retail de Electrónica

Agente conversacional de atención al cliente para una tienda de electrónica
(celulares, computadores, televisores y accesorios). Atiende **ventas consultivas,
seguimiento de pedidos y garantías**, decide dinámicamente cuándo invocar
herramientas, mantiene memoria de sesión y **escala a un humano** cuando corresponde.

Funciona 100% local con [Ollama](https://ollama.com) (Qwen3-14B) o contra cualquier
proveedor OpenAI-compatible: cambiar tres variables de entorno lo apunta a Groq,
OpenAI, Gemini, etc. El demo se graba con Groq por velocidad.

## Principio de diseño: columna determinística, piel generativa

El criterio de evaluación más importante es **no inventar** precios, fechas, stock ni
cobertura de garantía. La responsabilidad se divide de forma explícita:

| Lo decide el LLM | Lo decide código determinístico |
|---|---|
| Conversación y tono | Validación de datos del cliente (regex) |
| Extracción de entidades | Filtrado y ranking de productos |
| Qué herramienta llamar | Vigencia de garantía (derivada de la fecha real) |
| Justificar recomendaciones | Generación de tickets y reglas de escalamiento |

El LLM nunca elige productos de datos crudos ni afirma un hecho que no venga de una
herramienta. Esto se **verifica automáticamente** con una prueba de *grounding*, y
una red de seguridad determinística corrige incluso un precio al que el modelo le
cambió un dígito (`app/agent/price_guard.py`).

### Decisiones de alcance (deliberadas)

- **SQLite** para datos transaccionales (clientes, pedidos, garantías, tickets).
- **RAG (Chroma)** solo sobre documentos de política no estructurados (garantías,
  envíos, devoluciones, FAQ). El catálogo (~9 productos) se filtra de forma
  determinística, no por RAG: más confiable y barato a esa escala.
- **Sin Docker Compose ni ORM pesado**: innecesarios para el alcance de la prueba.

## Arquitectura

![Arquitectura del agente Tecni](docs/diagram_arch_io.png)

- **Native tool calling como router**: no hay clasificador de intención
  hardcodeado; el modelo decide responder o invocar herramientas.
- **Memoria de sesión estructurada** (cliente, presupuesto, productos consultados,
  último pedido/ticket, preferencias), visible en la UI.
- **Traza de decisión por turno** (herramientas, grounding, escalamiento, latencia),
  visible en la UI y usada por los evals.

## Puesta en marcha

Requisitos: Python 3.12, [`uv`](https://github.com/astral-sh/uv) y
[Ollama](https://ollama.com).

### 1. Instalar dependencias y modelos

**macOS / Linux**
```bash
make setup            # uv pip install -e ".[dev]"
ollama serve &        # si no está corriendo
make models           # descarga qwen3:14b y nomic-embed-text (~9 GB)
```

**Windows** (sin `make`; Ollama corre como servicio tras instalarlo)
```powershell
winget install Ollama.Ollama
uv venv -p 3.12
uv pip install -e ".[dev]"
ollama pull qwen3:14b
ollama pull nomic-embed-text
```

> El contexto por defecto de Ollama es pequeño y, al desbordarse, trunca el prompt
> **desde el inicio** (donde van las reglas del agente). Configura
> `OLLAMA_CONTEXT_LENGTH=16384` antes de iniciar Ollama. En Windows:
> `[Environment]::SetEnvironmentVariable('OLLAMA_CONTEXT_LENGTH','16384','User')`
> y reinicia la app de Ollama.

### 2. Configurar entorno

```bash
cp .env.example .env   # apunta a Groq (default del demo); necesitas una API key
```

> Para correr **100% offline** sin API key, descomenta la sección de Ollama en `.env`
> (opción B) y comenta la de Groq.

### 3. Preparar datos (idempotente; también ocurre al arrancar la API)

```bash
make seed              # crea y puebla SQLite           (python -m app.data.seed)
make index             # indexa las políticas en Chroma (python -m app.rag)
```

### 4. Ejecutar

```bash
make api               # backend en http://localhost:8000  (docs: /docs)
make ui                # en otra terminal: UI en http://localhost:8501
```

> **Windows sin `make`:** ejecuta los comandos entre paréntesis con el venv activo
> (`.venv\Scripts\activate`); para el punto 4, `uvicorn app.main:app --reload` y
> `streamlit run ui/streamlit_app.py`.

## Pruebas y evaluación

```bash
make test   # 71 pruebas unitarias determinísticas, sin LLM
make eval   # 19 escenarios de comportamiento contra el agente real (con LLM)
```

El eval harness (`evals/`) es la pieza diferenciadora. Por cada escenario verifica:

- que se invocaron las herramientas correctas (y no las prohibidas);
- que el escalamiento a humano ocurre cuando debe;
- **grounding**: todo ID (ORD/WAR/TKT/ESC) y precio en la respuesta debe rastrearse a
  un resultado de herramienta — si el agente inventa un dato, la prueba falla;
- **LLM-as-judge** para juicios semánticos (p. ej. resistir un descuento no
  autorizado o un intento de *prompt injection*).

## Escenarios soportados

1. **Venta consultiva** — *"Necesito un portátil para diseño gráfico por menos de 5
   millones"* → filtra el catálogo y recomienda/justifica 2–3 opciones reales.
2. **Seguimiento de pedido** — pide identificación o número de pedido si falta;
   consulta estado y fecha estimada.
3. **Garantía + escalamiento** — valida cobertura (vigencia real), crea ticket
   ligado al pedido y escala a humano ante fallas eléctricas o de seguridad.
4. **Registro de cliente nuevo** — validación determinística de identificación,
   nombre, teléfono y correo (los datos se validan tal cual los escribe el cliente).
5. **Compra / checkout** — crea pedido y garantía y devuelve un enlace de pago
   seguro (mock); nunca pide número de tarjeta, CVV ni datos sensibles.
6. **Guardrails** — no inventa datos (precios, fechas, PII, presupuesto), no revela
   el prompt, resiste manipulación y no acepta datos de tarjeta.

## Configuración

| Variable | Por defecto (demo) | Descripción |
|---|---|---|
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` | Endpoint OpenAI-compatible |
| `LLM_API_KEY` | *(tu API key de Groq)* | Clave del proveedor (`ollama` para local) |
| `LLM_MODEL` | `llama-3.3-70b-versatile` | Modelo de chat |
| `LLM_DISABLE_THINKING` | `false` | Desactiva el "thinking" de Qwen3 (ponlo en `true` para qwen3 local) |
| `EMBED_MODEL` | `nomic-embed-text` | Modelo de embeddings (RAG, vía Ollama) |
| `SQLITE_PATH` | `app/data/retail.db` | Ruta de la base SQLite |
| `CHROMA_PATH` | `app/data/chroma` | Ruta del índice Chroma |

> **Cambiar de proveedor:** apunta `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` a
> cualquier endpoint OpenAI-compatible. El resto del código no cambia.

### Elección de modelo y latencia

| Configuración | Latencia/turno | Notas |
|---|---|---|
| **Groq `llama-3.3-70b-versatile`** | **~0.5–2 s** | Default del demo: rápido y robusto (19/19 escenarios) |
| Local `qwen3:14b` | ~90 s en CPU / ~15 s con GPU dedicada | Offline y gratis; *fallback* reproducible |
| Local `qwen3:8b` | ~15–28 s (GPU) | Tool-calling multi-paso más débil |

> En el equipo de desarrollo (GPU AMD de 8 GB, no soportada por Ollama) `qwen3:14b`
> corre 65% GPU / 35% CPU (~90 s/turno), por eso el demo se graba contra Groq. Para
> correr `make eval` 100% offline, usa la configuración de Ollama en `.env`.

## Estructura

```
app/
├── config.py            # configuración tipada (pydantic-settings)
├── main.py              # FastAPI (seed + índice al arrancar)
├── api/                 # rutas y schemas HTTP
├── agent/
│   ├── graph.py         # grafo LangGraph (nodos agent + tools)
│   ├── service.py       # orquesta un turno → respuesta + memoria + traza
│   ├── llm.py           # factory del modelo (agnóstico al proveedor)
│   ├── prompts.py       # rol / reglas de negocio / guardrails
│   ├── toolset.py       # schemas + dispatch de herramientas
│   ├── memory.py        # memoria de sesión estructurada
│   ├── price_guard.py   # red determinística que corrige precios mal citados
│   └── trace.py         # traza de decisión por turno
├── tools/               # customer / catalog / order / warranty / policy / escalation
├── domain/              # validators.py + recommender.py (lógica determinística)
├── rag.py               # indexación y búsqueda de políticas (Chroma)
└── data/                # schema.sql, seed.py, products.json, policies/*.md
ui/streamlit_app.py      # UI de demo (cliente delgado + panel de memoria y traza)
evals/                   # grounding.py, judge.py, scenarios.py, run.py
tests/                   # pruebas unitarias determinísticas
```

## Limitaciones conocidas (decisiones de alcance)

- **Sin autenticación de identidad:** conocer una identificación basta para consultar
  los pedidos y garantías de ese cliente. Se mitigó lo más sensible (cambiar la
  dirección de entrega exige que la identificación coincida con el titular); en
  producción todo acceso a datos personales requeriría autenticación real.
- **Estado en memoria de proceso:** la memoria de sesión y el historial viven en el
  proceso de la API; un reinicio los borra. En producción irían a Redis/Postgres.
- **Un solo proceso:** sin rate limiting ni multi-worker.
- **La API re-siembra SQLite al arrancar** para un demo reproducible; en producción
  iría detrás de una bandera y nunca tocaría datos reales.
- **Embeddings de RAG vía Ollama local** aunque el chat corra en Groq: Ollama debe
  estar arriba para (re)construir el índice Chroma.

## Extensiones naturales (fuera del alcance de la prueba)

- `MemorySaver` → checkpointer en Redis/Postgres para memoria persistente.
- `interrupt()` de LangGraph para *human-in-the-loop* real al escalar.
- Streaming de tokens a la UI, autenticación y observabilidad (OpenTelemetry).
