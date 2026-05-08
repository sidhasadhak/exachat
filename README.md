# ⚡ exachat

**Ask your database anything — in plain English. Get SQL, data, and interactive charts.**

Local LLMs only. No data leaves your machine. Works with DuckDB, Exasol, PostgreSQL, MySQL, SQLite, and anything SQLAlchemy supports.

![Ask tab — query result with interactive bar chart](docs/images/screenshot-ask.png)

---

## Features

- **Natural language → SQL** — powered by any local LLM (Ollama, MLX, LM Studio, vLLM, etc.)
- **4 tabs**: Ask (chat), Build (visual query builder), Metrics (saved KPIs), Schema (ER diagram)
- **Interactive charts** — Plotly bar, line, area, scatter, pie with dual-axis support and live controls
- **Visual Query Builder** — table / dimension / measure selector with filters, sort, and limit — no SQL required
- **Schema Relationship Map** — auto-generated Mermaid ER diagram with detected join paths
- **Metrics Catalog** — define, save, and reuse KPI queries with one click
- **Semantic embeddings** — optional in-process embeddings (`pip install exachat[embeddings]`) improve SQL pattern retrieval and schema table matching; understands business vocabulary ("burn rate" → expense tables, "churn" → cancellation tables)
- **Smart schema retrieval** — for databases with 15+ tables, only the relevant subset is sent to the LLM instead of the full schema; join-connected tables are always included
- **Knowledge Base** — ChromaDB-backed store for Q→SQL patterns; injects similar patterns as few-shot examples into the prompt
- **Join inference** — detects join paths by exact and fuzzy column-name matching; explicitly warns the LLM about table pairs that cannot be joined
- **Access Control** — restrict queries to specific schemas and/or tables; SQL safety validator (allowlist SELECT/WITH only)
- **DuckDB dialect hints** — built-in prompt guidance for `QUALIFY`, `GROUP BY ALL`, `TRY_CAST`, date functions, and more
- **Pre-fill with `.env`** — set default paths, model, and URL so the UI is ready on launch

---

## Install

```bash
pip install exachat                  # core — DuckDB, PostgreSQL, SQLite, MySQL
pip install exachat[embeddings]      # + semantic embeddings (recommended)
pip install exachat[exasol]          # + Exasol support
pip install exachat[mlx]             # + Apple Silicon MLX LLM backend
pip install exachat[all]             # everything
```

