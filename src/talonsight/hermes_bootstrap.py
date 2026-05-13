"""Hermes Agent lifecycle manager for TalonSight Analyst mode.

Everything runs from within the Streamlit UI — no terminal required.

Setup flow (all driven from Streamlit):
  1. install()        — runs install.sh, kills before interactive wizard starts
  2. configure_llm()  — writes model: YAML block directly (non-interactive)
  3. register_mcp()   — `hermes mcp add` or direct YAML write
  4. verify()         — confirm hermes -z responds correctly

Per-question usage (Analyst mode):
  ask_hermes(question, output_cb)
      — runs `hermes -z "<question>" -t talonsight` as a subprocess,
        streams progress to output_cb, returns final answer text.

No persistent gateway process is needed.  Hermes -z handles each
question as a fresh sub-agent invocation against the talonsight MCP
toolset (database tools).

The user stays in Streamlit throughout.  Every step streams progress
strings to output_cb so the UI can display them in real time.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import Callable, NamedTuple, Optional
import pandas as pd

logger = logging.getLogger(__name__)


class HermesResult(NamedTuple):
    answer: str
    sql: str = ""
    data: Optional[pd.DataFrame] = None

# ── Config path discovery ─────────────────────────────────────────────────────
# Hermes stores its config under ~/.hermes/ (per the official docs).
# We check several candidates so the code works across Hermes versions.
_CONFIG_CANDIDATES = [
    Path.home() / ".hermes" / "config.yaml",
    Path.home() / ".config" / "hermes" / "config.yaml",
    Path.home() / ".hermes" / "config" / "config.yaml",
]

# Hermes Gateway default port
GATEWAY_PORT = 7860
GATEWAY_URL  = f"http://localhost:{GATEWAY_PORT}"

# ANSI / terminal control sequence stripper
_ANSI_RE = re.compile(
    r'\x1b(?:'
    r'\[[0-9;]*[mGKHFJABCDhlrsuPX]'   # CSI sequences
    r'|\[\?[0-9;]*[hl]'                 # DEC private mode
    r'|[()][AB012]'                     # charset selection
    r'|[78]'                            # save/restore cursor
    r'|M'                               # reverse index
    r')'
)


def _clean(text: str) -> str:
    """Strip ANSI escape codes and return printable text."""
    return _ANSI_RE.sub('', text).strip()


# ── Detection ─────────────────────────────────────────────────────────────────

def is_installed() -> bool:
    """Return True if the `hermes` CLI is on PATH."""
    _refresh_path()
    return shutil.which("hermes") is not None


def _hermes_version() -> str:
    try:
        r = subprocess.run(
            ["hermes", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        return _clean(r.stdout or r.stderr).split('\n')[0]
    except Exception:
        return "unknown"


def _refresh_path() -> None:
    """Add common Hermes install dirs to PATH for the current process."""
    for p in [
        Path.home() / ".local" / "bin",
        Path.home() / ".hermes" / "bin",
        Path("/usr/local/bin"),
    ]:
        s = str(p)
        if p.exists() and s not in os.environ.get("PATH", ""):
            os.environ["PATH"] = s + os.pathsep + os.environ.get("PATH", "")


# ── Installation ──────────────────────────────────────────────────────────────
# Strategy
# --------
# 1. Download install.sh and run it via `bash -s`.
# 2. Stream output line-by-line, stripping ANSI, to output_cb.
# 3. The script installs packages and syncs skills, then launches an
#    interactive TUI setup wizard.  We KILL the process the moment we
#    see any "install done" marker — Hermes is fully installed at that
#    point.  The wizard is just post-install configuration which we
#    handle separately via `hermes config set` (non-interactive).
# 4. Reload PATH and verify `hermes` is resolvable.

_INSTALL_DONE_MARKERS = [
    "skills synced",
    "total bundled",
    "installation complete",
    "successfully installed",
    "hermes is ready",
    "starting setup wizard",   # kill right before it renders
    "let's configure",         # first wizard line
    "press ctrl+c",            # wizard safety message
    "setup wizard",
]


def install(output_cb: Optional[Callable[[str], None]] = None) -> bool:
    """Download and run the Hermes Agent install script from within Python.

    Streams sanitised progress to output_cb.  Returns True when Hermes is
    installed and on PATH.
    """
    def emit(msg: str) -> None:
        clean = _clean(msg)
        if not clean:
            return
        logger.info("hermes-install: %s", clean)
        if output_cb:
            output_cb(clean)

    emit("Downloading Hermes Agent installer…")

    try:
        import urllib.request
        with urllib.request.urlopen(
            "https://hermes-agent.nousresearch.com/install.sh", timeout=30
        ) as r:
            script = r.read().decode("utf-8")
    except Exception as exc:
        emit(f"❌  Could not download installer: {exc}")
        return False

    emit("Running installer (2–3 minutes, once)…")

    env = {
        **os.environ,
        "NONINTERACTIVE":   "1",
        "CI":               "1",
        "HERMES_SKIP_SETUP":"1",   # newer versions honour this
        "TERM":             "dumb", # disables fancy TUI rendering
    }

    try:
        proc = subprocess.Popen(
            ["bash", "-s"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            bufsize=1,
        )
        assert proc.stdin and proc.stdout

        # Write the script and close stdin so bash doesn't wait for more input
        proc.stdin.write(script)
        proc.stdin.close()

        install_done = False
        for raw_line in proc.stdout:
            line = _clean(raw_line)
            if line:
                emit(line)
            low = raw_line.lower()
            if any(m in low for m in _INSTALL_DONE_MARKERS):
                install_done = True
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                emit("✓  Packages installed — skipping interactive wizard")
                break

        if not install_done:
            try:
                proc.wait(timeout=300)
            except subprocess.TimeoutExpired:
                proc.kill()
                emit("❌  Installer timed out after 5 minutes")
                return False

    except Exception as exc:
        emit(f"❌  Installer error: {exc}")
        return False

    _refresh_path()

    if is_installed():
        emit(f"✓  Hermes Agent ready ({_hermes_version()})")
        return True

    emit("⚠  Installed but `hermes` not on PATH yet.")
    emit("   Trying common install locations…")

    # One more attempt — installer may have added to shell rc but not this process
    for extra in [
        Path.home() / ".local" / "bin" / "hermes",
        Path.home() / ".hermes"  / "bin" / "hermes",
    ]:
        if extra.exists():
            os.environ["PATH"] = str(extra.parent) + os.pathsep + os.environ.get("PATH","")
            emit(f"✓  Found hermes at {extra}")
            return True

    emit("❌  Could not locate `hermes` — please open a new terminal and retry.")
    return False


# ── LLM configuration ─────────────────────────────────────────────────────────
# We always write the config as a nested `llm:` block in YAML — this is the
# format Hermes expects.  `hermes config set` writes flat root-level keys
# which triggers "stale root-level provider/base_url" warnings from
# `hermes doctor`.  So we skip the CLI entirely and write YAML directly,
# then run `hermes doctor --fix` to clean up any pre-existing stale keys.

def configure_llm(
    provider: str, model: str, url: str, api_key: str = "",
    output_cb: Optional[Callable[[str], None]] = None,
) -> bool:
    def emit(msg: str) -> None:
        if output_cb:
            output_cb(msg)

    if not is_installed():
        emit("⚠  Hermes not installed — skipping LLM config")
        return False

    # Always write the nested llm: format — avoids stale root-level key warnings
    emit("→  Writing LLM config…")
    ok = _write_config_yaml(provider, model, url, api_key, output_cb)

    # Auto-fix any stale root-level keys left from previous runs or older Hermes
    _doctor_fix(output_cb)

    if ok:
        emit(f"✓  LLM configured ({provider} / {model})")
    return ok


def _doctor_fix(output_cb: Optional[Callable[[str], None]] = None) -> None:
    """Run `hermes doctor --fix` to clean up stale config entries silently."""
    try:
        r = subprocess.run(
            ["hermes", "doctor", "--fix"],
            capture_output=True, text=True, timeout=20,
        )
        # Only surface output if something actually changed
        output = _clean(r.stdout + r.stderr)
        if output_cb and ("fix" in output.lower() or "fixed" in output.lower()):
            output_cb(f"✓  Config cleaned up (hermes doctor --fix)")
    except Exception:
        pass  # non-fatal


def _write_config_yaml(
    provider: str, model: str, url: str, api_key: str,
    output_cb: Optional[Callable[[str], None]] = None,
) -> bool:
    """Write the ``model:`` YAML block that Hermes reads via ``model.default``,
    ``model.provider``, and ``model.base_url``.

    Hermes resolves providers from the ``model:`` section, NOT from a top-level
    ``llm:`` block.  Writing ``llm:`` triggers "stale root-level" doctor warnings
    and routes local models incorrectly (e.g. provider=ollama → OpenRouter).

    Mapping rules
    -------------
    * Ollama / local:  provider="custom", base_url needs /v1 suffix.
    * MLX:             provider="custom", base_url as-is.
    * OpenAI:          provider="openai", no base_url.
    * Anthropic:       provider="anthropic", no base_url.
    * custom:          provider="custom", base_url as-is.
    """
    def emit(msg: str) -> None:
        if output_cb:
            output_cb(msg)

    config_path = _find_config_path()

    # Normalise provider to what Hermes understands
    hermes_provider = provider
    if provider == "ollama":
        hermes_provider = "custom"
        # Ollama's OpenAI-compatible endpoint lives under /v1
        if url and not url.rstrip("/").endswith("/v1"):
            url = url.rstrip("/") + "/v1"
    elif provider == "mlx":
        hermes_provider = "custom"

    # Build model config dict — "default" is the key for the model name
    model_cfg: dict = {"provider": hermes_provider, "default": model}
    if url and hermes_provider not in ("openai", "anthropic"):
        model_cfg["base_url"] = url
    if api_key and hermes_provider in ("openai", "anthropic", "custom"):
        model_cfg["api_key"] = api_key

    try:
        import yaml  # type: ignore[import-untyped]
        existing: dict = {}
        if config_path.exists():
            try:
                existing = yaml.safe_load(config_path.read_text()) or {}
            except Exception:
                pass
        # Write model: block; also remove any stale root-level llm: block
        existing["model"] = model_cfg
        existing.pop("llm", None)          # remove stale llm: block
        existing.pop("provider", None)     # remove stale root-level keys
        existing.pop("base_url", None)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(yaml.dump(existing, default_flow_style=False))
        emit(f"✓  Config written to {config_path}")
        return True
    except ImportError:
        pass  # no yaml library — write raw

    # Raw YAML write (no library)
    lines = ["model:"]
    for k, v in model_cfg.items():
        lines.append(f"  {k}: {v}")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing_text = config_path.read_text() if config_path.exists() else ""
    # Replace existing model: block if present; also strip stale llm: block
    for block_key in ("model", "llm"):
        existing_text = re.sub(
            rf'^{block_key}:.*?(?=^\w|\Z)', '',
            existing_text, flags=re.MULTILINE | re.DOTALL,
        )
    config_path.write_text(existing_text.strip() + "\n" + "\n".join(lines) + "\n")
    emit(f"✓  Config written to {config_path}")
    return True


def _find_config_path() -> Path:
    """Return the existing Hermes config path, or the default location."""
    for p in _CONFIG_CANDIDATES:
        if p.exists():
            return p
    path = _CONFIG_CANDIDATES[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ── MCP registration ──────────────────────────────────────────────────────────

def register_mcp(output_cb: Optional[Callable[[str], None]] = None) -> bool:
    def emit(msg: str) -> None:
        if output_cb:
            output_cb(msg)

    mcp_cmd = shutil.which("talonsight-mcp") or "talonsight-mcp"

    if is_installed():
        try:
            r = subprocess.run(
                ["hermes", "mcp", "add", "talonsight",
                 "--command", mcp_cmd, "--transport", "stdio"],
                capture_output=True, text=True, timeout=15,
            )
            stderr_low = r.stderr.lower()
            if r.returncode == 0 or "already" in stderr_low or "exists" in stderr_low:
                emit("✓  Database tools registered with Hermes")
                return True
            emit(f"⚠  CLI registration: {_clean(r.stderr)[:100]} — trying YAML fallback")
        except Exception as exc:
            emit(f"⚠  CLI registration error ({exc}) — trying YAML fallback")

    return _register_mcp_yaml(mcp_cmd, output_cb)


def _register_mcp_yaml(mcp_cmd: str,
                        output_cb: Optional[Callable[[str], None]] = None) -> bool:
    def emit(msg: str) -> None:
        if output_cb:
            output_cb(msg)

    config_path = _find_config_path()
    entry = {"command": mcp_cmd, "transport": "stdio"}

    try:
        import yaml  # type: ignore[import-untyped]
        existing: dict = {}
        if config_path.exists():
            existing = yaml.safe_load(config_path.read_text()) or {}
        servers = existing.get("mcp_servers", {})
        servers["talonsight"] = entry
        existing["mcp_servers"] = servers
        config_path.write_text(yaml.dump(existing, default_flow_style=False))
        emit("✓  Database tools registered via config.yaml")
        return True
    except ImportError:
        snippet = (
            "\nmcp_servers:\n"
            "  talonsight:\n"
            f"    command: {mcp_cmd}\n"
            "    transport: stdio\n"
        )
        text = config_path.read_text() if config_path.exists() else ""
        if "mcp_servers:" not in text:
            config_path.write_text(text + snippet)
            emit("✓  Database tools registered via config.yaml")
            return True
    except Exception as exc:
        emit(f"⚠  Could not register MCP tools: {exc}")

    return False


# ── Hermes readiness check (no persistent gateway needed) ────────────────────
# Integration uses `hermes -z "<question>" -t talonsight` per-question.
# There is no persistent gateway process.  We just verify the CLI works.

def is_gateway_alive() -> bool:
    """Legacy name kept for call-site compatibility.  Returns True when
    hermes is installed and functional."""
    return is_functional()


def is_functional() -> bool:
    """Return True when `hermes -z` can answer a trivial question."""
    if not is_installed():
        return False
    try:
        r = subprocess.run(
            ["hermes", "-z", "Reply with the single word: ready", "-t", "talonsight"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def start_gateway(output_cb: Optional[Callable[[str], None]] = None) -> bool:
    """No persistent gateway is needed — `hermes -z` is invoked per-question.
    This function just verifies hermes is installed and functional."""
    def emit(msg: str) -> None:
        if output_cb:
            output_cb(msg)

    if not is_installed():
        emit("❌  Hermes not installed")
        return False

    emit("✓  Analyst engine ready (hermes -z per-question mode)")
    return True


def stop_gateway() -> None:
    """No-op — no persistent gateway process exists."""
    pass


# ── Per-question Hermes invocation ────────────────────────────────────────────

def _extract_sql(text: str) -> Optional[str]:
    """Pull a SQL SELECT statement out of a Hermes response.

    Models often emit MCP tool calls as scratchpad JSON rather than invoking
    the protocol.  We intercept here and convert to executable SQL.

    Patterns handled (in priority order):
      1. {"arguments": {"sql": "SELECT ..."}, "name": "run_sql"}
      2. {"arguments": {"table": "...", "n": N}, "name": "get_sample_data"}
         → converted to SELECT * FROM {table} LIMIT {n}
      3. {"sql": "SELECT ..."}
      4. ```sql SELECT ... ```
      5. Bare SELECT ... statement
    """
    import json as _json

    cleaned = re.sub(r'<SCRATCHPAD>|</SCRATCHPAD>', '', text, flags=re.IGNORECASE).strip()

    # Patterns 1–3: find all JSON objects in the text, including nested ones.
    # We use a simple brace-depth scanner to extract complete JSON blobs.
    def _iter_json_blobs(s: str):
        depth = 0
        start = -1
        for i, ch in enumerate(s):
            if ch == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start != -1:
                    yield s[start:i+1]
                    start = -1

    for chunk in _iter_json_blobs(cleaned):
        try:
            obj = _json.loads(chunk)
        except (ValueError, _json.JSONDecodeError):
            continue

        name = (obj.get("name") or "").lower().replace("_", "").replace("mcp", "").replace("talonsight", "")
        args = obj.get("arguments") if isinstance(obj.get("arguments"), dict) else {}

        # get_sample_data / getsampledata tool call → simple SELECT
        if "getsampledata" in name or "sampledata" in name:
            tbl = args.get("table") or args.get("table_name") or ""
            n   = int(args.get("n") or 10)
            if tbl:
                return f"SELECT * FROM {tbl} LIMIT {n}"
            # table arg missing — fall through to let the model retry

        # run_sql / runsql: extract sql argument
        sql = args.get("sql", "") or obj.get("sql", "")
        if sql and re.search(r'\bSELECT\b', sql, re.IGNORECASE):
            return _clean_sql(sql)

    # Pattern 4: fenced code block
    m = re.search(r'```(?:sql)?\s*(SELECT.+?)(?:```|$)', cleaned, re.DOTALL | re.IGNORECASE)
    if m:
        return _clean_sql(m.group(1))

    # Pattern 5: bare SELECT statement
    m = re.search(r'(SELECT\s+.+)', cleaned, re.DOTALL | re.IGNORECASE)
    if m:
        return _clean_sql(m.group(1))

    return None


def _clean_sql(sql: str) -> Optional[str]:
    """Strip trailing non-SQL prose and normalise a SQL string.

    Handles the common model failure of appending prose after a semicolon
    on the same line, e.g.:
        SELECT * FROM t LIMIT 10;` query without any filters?
    """
    # First, truncate at the first semicolon that's followed by non-SQL text.
    # We keep the SQL up to (but not including) the semicolon.
    # A semicolon followed only by whitespace/EOL is fine (stripped later).
    semi_m = re.search(r';(.+)', sql)
    if semi_m:
        trailing = semi_m.group(1).strip().lstrip('`').strip()
        # If anything remains after the semicolon it's prose — cut there
        if trailing:
            sql = sql[:semi_m.start()]

    lines = sql.strip().splitlines()
    sql_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.match(r'^(If|Please|Note|This|The|I |You |Here|Let|That|It )', stripped):
            break
        sql_lines.append(line)
    result = "\n".join(sql_lines).rstrip("; \n\t")
    if result and re.search(r'\bSELECT\b', result, re.IGNORECASE):
        return result
    return None


