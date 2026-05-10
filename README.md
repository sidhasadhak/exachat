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
- **Auto-correct retry loop** — failed queries are automatically diagnosed and fixed by the LLM, up to 3 attempts; the UI shows live attempt progress and a summary of what was corrected
- **Enriched Knowledge Base** — 203 domain SQL patterns across eCommerce, Finance, Marketing, Product, and BI; each pattern includes inflation/deflation causes, causal relationships, graduated SQL assets, and anti-patterns
- **Semantic embeddings** — optional in-process embeddings (`pip install exachat[embeddings]`) improve SQL pattern retrieval and schema table matching; understands business vocabulary ("burn rate" → expense tables, "churn" → cancellation tables)
- **Smart schema retrieval** — for databases with 15+ tables, only the relevant subset is sent to the LLM instead of the full schema; join-connected tables are always included
- **Knowledge Base** — ChromaDB-backed store for SQL patterns; injects similar patterns as few-shot examples into the prompt
- **Join inference** — detects join paths by exact and fuzzy column-name matching; explicitly warns the LLM about table pairs that cannot be joined
- **Access Control** — restrict queries to specific schemas and/or tables; SQL safety validator (allowlist SELECT/WITH only)
- **Dialect hints** — built-in prompt guidance for DuckDB (`QUALIFY`, `GROUP BY ALL`, `TRY_CAST`, date functions), PostgreSQL (timestamp cast safety, interval arithmetic), and Exasol
- **MLX auto-start** — on Apple Silicon, the MLX server starts automatically on first query; model is downloaded once if not already cached
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
| `mlx` | `mlx-lm`, `transformers>=4.47` | Apple Silicon LLM inference (M-series only) |
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