**Requirements:** Python ≥ 3.9, and a local LLM server (see [LLM Setup](#llm-setup) below).

### What each extra installs

| Extra | Package | What it does |
|-------|---------|--------------|
| `embeddings` | `fastembed` | In-process semantic embeddings via ONNX. Model (~130 MB) downloaded once on first use. No server needed. |
| `exasol` | `pyexasol`, `sqlalchemy-exasol` | Exasol database connectivity |
| `mlx` | `mlx-lm` | Apple Silicon LLM inference (M-series only) |
| `postgres` | `psycopg2-binary` | PostgreSQL driver |
| `mysql` | `pymysql` | MySQL driver |

---

## Quick Start

### 1. Get a local LLM running

```bash
# Install Ollama (macOS / Linux)
curl -fsSL https://ollama.com/install.sh | sh

# Pull a model — qwen3:8b is the recommended starting point
ollama pull qwen3:8b              # recommended — best quality/speed on modern hardware
ollama pull qwen2.5-coder:7b      # good alternative for pure SQL tasks
ollama pull qwen2.5-coder:14b     # better quality, needs more RAM
```

**Apple Silicon (M-series)?** Use the MLX backend for better performance — see [MLX Setup](#mlx-apple-silicon).

Using **LM Studio** or **vLLM**? Choose **"OpenAI-compatible API"** in the sidebar's LLM Backend expander.

### 2. (Optional but recommended) Enable semantic embeddings

```bash
pip install exachat[embeddings]
```

The `nomic-ai/nomic-embed-text-v1.5` model (~130 MB) is downloaded automatically on first connect. After installing, select **FastEmbed (in-process)** in the sidebar's Embeddings expander before connecting.

### 3. Launch the UI

```bash
exachat
```

Opens at `http://localhost:8501`.

### 4. Connect

The sidebar keeps the most important controls above the fold:

1. **Database** — pick connection type (DuckDB / Exasol / PostgreSQL / SQLAlchemy URL) and enter credentials or a file path
2. Click **🔍 Load schemas & tables** to preview available schemas (optional but recommended)
3. **Access Control** — select the schema and optionally restrict to specific tables
4. Click **⚡ Connect**

Advanced settings — LLM backend, Embeddings, Knowledge Base, Metrics directory, and Options — are in collapsed expanders below the buttons.

![Compact sidebar and auto-generated starter questions](docs/images/screenshot-connected.png)

After connecting, exachat generates 5 starter questions based on your actual schema and data profile.

### 5. Ask questions

Type in plain English — exachat generates SQL, runs it read-only, and shows a plain-English summary, an interactive chart, and the raw data table.

Use the **chart controls** row below each answer to switch chart type, change the x-axis, or select which measures to plot — without re-running the query.

### 6. Pre-fill with a `.env` file

Create `.env` in your working directory (gitignored):

```bash
EXACHAT_DUCKDB_PATH=/path/to/your/database.duckdb
EXACHAT_OLLAMA_URL=http://localhost:11434
EXACHAT_OLLAMA_MODEL=qwen3:8b
```

---

## The Four Tabs

### 💬 Ask — Natural Language Chat

Type a question, get SQL + a plain-English summary + an interactive Plotly chart + the raw data table.

- Click **👍** to save the question→SQL pair to the Knowledge Base so future similar questions benefit from it
- Follow-up questions work naturally — "now filter by last 90 days", "also show average order value"
- Every answer shows a **Generated SQL** expander, timing, and suggested follow-up questions

### 📊 Build — Visual Query Builder

Pick a table, add dimensions (GROUP BY columns) and measures (aggregated columns with SUM / AVG / COUNT / MIN / MAX), set filters, sort order, and row limit — then click **▶ Run**.

The builder generates clean, schema-qualified SQL and renders the same interactive chart + table as the Ask tab. Dimensions can be reordered with ↑↓ buttons. Great for ad-hoc exploration without writing SQL.

![Visual Query Builder — field configuration](docs/images/screenshot-build-config.png)

![Visual Query Builder — results with chart and data table](docs/images/screenshot-build-result.png)

### 📐 Metrics — Saved KPIs

Define a metric once (name + SQL or question), save it to the Metrics Catalog, and re-run it in any future session with one click. Metrics persist to disk as JSON files in the configured directory.

### 🗺️ Schema — ER Diagram

Auto-generated entity-relationship diagram using Mermaid.js. Tables show all column names and their SQL data types. Solid lines indicate exact column-name join paths; dashed lines indicate fuzzy root matches (e.g. `order_id` ↔ `order_id_pseudonyms`). Tables with no detected join path are shown in isolation.

![Schema Relationship Map — auto-generated Mermaid ER diagram](docs/images/screenshot-schema.png)

---

## Python API

```python
from exachat import ExasolChat

# DuckDB (local file)
chat = ExasolChat("duckdb:///path/to/analytics.duckdb")
chat = ExasolChat("./my_data.duckdb")  # bare path works too

# Exasol
chat = ExasolChat("exa+pyexasol://user:pass@host:8563/MY_SCHEMA")

# PostgreSQL
chat = ExasolChat("postgresql://user:pass@localhost:5432/mydb")

# SQLite / MySQL / anything SQLAlchemy supports
chat = ExasolChat("sqlite:///local.db")
chat = ExasolChat("mysql+pymysql://user:pass@host:3306/db")
```

```python
result = chat.ask("Top 10 customers by total spend")

print(result.summary)      # "The top customer is Acme Corp with $2.3M..."
print(result.sql)          # SELECT customer_name, SUM(total) AS total_spend ...
print(result.data)         # pandas DataFrame
print(result.chart_config) # {"chart_type": "bar", "x": "customer_name", ...}
```

### Using a different LLM backend

```python
from exachat.llm import OllamaBackend, OpenAICompatibleBackend, MLXBackend

# Ollama
llm = OllamaBackend(model="qwen3:8b")

# OpenAI-compatible (LM Studio, vLLM, etc.)
llm = OpenAICompatibleBackend(base_url="http://localhost:1234/v1", model="qwen2.5-coder-14b")

# Apple Silicon MLX
llm = MLXBackend(base_url="http://localhost:8080/v1", model="mlx-community/Qwen3-8B-4bit")

chat = ExasolChat("./data.duckdb", llm=llm)
```

### Enabling semantic embeddings

```python
# In-process via fastembed (recommended — pip install exachat[embeddings])
chat = ExasolChat("./data.duckdb", embedding_backend="fastembed")

# Via Ollama embedding server (ollama pull nomic-embed-text)
chat = ExasolChat("./data.duckdb",
    embedding_backend="ollama",
    embedding_url="http://localhost:11434",
    embedding_model="nomic-embed-text",
)

# Via any OpenAI-compatible embedding API
chat = ExasolChat("./data.duckdb",
    embedding_backend="openai",
    embedding_url="http://localhost:1234/v1",
    embedding_model="nomic-embed-text",
)
```

### Access control

```python
chat = ExasolChat(
    "exa+pyexasol://readonly_user:pass@host:8563/PROD",
    allowed_schemas=["SALES", "ANALYTICS"],
    allowed_tables=["CUSTOMERS", "ORDERS", "PRODUCTS"],
    extra_context="""
        - revenue columns are in EUR
        - fiscal year starts April 1
        - ORDERS.status: 'active', 'cancelled', 'refunded'
    """,
)
```

### Scripting / batch reports

```python
from exachat import ExasolChat

with ExasolChat("duckdb:///sales.duckdb") as chat:
    monthly = chat.ask("Monthly revenue for the last 12 months")
    top_products = chat.ask("Top 5 products by units sold this quarter")

    monthly.data.to_csv("monthly_revenue.csv", index=False)
    top_products.data.to_csv("top_products.csv", index=False)
```

---

## LLM Setup

### Ollama (recommended for most setups)

| Model | Command | Quality | Notes |
|-------|---------|---------|-------|
| `qwen3:8b` | `ollama pull qwen3:8b` | ⭐⭐⭐⭐⭐ | **Recommended default** |
| `qwen2.5-coder:7b` | `ollama pull qwen2.5-coder:7b` | ⭐⭐⭐⭐ | Good for SQL-heavy workloads |
| `qwen2.5-coder:14b` | `ollama pull qwen2.5-coder:14b` | ⭐⭐⭐⭐⭐ | Better quality, needs more RAM |
| `deepseek-coder-v2:16b` | `ollama pull deepseek-coder-v2:16b` | ⭐⭐⭐⭐⭐ | Excellent for complex joins |

### MLX (Apple Silicon)

MLX runs models natively on Apple M-series chips via Metal — typically 20–30% faster than Ollama on the same hardware.

```bash
# Install (inside your project venv)
pip install exachat[mlx]

# Start the MLX server (keep running while exachat is open)
python3 -m mlx_lm.server --model mlx-community/Qwen3-8B-4bit --port 8080
```

In the sidebar: **LLM Backend → MLX (Apple Silicon)**.  
Default server URL: `http://localhost:8080/v1`, model: `mlx-community/Qwen3-8B-4bit`.

Other recommended MLX models:

| Model | Size | Notes |
|-------|------|-------|
| `mlx-community/Qwen3-8B-4bit` | ~5 GB | **Recommended** |
| `mlx-community/Qwen3-8B-8bit` | ~9 GB | Higher quality |
| `mlx-community/Qwen2.5-Coder-7B-Instruct-4bit` | ~4 GB | SQL-focused |

### OpenAI-compatible APIs

Any server implementing `/v1/chat/completions` works — LM Studio, vLLM, text-generation-webui, LocalAI. Select **"OpenAI-compatible API"** in the LLM Backend expander.

---

## Embeddings

Embeddings power two things in exachat:

1. **SQL pattern retrieval** — finds relevant SQL technique patterns (window functions, YoY comparisons, etc.) to inject as examples into the prompt
2. **Schema table retrieval** — for databases with 15+ tables, retrieves only the relevant tables per query instead of dumping the full schema into the prompt

### Embedding backends

| Backend | Setup | Quality | Notes |
|---------|-------|---------|-------|
| Bag of words (default) | None — works offline | Keyword matching only | Good for small schemas and standard SQL vocabulary |
| **FastEmbed** *(recommended)* | `pip install exachat[embeddings]` | Semantic | In-process ONNX, no server. Model auto-downloaded (~130 MB). |
| Ollama | `ollama pull nomic-embed-text` | Semantic | Requires Ollama running separately |
| OpenAI-compatible | Any `/v1/embeddings` server | Semantic | LM Studio, etc. |

### FastEmbed setup

```bash
pip install exachat[embeddings]
```

That's it. On first connect, the `nomic-ai/nomic-embed-text-v1.5` model is downloaded (~130 MB) and cached at `~/.cache/fastembed/`. All subsequent connects are instant.

In the sidebar: **Embeddings → FastEmbed (in-process)**.

### Why semantic embeddings matter

With bag-of-words, retrieval is purely keyword-based. With semantic embeddings:

- `"burn rate"` correctly retrieves your `MONTHLY_EXPENSES` table
- `"churn"` matches `CANCELLATIONS` even with no shared words
- `"headcount trend"` finds the `EMPLOYEES` and `DEPARTMENTS` tables
- SQL patterns like `"year-over-year comparison"` match a question phrased as `"how has revenue changed vs last year?"`

Semantic embeddings are most valuable for databases with **business-domain column/table names** and schemas with **15+ tables** where full schema prompt-stuffing is too noisy.

### Schema retrieval behaviour

| Schema size | Behaviour |
|-------------|-----------|
| ≤ 15 tables | Full schema always included — maximum accuracy |
| > 15 tables | Top 10 most relevant tables retrieved per query; join-connected tables always included to preserve JOIN paths |

---

## Knowledge Base

Successful question→SQL pairs are stored locally in ChromaDB and retrieved as few-shot examples for similar future questions. With semantic embeddings enabled, retrieval is meaning-aware rather than keyword-based.

```python
# Seed with your own patterns:
chat.train(
    "quarterly revenue by region",
    """SELECT region,
        date_trunc('quarter', order_date) AS quarter,
        SUM(amount) AS revenue
    FROM sales.orders
    GROUP BY ALL
    ORDER BY quarter, revenue DESC"""
)

# Inspect stored pairs:
print(chat.kb.count)

# Clear memory:
chat.rag.clear()
```

Patterns persist at `~/.exachat/kb/` by default. Point the UI to a custom directory via the **📖 Knowledge Base** expander or `EXACHAT_KB_PATH` in `.env`.

---

## Safety Model

- **Allowlist-only**: Only `SELECT` and `WITH` (CTE) pass. `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `EXEC`, `CALL`, `EXPORT`, `IMPORT`, `COPY`, `ATTACH`, `DETACH`, `INSTALL`, `LOAD` are all blocked before execution.
- **No `exec()` or `eval()`**: LLM output is never executed as Python code.
- **Pattern matching**: Blocks `read_csv` / `read_parquet` / `read_json` (DuckDB file access), `pg_sleep`, `BENCHMARK`, statement stacking (`;`-separated queries), `SET`, `PRAGMA`.
- **Access control enforcement**: The LLM prompt explicitly lists allowed tables; the safety validator cross-checks the generated SQL against the allowlist.
- **Read-only connections**: DuckDB files always opened with `read_only=True`. SQLAlchemy uses `SET TRANSACTION READ ONLY` where supported.
- **Suspicious query warnings**: `UNION SELECT`, tautology injections, and system table access trigger a visible warning badge without blocking execution.

> Use a **read-only database user** in production. The safety layer is defence-in-depth, not a substitute for proper DB permissions.

---

## Architecture

```
Question
  │
  ├─► SQL pattern retrieval  (ChromaDB KB — semantic or bag-of-words)
  ├─► Schema table retrieval (ChromaDB SchemaIndex — only for schemas > 15 tables)
  │
  ▼
LLM Prompt
  ├── Schema context (relevant tables only for large schemas; full schema for small ones)
  ├── Join map (detected paths + "no-join" table pairs)
  ├── Dialect hints (DuckDB / PostgreSQL / Exasol)
  ├── Few-shot SQL pattern examples (from KB retrieval)
  └── Conversation history (follow-up support)
  │
  ▼
SQL Generation → Safety Validation → Query Execution (read-only)
  │
  ▼
Summary · Chart · DataFrame · Follow-up Suggestions · KB feedback loop
```

### Module map

| Module | Purpose |
|--------|---------|
| `app.py` | Streamlit UI — 4 tabs (Ask / Build / Metrics / Schema), compact sidebar, chart controls |
| `app_builder.py` | Visual Query Builder — dimension / measure / filter / sort UI → SQL |
| `core.py` | Engine — orchestrates the full `ask()` pipeline |
| `llm.py` | LLM backends — Ollama, MLX, OpenAI-compatible; dialect hints; prompt construction |
| `schema.py` | Schema introspection + join inference (exact + fuzzy column-name matching) |
| `safety.py` | SQL validation — allowlist, DDL/DML blocking, injection pattern detection |
| `connection.py` | Connection management — pyexasol, DuckDB native (read-only), SQLAlchemy |
| `builder.py` | QueryBuilder — programmatic SELECT / GROUP BY / filter / sort → schema-qualified SQL |
| `metrics.py` | Metrics Catalog — save / load / run named KPI queries from JSON |
| `kb.py` | Knowledge Base + Schema Index — ChromaDB store for Q→SQL patterns and per-table schema retrieval; bag-of-words (default), FastEmbed, Ollama, or OpenAI-compatible embeddings |
| `charts.py` | Auto-charting — Plotly bar / line / area / scatter / pie / heatmap |

---

## Configuration Reference

```python
from exachat import ExasolChat
from exachat.llm import OllamaBackend

chat = ExasolChat(
    connection="duckdb:///sales.duckdb",
    llm=OllamaBackend(model="qwen3:8b"),

    # Schema scoping
    schema="main",

    # Access control
    allowed_schemas=["SALES", "ANALYTICS"],
    allowed_tables=["CUSTOMERS", "ORDERS", "PRODUCTS"],

    # Business context injected into every prompt
    extra_context="revenue is in EUR. fiscal year starts April 1.",

    # Query limits
    max_rows=10000,

    # Embeddings — controls both KB pattern retrieval and schema table retrieval
    # "bow" (default) | "fastembed" | "ollama" | "openai"
    embedding_backend="fastembed",
    embedding_url="",                          # not needed for fastembed
    embedding_model="nomic-ai/nomic-embed-text-v1.5",

    # Knowledge Base
    kb_path=None,          # path to extra KB JSON files (built-in patterns always loaded)

    # Charts
    chart_library="auto",  # "plotly", "altair", or "auto"

    # Metrics
    metrics_path=None,     # path to metrics JSON directory (~/.exachat/metrics/ by default)
)
```

---

## Limitations

- **SQL accuracy = LLM quality.** Smaller models produce worse SQL. 7B+ recommended; 14B+ for complex schemas or many tables.
- **Safety layer is regex-based.** It catches known patterns but is not a full SQL parser. Always use a read-only database user.
- **Join inference is heuristic.** Column-name similarity works well for conventional naming; semantic joins (different names, same concept) are not detected automatically, though semantic embeddings reduce this gap for schema retrieval.
- **Charts are LLM-suggested.** Usually correct — use the chart controls in the UI to override type, axes, and measures.
- **Embedding model download required on first use.** FastEmbed downloads ~130 MB on first connect; requires an internet connection once.

---

## License

MIT