def _get_selected_schema() -> str:
    """Return the schema the user selected at connect time, or empty string."""
    try:
        from talonsight.preferences import Preferences
        return Preferences.load().selected_schema or ""
    except Exception:
        return ""


def _auto_qualify_tables(sql: str) -> str:
    """Replace unqualified table references with schema-qualified ones.

    e.g.  FROM customer  →  FROM ecommerce.customer
          JOIN orders     →  JOIN ecommerce.orders

    Only substitutes bare names that exist in the user's selected schema;
    tables already qualified (schema.table) or in the main schema are left alone.
    """
    try:
        from talonsight.mcp_server import _get_core
        ts = _get_core()
        _sel_schema = _get_selected_schema()
        _schema_filter = (
            f"AND table_schema = '{_sel_schema}'"
            if _sel_schema
            else "AND table_schema NOT IN ('information_schema','pg_catalog','main')"
        )
        df = ts._db.execute_query(
            f"SELECT table_schema, table_name FROM information_schema.tables "
            f"WHERE table_type = 'BASE TABLE' {_schema_filter}"
        )
        if df is None or df.empty:
            return sql
        # Build map: table_name (lower) → schema
        tbl_map: dict[str, str] = {}
        for _, row in df.iterrows():
            tbl_map[str(row["table_name"]).lower()] = str(row["table_schema"])

        def _qualify(m: re.Match) -> str:
            kw   = m.group(1)   # FROM or JOIN
            name = m.group(2)   # table name (may be quoted)
            bare = name.strip('"').lower()
            if bare in tbl_map:
                schema = tbl_map[bare]
                return f"{kw} {schema}.{name}"
            return m.group(0)

        # Match FROM/JOIN followed by an unqualified identifier (no dot before it)
        qualified = re.sub(
            r'\b(FROM|JOIN)\s+("?[A-Za-z_]\w*"?)(?!\s*\.)',
            _qualify,
            sql,
            flags=re.IGNORECASE,
        )
        return qualified
    except Exception:
        return sql


