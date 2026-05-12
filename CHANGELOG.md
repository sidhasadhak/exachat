# Changelog

All notable changes to talonsight are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.6.0] — 2026-05-13

### Added

- **Data Quality Scanner** — rule-driven anomaly detection for any connected table.
  Eight check types: null rates, blank strings, whitespace anomalies, invalid dates,
  numeric format violations, rare value detection, duplicate rows, and LLM-inferred
  logical consistency. Results sorted by severity × failure rate with expandable SQL
  viewer. Driven by `dq_config.json` (ships with the package).

- **SQL auto-correction error classifier** — `_classify_sql_error()` maps 21+
  database error patterns to precise DIAGNOSIS + FIX hints injected into the
  correction prompt. The LLM is told exactly what went wrong (e.g. alias-as-schema,
  interval arithmetic, GROUP BY violations) rather than receiving only the raw error
  string. Covers: alias-as-schema, missing FROM entry, missing column/table, function
  not found, ambiguous column, GROUP BY violation, nested window/aggregate, interval
  division, cannot cast interval, ROUND(double precision), type cast failure,
  indeterminate type, operator mismatch, invalid input syntax, date out of range,
  numeric overflow, scalar subquery >1 row, UNION mismatch, duplicate column, syntax
  error, memory exhausted/disk spill, divide by zero.

- **PostgreSQL post-processing pipeline** — three proactive SQL rewriters applied
  before execution and before every retry attempt:
  - `_pg_fix_timestamp_casts` — rewrites `alias.col::timestamp` →
    `NULLIF(alias.col, '')::timestamp`, preventing `InvalidDatetimeFormat` on
    empty-string CSV data and the alias-as-schema error when the alias prefix was
    left orphaned outside the function call.
  - `_pg_rewrite_interval_to_days` — rewrites `(ts - ts)::numeric / 86400` and
    `(ts - ts)::interval / INTERVAL '1 day'` → `EXTRACT(EPOCH FROM expr) / 86400`,
    fixing the `cannot cast type interval to numeric` oscillation loop.
  - `_pg_fix_round` — rewrites `ROUND(expr, n)` → `ROUND((expr)::numeric, n)`,
    fixing `function round(double precision, integer) does not exist` on PostgreSQL.
  - All three use balanced-parenthesis walking to handle arbitrary nesting depth.

- **DQ tab in Streamlit UI** — table selector, progress callback, severity pills
  (🔴 critical / 🟠 high / 🟡 medium / 🟢 low), results dataframe, and expandable
  SQL viewer per check result.

### Changed

- **Embeddings: fastembed removed; BOW is now the default** — talonsight no longer
  depends on fastembed. The default embedding backend is a zero-dependency
  bag-of-words (BOW) hasher (512-dim). Ollama `nomic-embed-text` is available as an
  explicit opt-in via the sidebar; its URL is auto-populated from the configured
  Ollama server address. The stale `[embeddings]` optional dependency has been
  removed from `pyproject.toml`.

- **KB fingerprint cache** — the built-in knowledge base skips the 230-chunk ChromaDB
  upsert on subsequent connects when the JSON files are unchanged. An MD5 fingerprint
  of (filename, size, mtime_ns) is stored at `~/.talonsight/kb/.builtin_fingerprint`.
  Cold-start connect time drops from ~4–8 s to <100 ms on warm cache.

- **Auto-correction now receives full schema** — `fix_sql()` accepts a `schema`
  parameter; the schema prompt is passed on every retry so the LLM can verify
  table and column names when fixing reference errors.

### Fixed

- `_pg_fix_timestamp_casts` regex matched only the bare column name when an alias
  was present (`oi.shipping_limit_date::timestamp`), leaving `oi.` orphaned outside
  the `NULLIF()` call and triggering `InvalidSchemaName`. Fixed with
  `(?<!\w)(?:(\w+)\.)?(\w+)::TYPE` capturing the optional alias prefix.

- Two-attempt oscillation on `timestamp - timestamp` queries: first attempt cast
  to `::numeric` (fails with `cannot cast type interval to numeric`), second attempt
  used `::interval / INTERVAL '1 day'` (fails with `operator does not exist:
  interval / interval`). Fixed by `_pg_rewrite_interval_to_days` rewriting both
  patterns before execution.

- `ROUND(AVG(col), 2)` failing on PostgreSQL with `function round(double precision,
  integer) does not exist`. Fixed by `_pg_fix_round` casting to `::numeric` before
  the two-argument ROUND call.

- `dq_config.json` not found in pipx installs. Added `"dq_config.json"` to
  `[tool.setuptools.package-data]` in `pyproject.toml`.

- Column classification in DQ scanner missing numeric columns with SQL types such
  as `integer`, `bigint`, `double precision`. Changed type check from exact set
  membership to substring containment (`any(k in base_type for k in TYPE_SET)`).

---

## [0.5.0] — 2026-05-11

- Renamed package from `exachat` → `talonsight`. All references, CLI entry point,
  module paths, and PyPI metadata updated.