**Apple Silicon (M-series)?** Use the MLX backend — see [MLX Setup](#mlx-apple-silicon). The server and model are managed automatically; no terminal command needed.

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

If the generated SQL fails, exachat automatically retries up to 3 times: the LLM diagnoses the error, rewrites the SQL, re-validates safety, and re-executes — all without any action from you. The UI shows live attempt progress ("⚠️ Attempt 2/3 — refining query…") and a collapsed summary of what was corrected on success.

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

- Follow-up questions work naturally — "now filter by last 90 days", "also show average order value"
- Every answer shows a **Generated SQL** expander, timing, and suggested follow-up questions
- If a query fails and is auto-corrected, a collapsed green expander shows the original SQL, the error, and what was fixed

### 📊 Build — Visual Query Builder

Pick a table, add dimensions (GROUP BY columns) and measures (aggregated columns with SUM / AVG / COUNT / MIN / MAX), set filters, sort order, and row limit — then click **▶ Run**.

The builder generates clean, schema-qualified SQL and renders the same interactive chart + table as the Ask tab. Dimensions can be reordered with ↑↓ buttons. Great for ad-hoc exploration without writing SQL.

![Visual Query Builder — field configuration](docs/images/screenshot-build-config.png)

![Visual Query Builder — results with chart and data table](docs/images/screenshot-build-result.png)

### 📐 Metrics — Saved KPIs

Define a metric once (name + SQL or question), save it to the Metrics Catalog, and re-run it in any future session with one click. Metrics persist to disk as JSON files in the configured directory.

### 🗺️ Schema — ER Diagram

Auto-generated entity-relationship diagram using Mermaid.js. Tables show all column names and their SQL data types. Solid lines indicate exact column-name join paths; dashed lines indicate fuzzy root matches. Tables with no detected join path are shown in isolation.

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

# Auto-correction fields — populated when a query failed and recovered
print(result.auto_corrected)          # True / False
print(result.original_sql)            # the SQL that first failed (if corrected)
print(result.original_error)          # the DB error from the first attempt
print(result.correction_explanation)  # what the LLM says it fixed
```

### Using a different LLM backend

```python
from exachat.llm import OllamaBackend, OpenAICompatibleBackend, MLXBackend

# Ollama
llm = OllamaBackend(model="qwen3:8b")

# OpenAI-compatible (LM Studio, vLLM, etc.)
llm = OpenAICompatibleBackend(base_url="http://localhost:1234/v1", model="qwen2.5-coder-14b")

# Apple Silicon MLX — server starts automatically on first query
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
pip install exachat[mlx]
```

In the sidebar: **LLM Backend → MLX (Apple Silicon)**.

**The server starts automatically.** On first query, exachat spawns the MLX server in the background, waits for the model to load into memory (~30 s the first time), and then runs your query. If the model isn't cached locally, it is downloaded automatically before the server starts. No terminal command needed at any point.

Default server URL: `http://localhost:8080/v1`, model: `mlx-community/Qwen3-8B-4bit`.

| Model | Size | Notes |
|-------|------|-------|
| `mlx-community/Qwen3-8B-4bit` | ~5 GB | **Recommended** |
| `mlx-community/Qwen3-8B-8bit` | ~9 GB | Higher quality |
| `mlx-community/Qwen2.5-Coder-7B-Instruct-4bit` | ~4 GB | SQL-focused |

### OpenAI-compatible APIs

Any server implementing `/v1/chat/completions` works — LM Studio, vLLM, text-generation-webui, LocalAI. Select **"OpenAI-compatible API"** in the LLM Backend expander.

---

## Auto-Correct Query Retry

When a generated SQL query fails at execution, exachat does not surface the raw database error immediately. Instead, it automatically retries up to **3 attempts**:

1. The DB error is passed back to the LLM along with the original question and failed SQL
2. The LLM diagnoses the error and returns a corrected query
3. The corrected SQL is re-validated for safety and re-executed
4. If it succeeds, the result is returned normally with a collapsed notice showing what was fixed

The Streamlit UI shows live status during retries: **"⚠️ Attempt 2/3 — refining query…"**

On success after a retry, a collapsed green expander shows:
- The original (failed) SQL
- The database error it produced
- The corrected SQL that was used
- The LLM's explanation of what was wrong

If all 3 attempts fail, the final error is shown with a collapsible detail panel.

The `QueryResult` object exposes the full correction metadata:
```python
result = chat.ask("...")

if result.auto_corrected:
    print("Original SQL:", result.original_sql)
    print("Error:", result.original_error)
    print("Fix:", result.correction_explanation)
```

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

### Schema retrieval behaviour

| Schema size | Behaviour |
|-------------|-----------|
| ≤ 15 tables | Full schema always included — maximum accuracy |
| > 15 tables | Top 10 most relevant tables retrieved per query; FK-connected tables always included to preserve JOIN paths |

---

## Knowledge Base

exachat ships with **203 enriched SQL patterns** across five business domains. Each pattern includes:

- **Metric nature** — what the metric measures, what it does not, and common misconceptions
- **Graduated SQL assets** — basic, intermediate, and advanced SQL templates
- **Inflation & deflation causes** — common reasons the metric is over- or under-counted, each with a diagnostic SQL snippet
- **Causal relationships** — if/then chains linking symptoms to root causes
- **Anti-patterns** — specific SQL mistakes with explanations of why they break the metric

### Covered domains

| Domain | Patterns | Examples |
|--------|----------|---------|
| eCommerce Orders & Revenue | 10 | GMV, net revenue, AOV, refund rate, discount rate, RPV |
| eCommerce Customer Lifecycle | 10 | CLV, repeat rate, RFM, cohort retention, CAC, TBO |
| eCommerce Funnel & Conversion | 9 | Conversion rate, cart abandonment, checkout funnel, PDP-to-cart |
| eCommerce Inventory & Merchandising | 10 | Inventory turnover, DIO, stockout, sell-through, dead stock |
| Finance Revenue | 9 | Recognized revenue, deferred revenue, bookings vs billings, upsell rate |
| Finance Unit Economics | 4 | Gross margin, contribution margin, COGS per unit, operating leverage |
| Marketing Attribution & Spend | 7 | CAC by channel, ROAS, CPC, CPL, blended CAC, payback period |
| Marketing Campaign Performance | 5 | CPA by creative, audience overlap, incrementality, frequency fatigue |
| Product Engagement | 8 | DAU/MAU, session length, feature adoption, stickiness, breadth of use |

Patterns are embedded using the same embedding backend as schema retrieval, so business vocabulary in questions ("conversion dropped", "what's our payback?") maps correctly to the right pattern.

You can also load your own patterns:

```python
chat = ExasolChat("./data.duckdb", kb_path="/path/to/your/patterns/")
```

Or seed the KB with a question→SQL pair:

```python
chat.kb.load_file("/path/to/pattern.json")
```

Patterns persist at `~/.exachat/kb/` by default. Point the UI to a custom directory via the **📖 Knowledge Base** expander or `EXACHAT_KB_PATH` in `.env`.

---

## Safety Model

- **Allowlist-only**: Only `SELECT` and `WITH` (CTE) pass. `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `EXEC`, `CALL`, `EXPORT`, `IMPORT`, `COPY`, `ATTACH`, `DETACH`, `INSTALL`, `LOAD` are all blocked before execution.
- **No `exec()` or `eval()`**: LLM output is never executed as Python code.
- **Pattern matching**: Blocks `read_csv` / `read_parquet` / `read_json` (DuckDB file access), `pg_sleep`, `BENCHMARK`, statement stacking (`;`-separated queries), `SET`, `PRAGMA`.
- **Access control enforcement**: The LLM prompt explicitly lists allowed tables; the safety validator cross-checks the generated SQL against the allowlist — including after auto-correction rewrites.
- **Read-only connections**: DuckDB files always opened with `read_only=True`. SQLAlchemy uses `SET TRANSACTION READ ONLY` where supported.
- **Suspicious query warnings**: `UNION SELECT`, tautology injections, and system table access trigger a visible warning badge without blocking execution.

> Use a **read-only database user** in production. The safety layer is defence-in-depth, not a substitute for proper DB permissions.

---

## Architecture

![exachat architecture — SQL generation pipeline](docs/images/architecture.png)

The diagram shows the full SQL generation pipeline: from a natural language question through KB retrieval, schema narrowing, LLM generation, safety validation, auto-correct retry loop, and result enrichment.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full component breakdown and a Mermaid flowchart of the pipeline.

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

## Module Map

| Module | Purpose |
|--------|---------|
| `app.py` | Streamlit UI — 4 tabs (Ask / Build / Metrics / Schema), compact sidebar, chart controls, retry status |
| `app_builder.py` | Visual Query Builder — dimension / measure / filter / sort UI → SQL |
| `core.py` | Engine — orchestrates the full `ask()` pipeline including auto-correct retry loop |
| `llm.py` | LLM backends — Ollama, MLX (auto-start), OpenAI-compatible; dialect hints; `fix_sql()` for auto-correction |
| `schema.py` | Schema introspection + join inference (exact + fuzzy column-name matching) |
| `safety.py` | SQL validation — allowlist, DDL/DML blocking, injection pattern detection |
| `connection.py` | Connection management — pyexasol, DuckDB native (read-only), SQLAlchemy |
| `builder.py` | QueryBuilder — programmatic SELECT / GROUP BY / filter / sort → schema-qualified SQL |
| `metrics.py` | Metrics Catalog — save / load / run named KPI queries from JSON |
| `kb.py` | Knowledge Base + Schema Index — ChromaDB store; 203 built-in domain patterns; bag-of-words / FastEmbed / Ollama / OpenAI embeddings |
| `charts.py` | Auto-charting — Plotly bar / line / area / scatter / pie |
| `cli.py` | CLI entrypoint — setup wizard, MLX server auto-start, model auto-download |
| `setup_wizard.py` | First-time setup — LLM backend selection, MLX model cache check and download |

---

## Limitations

- **SQL accuracy = LLM quality.** Smaller models produce worse SQL. 7B+ recommended; 14B+ for complex schemas or many tables.
- **Safety layer is regex-based.** It catches known patterns but is not a full SQL parser. Always use a read-only database user.
- **Join inference is heuristic.** Column-name similarity works well for conventional naming; semantic joins (different names, same concept) are not detected automatically, though semantic embeddings reduce this gap for schema retrieval.
- **Charts are LLM-suggested.** Usually correct — use the chart controls in the UI to override type, axes, and measures.
- **Embedding model download required on first use.** FastEmbed downloads ~130 MB on first connect; requires an internet connection once.
- **MLX is Apple Silicon only.** The MLX backend requires an M-series Mac. On other platforms, use Ollama or an OpenAI-compatible API instead.

---

## License

MIT