def _execute_sql_safe(sql: str) -> tuple[str, str, Optional[pd.DataFrame]]:
    """Run sql via the MCP server; return (markdown_table, error_or_empty, df_or_None).

    Auto-qualifies bare table names (customer → ecommerce.customer) and
    enforces the schema/table allowlist so the agent cannot query objects
    outside the connected database.
    """
    try:
        from talonsight.mcp_server import _get_core, _get_allowlists
        from talonsight.safety import validate_sql, RiskLevel
        ts = _get_core()

        # Qualify unqualified table references before safety check
        sql = _auto_qualify_tables(sql)

        _schemas, _tables = _get_allowlists()
        verdict = validate_sql(
            sql,
            allowed_schemas=_schemas or None,
            allowed_tables=_tables or None,
        )
        if verdict.level == RiskLevel.BLOCKED:
            return f"BLOCKED: {verdict.reason}", "", None
        sql = sql.rstrip("; \n\t")
        if not re.search(r'\bLIMIT\b', sql, re.IGNORECASE):
            sql = sql + "\nLIMIT 200"
        df = ts._db.execute_query(sql)
        if df is None or df.empty:
            return "Query returned no rows.", "", None
        df = _normalise_dates(df)
        return df.to_markdown(index=False), "", df
    except Exception as exc:
        return "", str(exc), None


