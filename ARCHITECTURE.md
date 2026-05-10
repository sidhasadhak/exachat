# ⚡ exachat — Architecture

```mermaid
flowchart LR

    subgraph UI["🖥️  User Interface"]
        direction TB
        SB["⚙️ Sidebar\nConfig & Connect"]
        MA["🗂️ Main Area\nChat · Build · Metrics · Schema"]
        SA(["Streamlit App"])
        SB & MA --> SA
    end

    subgraph CORE["⚙️  Core Engine — ExasolChat"]
        direction TB
        LLM["🧠 LLM Backend\nOllama · MLX · OpenAI"]
        KB["📖 Knowledge Base\nRAG · SQL Patterns"]
        SI["🗺️ Schema Index\nJoin detection"]
        QB["🔧 Query Builder\nVisual SQL"]
        MC["📐 Metrics Catalog\nBusiness KPIs"]
        SV["🛡️ Safety Validator\n+ Auto-Correct"]
        DC["🔌 DB Connection"]
        QB --> MC & SI
    end

    subgraph EB["🔢  Embedding Backends"]
        direction TB
        FE["FastEmbed\nin-process ONNX"]
        OLE["Ollama\nnomic-embed"]
        OAE["OpenAI-compatible\nAPI"]
        BOW["Bag-of-Words\noffline fallback"]
    end

    subgraph ST["💾  Storage"]
        direction TB
        CDB[("ChromaDB\nPatterns · Schema index")]
        MJS[("Metrics JSON\nfiles")]
    end

    subgraph DB["🗄️  Databases"]
        direction TB
        Duck[("DuckDB")]
        Exa[("Exasol")]
        PG[("PostgreSQL")]
        Any[("SQLAlchemy\nany DB")]
    end

    SA -->|"question / query"| CORE
    CORE -->|"SQL · chart · summary"| SA

    KB & SI -->|"embed via"| EB
    KB -->|"persist patterns"| CDB
    SI -->|"persist index"| CDB
    MC -->|"persist"| MJS

    LLM -.->|"optional embed"| OLE & OAE & FE

    DC --> Duck & Exa & PG & Any
```

## Component Responsibilities

| Component | Role |
|---|---|
| **Streamlit App** | Web UI — chat, visual builder, metrics explorer, schema map |
| **LLM Backend** | Text-to-SQL generation, summaries, chart suggestions, follow-ups |
| **Knowledge Base** | RAG over 200+ domain SQL patterns (ChromaDB-backed) |
| **Schema Index** | Per-table semantic retrieval for large schemas (15+ tables) |
| **Query Builder** | Point-and-click SQL without LLM, driven by Metrics Catalog |
| **Metrics Catalog** | Business metric definitions with SQL templates and dimensions |
| **Safety Validator** | Risk classification + auto-correct retry loop (up to 3 attempts) |
| **DB Connection** | Unified connector for DuckDB, Exasol, PostgreSQL, SQLAlchemy |
| **Embedding Backends** | FastEmbed (default, in-process) · Ollama · OpenAI-compat · Bag-of-Words |