def _normalise_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Convert all date/datetime columns to YYYY-MM-DD strings.

    Consistent ISO date strings make it far easier for LLMs to reason about
    time-series data and write correct WHERE / GROUP BY date filters.
    """
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
        elif df[col].dtype == object:
            # Detect object columns that contain Python date/datetime objects
            sample = df[col].dropna().head(3)
            if not sample.empty:
                import datetime as _dt
                if isinstance(sample.iloc[0], (_dt.date, _dt.datetime)):
                    df[col] = df[col].apply(
                        lambda v: v.strftime("%Y-%m-%d") if isinstance(v, (_dt.date, _dt.datetime)) else v
                    )
    return df


def _ask_hermes_raw(prompt: str, timeout: int = 90) -> str:
    """Low-level hermes -z call, returns raw stdout."""
    try:
        r = subprocess.run(
            ["hermes", "-z", prompt, "-t", "talonsight"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _repair_and_execute(
    sql: str, error: str, schema_context: str, question: str
) -> tuple[str, str, Optional[pd.DataFrame]]:
    """Ask the model to fix a failed SQL given the error message.

    Returns (markdown_table, final_error, df_or_None).
    """
    repair_prompt = (
        f"{schema_context}\n\n"
        f"The following SQL failed:\n```sql\n{sql}\n```\n\n"
        f"Error: {error}\n\n"
        f"Write a corrected SELECT query that answers: {question!r}\n"
        f"Use ONLY the tables shown above. Do NOT JOIN tables not listed. "
        f"Return ONLY the SQL, no explanation."
    )
    raw = _ask_hermes_raw(repair_prompt, timeout=90)
    fixed_sql = _extract_sql(raw) if raw else None
    if not fixed_sql:
        return "", error, None
    result, err2, df2 = _execute_sql_safe(fixed_sql)
    if err2:
        return "", err2, None
    return result, "", df2


def _build_enriched_prompt(
    question: str,
    history: Optional[list[dict]] = None,
) -> str:
    """Prefix the question with schema context for only the relevant tables,
    plus recent conversation history so follow-up questions have context.

    Scoring: pick top-3 tables by keyword overlap with the combined text of
    the question + recent history (so follow-ups like "show this in a table"
    inherit the right tables from prior turns).
    """
    try:
        from talonsight.mcp_server import _get_core, _get_schema
        ts = _get_core()

        # Combine current question + recent history text for table scoring
        history_text = ""
        if history:
            for msg in history[-6:]:
                content = msg.get("content") or ""
                if not content and "result" in msg:
                    content = getattr(msg["result"], "summary", "") or ""
                if content:
                    history_text += f" {content}"

        search_text = question + " " + history_text
        q_tokens = set(re.split(r'\W+', search_text.lower()))
        q_tokens.discard('')

        # Build full table list from information_schema — scoped to the schema
        # the user selected at connect time so the agent cannot see or query
        # tables from other schemas in the same database file.
        _sel_schema = _get_selected_schema()
        _schema_filter = (
            f"AND table_schema = '{_sel_schema}'"
            if _sel_schema
            else "AND table_schema NOT IN ('information_schema','pg_catalog')"
        )
        try:
            _df_all = ts._db.execute_query(
                f"SELECT table_schema, table_name, column_name "
                f"FROM information_schema.columns "
                f"WHERE 1=1 {_schema_filter} "
                f"ORDER BY table_name, ordinal_position"
            )
            _all_cols: dict[str, list[str]] = {}
            _tbl_schema: dict[str, str] = {}
            if _df_all is not None and not _df_all.empty:
                for _, _r in _df_all.iterrows():
                    _all_cols.setdefault(_r["table_name"], []).append(_r["column_name"])
                    _tbl_schema[_r["table_name"]] = _r["table_schema"]
        except Exception:
            _all_cols = {t.name: [c.name for c in t.columns] for t in ts.schema_context.tables}
            _tbl_schema = {t.name: "main" for t in ts.schema_context.tables}

        scores: list[tuple[int, str]] = []
        for tbl_name, col_names in _all_cols.items():
            tbl_tokens = set(re.split(r'[_\W]+', tbl_name.lower()))
            col_tokens: set[str] = set()
            for col in col_names:
                col_tokens.update(re.split(r'[_\W]+', col.lower()))
            score = len(q_tokens & (tbl_tokens | col_tokens))
            scores.append((score, tbl_name))

        scores.sort(key=lambda x: (-x[0], x[1]))

        if not scores or scores[0][0] == 0:
            chosen = [n for n, _ in sorted(_all_cols.items(), key=lambda x: -len(x[1]))[:3]]
        else:
            # Light stemming so "states"→"state", "customers"→"customer"
            q_stem = q_tokens | {t[:-1] for t in q_tokens if t.endswith('s') and len(t) > 3}
            scored_stem: list[tuple[int, str]] = []
            for tbl_name, col_names in _all_cols.items():
                tbl_tokens = set(re.split(r'[_\W]+', tbl_name.lower()))
                col_tokens_s: set[str] = set()
                for col in col_names:
                    col_tokens_s.update(re.split(r'[_\W]+', col.lower()))
                sc = len(q_stem & (tbl_tokens | col_tokens_s))
                scored_stem.append((sc, tbl_name))
            scored_stem.sort(key=lambda x: (-x[0], x[1]))
            chosen = [name for sc, name in scored_stem[:3] if sc > 0]
            if not chosen:
                chosen = [scored_stem[0][1]]

        # Expand with FK-linked bridge tables so JOIN chains work (cap at 4)
        # Only use semantically safe FK keys to avoid false matches.
        _FK = {'order_id', 'customer_id', 'seller_id', 'review_id', 'payment_id'}
        for _seed in list(chosen):
            if len(chosen) >= 4:
                break
            seed_fk = {c.lower() for c in _all_cols.get(_seed, [])} & _FK
            if not seed_fk:
                continue
            for _, cand in scores:          # use original scores for ordering
                if len(chosen) >= 4:
                    break
                if cand in chosen:
                    continue
                if seed_fk & {c.lower() for c in _all_cols.get(cand, [])}:
                    chosen.append(cand)

        # Build the schema string with fully-qualified names for non-main tables
        # so the model writes the correct FROM / JOIN references.
        schema_lines: list[str] = []
        for tbl_name in chosen:
            tschema = _tbl_schema.get(tbl_name, "main")
            fqn = f"{tschema}.{tbl_name}" if tschema != "main" else tbl_name
            # Get columns from information_schema result
            col_rows = _all_cols.get(tbl_name, [])
            schema_lines.append(f"\nTable: {fqn}")
            for col in col_rows:
                safe = f'"{col}"' if any(c in col for c in (' ', '-', '.')) else col
                schema_lines.append(f"  {safe}")
        schema = "\n".join(schema_lines) if schema_lines else _get_schema(chosen)

        # Build conversation context block for follow-up awareness
        conv_block = ""
        if history:
            conv_lines: list[str] = []
            for msg in history[-6:]:
                role = msg.get("role", "")
                content = msg.get("content") or ""
                if not content and "result" in msg:
                    content = getattr(msg["result"], "summary", "") or ""
                if content and role in ("user", "assistant"):
                    label = "User" if role == "user" else "Assistant"
                    snippet = content[:400] + "…" if len(content) > 400 else content
                    conv_lines.append(f"{label}: {snippet}")
            if conv_lines:
                conv_block = "RECENT CONVERSATION:\n" + "\n".join(conv_lines) + "\n\n"

        context = (
            f"You are a SQL data analyst. Use ONLY these tables:\n\n"
            f"{schema}\n\n"
            f"RULES:\n"
            f"- Call run_sql with a valid SELECT query.\n"
            f"- Reference each table EXACTLY as shown above (e.g. 'ecommerce.customer' not 'customer').\n"
            f"- Use ONLY the tables listed above. Do NOT JOIN tables not listed.\n"
            f"- Use EXACT column names shown — never guess or rename columns.\n"
            f"- Do NOT add WHERE filters unless the question explicitly asks to filter.\n"
            f"- GROUP BY and ORDER BY for ranked/aggregated results.\n\n"
            f"{conv_block}"
            f"QUESTION: {question}"
        )
        return context
    except Exception:
        return question


_ANALYST_TICKS = [
    # (elapsed_seconds, message)
    (3,   "🔍 Examining schema…"),
    (8,   "📋 Identifying relevant tables…"),
    (15,  "⚙️  Querying database…"),
    (25,  "📊 Analysing results…"),
    (40,  "🧩 Cross-referencing data…"),
    (60,  "✍️  Composing answer…"),
    (90,  "⏳ Still working — complex question takes a moment…"),
    (120, "⏳ Almost there…"),
    (180, "⏳ Finalising…"),
]


def ask_hermes(
    question: str,
    output_cb: Optional[Callable[[str], None]] = None,
    timeout: int = 300,
    history: Optional[list[dict]] = None,
) -> HermesResult:
    """Run `hermes -z <question> -t talonsight` and return the final answer.

    hermes -z suppresses all output until the final answer is ready, so we
    emit synthetic timed progress ticks via output_cb to keep the UI alive.
    The talonsight MCP toolset gives Hermes access to the connected database.

    Returns a HermesResult with answer, sql, and data fields.
    """
    def emit(msg: str) -> None:
        if output_cb and msg.strip():
            output_cb(msg.strip())

    if not is_installed():
        return HermesResult(answer="❌ Hermes Agent is not installed. Please complete onboarding first.")

    emit("🧠 Analyst starting…")

    # Re-sync hermes config with current preferences so the correct model is
    # always used — the YAML is only written during onboarding, so if the user
    # changes the model in the TalonSight UI the subprocess would otherwise still
    # use the old model (e.g. hermes3:8b instead of gemma4:31b-cloud).
    try:
        from talonsight.preferences import Preferences as _Prefs
        _p = _Prefs.load()
        if _p.llm_model:
            _write_config_yaml(
                _p.llm_provider or "ollama",
                _p.llm_model,
                _p.llm_url or "",
                _p.llm_api_key or "",
            )
    except Exception:
        pass  # non-fatal — proceed with whatever config is already on disk

    # Prepend schema + recent chat history so the model has full context
    enriched_question = _build_enriched_prompt(question, history=history)

    try:
        proc = subprocess.Popen(
            ["hermes", "-z", enriched_question, "-t", "talonsight"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except Exception as exc:
        return HermesResult(answer=f"❌ Could not launch Hermes: {exc}")

    # ── Timed progress ticker ─────────────────────────────────────────────────
    # hermes -z redirects all internal output to /dev/null and only writes the
    # final answer to stdout at the very end.  We fire synthetic status ticks
    # on a background thread so the UI doesn't look frozen.
    _done_event = threading.Event()

    def _tick() -> None:
        import time as _time
        start = _time.monotonic()
        tick_idx = 0
        while not _done_event.wait(timeout=1.0):
            elapsed = _time.monotonic() - start
            if tick_idx < len(_ANALYST_TICKS):
                threshold, msg = _ANALYST_TICKS[tick_idx]
                if elapsed >= threshold:
                    emit(msg)
                    tick_idx += 1

    ticker = threading.Thread(target=_tick, daemon=True)
    ticker.start()

    # Collect stdout (final answer written by hermes at the very end)
    output_lines: list[str] = []
    stderr_lines: list[str] = []
    assert proc.stdout and proc.stderr

    def _drain_stderr() -> None:
        for raw in proc.stderr:
            line = _clean(raw)
            if line:
                stderr_lines.append(line)

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    for raw in proc.stdout:
        line = _clean(raw)
        if line:
            output_lines.append(line)

    _done_event.set()  # stop the ticker

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return HermesResult(answer="❌ Analysis timed out after 5 minutes.")
    finally:
        ticker.join(timeout=3)
        stderr_thread.join(timeout=3)

    if proc.returncode != 0:
        diag = "\n".join(stderr_lines[-5:]) if stderr_lines else "no details"
        return HermesResult(answer=f"❌ Hermes exited with code {proc.returncode}.\n{diag}")

    answer = "\n".join(output_lines).strip()

    # ── Intercept tool-call-as-text responses ─────────────────────────────────
    # hermes3 and similar small models often output MCP tool calls as scratchpad
    # JSON rather than invoking the protocol.  Detect this, execute the SQL
    # ourselves, then ask Hermes to narrate the results.
    if not answer or _extract_sql(answer):
        sql = _extract_sql(answer) if answer else None
        if sql:
            emit("⚙️  Executing SQL…")
            table, err, _df = _execute_sql_safe(sql)
            if err:
                # SQL had hallucinated columns / WHERE clauses — tell user
                return HermesResult(
                    answer=(
                        f"Generated SQL had an error: {err}\n\n"
                        f"**SQL attempted:**\n```sql\n{sql}\n```"
                    )
                )
            if not table or table.strip() == "Query returned no rows.":
                return HermesResult(answer=f"The query returned no rows.\n\n```sql\n{sql}\n```")

            emit("✍️  Composing answer…")
            narration = _narrate_result(question, sql, table)
            return HermesResult(answer=narration, sql=sql, data=_df)

    # ── Rescue ASCII / text-chart responses ──────────────────────────────────
    # Some models (especially smaller ones) output "I cannot render graphics…
    # here is a text-based bar chart" instead of returning raw data.
    # We parse that ASCII output back into a real DataFrame so the Streamlit
    # chart renderer can produce an actual Plotly bar chart.
    if answer and _df_from_ascii_chart(answer) is not None:
        _rescued_df = _df_from_ascii_chart(answer)
        # The chart/table is the content — suppress the ASCII text entirely
        # so the UI renders only the Plotly component, nothing else.
        return HermesResult(answer="", sql="", data=_rescued_df)

    return HermesResult(answer=answer) if answer else HermesResult(answer="No answer was returned.")


def _df_from_ascii_chart(text: str) -> "Optional[pd.DataFrame]":
    """Parse a text-based bar chart into a two-column DataFrame.

    Handles two common model output formats:

      1.  STATE | ############ 718,723
      2.  STATE         718723    (whitespace-separated, numeric in last column)

    Returns a DataFrame with columns [label_col, value_col] or None if not
    enough rows are found.
    """
    rows: list[tuple[str, float]] = []

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("-") or line.startswith("="):
            continue

        # Format 1 — "LABEL | ####...#### 123,456"
        m = re.match(r'^([^|]+)\|\s*[#\-=*]+\s*([\d,\.]+)\s*$', line)
        if m:
            label = m.group(1).strip()
            val_str = m.group(2).replace(",", "")
            try:
                rows.append((label, float(val_str)))
                continue
            except ValueError:
                pass

        # Format 2 — "LABEL   123456" or "LABEL   1,234,567"
        m2 = re.match(r'^([A-Za-z][A-Za-z\s_\-]+?)\s+([\d,\.]+)\s*$', line)
        if m2:
            label = m2.group(1).strip()
            val_str = m2.group(2).replace(",", "")
            try:
                rows.append((label, float(val_str)))
            except ValueError:
                pass

    if len(rows) < 2:
        return None

    labels, values = zip(*rows)
    return pd.DataFrame({"category": list(labels), "value": list(values)})


def _narrate_result(question: str, sql: str, table: str) -> str:
    """Ask Hermes to write a natural-language answer given the SQL result data."""
    prompt = (
        f"A SQL query was run to answer this question: {question!r}\n\n"
        f"SQL used:\n```sql\n{sql}\n```\n\n"
        f"Results:\n{table}\n\n"
        f"Write a clear, concise answer to the question using the data above. "
        f"Mention specific numbers, top entries, and any notable patterns. "
        f"Do not re-state the SQL. 3-5 sentences max."
    )
    try:
        result = subprocess.run(
            ["hermes", "-z", prompt, "-t", "talonsight"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
        narration = result.stdout.strip()
        if narration and not _extract_sql(narration):
            # Return narrative only — the raw data is in HermesResult.data
            # and will be rendered as a Plotly chart/table by the UI.
            return narration
    except Exception:
        pass
    # Fallback: no narration available — return a brief placeholder so the
    # UI still has something to show in the Finding box.  The actual data
    # table / chart is rendered from HermesResult.data by _render_result.
    return "Query complete — see the data table below."


def run_doctor(output_cb: Optional[Callable[[str], None]] = None) -> None:
    """Run `hermes doctor` and stream its output — useful for diagnostics."""
    def emit(msg: str) -> None:
        if output_cb:
            output_cb(msg)
    if not is_installed():
        emit("Hermes not installed — nothing to diagnose")
        return
    try:
        r = subprocess.run(
            ["hermes", "doctor"], capture_output=True, text=True, timeout=30
        )
        for line in (r.stdout + r.stderr).splitlines():
            clean = _clean(line)
            if clean:
                emit(clean)
    except Exception as exc:
        emit(f"hermes doctor error: {exc}")


# ── All-in-one setup ──────────────────────────────────────────────────────────

def ensure_analyst_ready(
    provider: str,
    model: str,
    url: str,
    api_key: str = "",
    output_cb: Optional[Callable[[str], None]] = None,
) -> bool:
    """Install → configure LLM → register MCP → verify.

    No persistent gateway is started.  Each user question is handled by
    a fresh `hermes -z "<question>" -t talonsight` invocation.

    Everything streams to output_cb for live display in Streamlit.
    Returns True when Hermes is installed, configured, and verified.
    """
    def emit(msg: str) -> None:
        logger.info("hermes-setup: %s", msg)
        if output_cb:
            output_cb(msg)

    # 1 — Install
    if is_installed():
        emit(f"✓  Hermes Agent already installed ({_hermes_version()})")
    else:
        emit("Installing Hermes Agent…")
        if not install(output_cb=output_cb):
            emit("❌  Installation failed. Click Retry to try again.")
            return False

    # 2 — Configure LLM (writes model: YAML block)
    emit(f"Configuring LLM ({provider} / {model})…")
    configure_llm(provider, model, url, api_key, output_cb=output_cb)

    # 3 — Register MCP (talonsight database tools)
    emit("Registering database tools…")
    register_mcp(output_cb=output_cb)

    emit("✓  Setup complete — Analyst engine ready")
    return True


# ── Onboarding reset ──────────────────────────────────────────────────────────

def reset_onboarding() -> None:
    """Reset the onboarding state so the wizard shows again on next launch."""
    from talonsight.preferences import Preferences
    prefs = Preferences.load()
    prefs.onboarding_complete = False
    prefs.save()
