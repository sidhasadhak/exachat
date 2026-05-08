"""SQL pattern knowledge base — RAG retrieval over structured JSON chunks.

Chunks are embedded by: title + intent_tags + when_to_use + anti_patterns.
Retrieval injects pattern templates, hints, and anti-patterns into the LLM prompt.

Built-in patterns live in knowledge_base/*.json (bundled with the package).
Additional patterns can be loaded from any directory via load_dir().

Also provides SchemaIndex: ChromaDB-backed per-table schema retrieval that
narrows the schema prompt to only relevant tables for large databases.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from exachat.schema import TableInfo

logger = logging.getLogger(__name__)


class _BagOfWordsEF:
    """Offline ChromaDB embedding — no model download required.

    Hashed token counts projected into a fixed-dim vector, L2-normalised.
    Works entirely offline; used as the default and as the fallback when the
    semantic embedding server is unreachable.
    """
    DIM = 512

    def name(self) -> str:
        return "bag-of-words-v2"

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in input]

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self.__call__(input)

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.DIM
        for token in text.lower().split():
            idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % self.DIM
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class _SemanticEF:
    """Semantic embedding function backed by an HTTP embedding API.

    Supports two API types:
    - ``"ollama"``  — Ollama's  POST /api/embeddings  (one text at a time)
    - ``"openai"``  — Any OpenAI-compatible  POST /v1/embeddings  (batched)

    Safety guarantees
    -----------------
    * Probes the server at construction time.  If unreachable, ``available``
      is set to False and every call transparently falls back to
      ``_BagOfWordsEF`` — no errors surface to the caller.
    * ``name()`` encodes the API type **and** a hash of the model identifier.
      ChromaDB stores this in collection metadata; when it changes (different
      model or different backend) ChromaDB raises a conflict that our
      ``_get_or_create`` handler catches and resolves by rebuilding the
      collection.  This prevents mixing vectors from different models.
    * Batch calls for OpenAI-compatible are done in a single HTTP request;
      Ollama is called sequentially because it doesn't support batching.
    """

    def __init__(self, base_url: str, model: str, api_type: str = "ollama") -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_type = api_type  # "ollama" or "openai"
        self._fallback = _BagOfWordsEF()
        self.available = False

        # Probe: embed a single token to confirm connectivity and get dimension
        try:
            test = self._call_api(["ping"])
            self._dim = len(test[0])
            self.available = True
        except Exception as exc:
            warnings.warn(
                f"Semantic embedding server unreachable ({exc}). "
                "Falling back to bag-of-words embeddings.",
                RuntimeWarning,
                stacklevel=2,
            )

    # ── ChromaDB EF protocol ──────────────────────────────────────────

    def name(self) -> str:
        """Stable identifier that encodes model identity for ChromaDB."""
        model_hash = hashlib.md5(self._model.encode()).hexdigest()[:8]
        return f"semantic-{self._api_type}-{model_hash}"

    def __call__(self, input: list[str]) -> list[list[float]]:
        if not self.available:
            return self._fallback(input)
        try:
            return self._call_api(input)
        except Exception as exc:
            logger.warning("Semantic embedding call failed (%s); using bag-of-words.", exc)
            return self._fallback(input)

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self.__call__(input)

    # ── HTTP calls ────────────────────────────────────────────────────

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        import httpx
        if self._api_type == "ollama":
            return self._call_ollama(texts)
        return self._call_openai(texts)

    def _call_ollama(self, texts: list[str]) -> list[list[float]]:
        """Ollama embeds one text at a time via POST /api/embeddings."""
        import httpx
        vecs: list[list[float]] = []
        with httpx.Client(timeout=30.0) as client:
            for text in texts:
                resp = client.post(
                    f"{self._base_url}/api/embeddings",
                    json={"model": self._model, "prompt": text},
                )
                resp.raise_for_status()
                vecs.append(resp.json()["embedding"])
        return vecs

    def _call_openai(self, texts: list[str]) -> list[list[float]]:
        """OpenAI-compatible batched POST /embeddings."""
        import httpx
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{self._base_url}/embeddings",
                json={"model": self._model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            # Sort by index to preserve input order
            return [d["embedding"] for d in sorted(data, key=lambda x: x["index"])]


class _FastEmbedEF:
    """In-process semantic embeddings via fastembed (no server required).

    Uses the ``nomic-ai/nomic-embed-text-v1.5`` model by default — a 768-dim
    model (~130 MB) that is downloaded once on first use and cached locally.
    Runs on CPU via ONNX; on Apple Silicon this is accelerated automatically.

    Requires the ``embeddings`` optional extra::

        pip install exachat[embeddings]

    Falls back to ``_BagOfWordsEF`` with a warning if fastembed is not
    installed, so the rest of the app continues to work.
    """

    DEFAULT_MODEL = "nomic-ai/nomic-embed-text-v1.5"

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self._model_name = model or self.DEFAULT_MODEL
        self._model = None          # lazy — loaded on first embed call
        self._fallback = _BagOfWordsEF()
        self.available = False

        try:
            from fastembed import TextEmbedding  # noqa: F401 — just probe import
            self._TextEmbedding = TextEmbedding
            self.available = True
        except ImportError:
            warnings.warn(
                "fastembed is not installed — semantic embeddings unavailable. "
                "Run: pip install exachat[embeddings]  "
                "Falling back to bag-of-words embeddings.",
                RuntimeWarning,
                stacklevel=2,
            )

    # ── ChromaDB EF protocol ──────────────────────────────────────────

    def name(self) -> str:
        model_hash = hashlib.md5(self._model_name.encode()).hexdigest()[:8]
        return f"fastembed-{model_hash}"

    def __call__(self, input: list[str]) -> list[list[float]]:
        if not self.available:
            return self._fallback(input)
        try:
            m = self._get_model()
            return [e.tolist() for e in m.embed(input)]
        except Exception as exc:
            logger.warning("FastEmbed call failed (%s); using bag-of-words.", exc)
            return self._fallback(input)

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self.__call__(input)

    # ── Internals ─────────────────────────────────────────────────────

    def _get_model(self):
        """Lazy model load — downloads on first call, cached afterwards."""
        if self._model is None:
            self._model = self._TextEmbedding(self._model_name)
        return self._model


def build_embedding_fn(
    backend: str = "bow",
    url: str = "",
    model: str = "",
) -> "_BagOfWordsEF | _FastEmbedEF | _SemanticEF":
    """Return the right ChromaDB embedding function for the given backend.

    Parameters
    ----------
    backend:
        ``"bow"``       — offline bag-of-words (default, no setup needed)
        ``"fastembed"`` — in-process via fastembed (``pip install exachat[embeddings]``)
        ``"ollama"``    — Ollama embedding API (``ollama pull nomic-embed-text``)
        ``"openai"``    — OpenAI-compatible embedding API (LM Studio, etc.)
    url:
        Base URL for server-backed backends.
        Ollama default : ``http://localhost:11434``
        OpenAI default : ``http://localhost:1234/v1``
    model:
        Embedding model name.
        fastembed default : ``nomic-ai/nomic-embed-text-v1.5``
        Ollama / OpenAI  : ``nomic-embed-text``
    """
    if not backend or backend == "bow":
        return _BagOfWordsEF()

    if backend == "fastembed":
        fe_model = model.strip() or _FastEmbedEF.DEFAULT_MODEL
        return _FastEmbedEF(model=fe_model)

    # Server-backed: ollama or openai
    defaults = {
        "ollama": "http://localhost:11434",
        "openai": "http://localhost:1234/v1",
    }
    resolved_url = url.strip() or defaults.get(backend, "http://localhost:11434")
    resolved_model = model.strip() or "nomic-embed-text"
    return _SemanticEF(base_url=resolved_url, model=resolved_model, api_type=backend)


def _embed_text(chunk: dict) -> str:
    """Build the text to embed for a KB chunk."""
    parts = [chunk.get("title", "")]

    tags = chunk.get("intent_tags", [])
    if isinstance(tags, list):
        parts.append(" ".join(tags))
    elif isinstance(tags, str):
        parts.append(tags)

    when = chunk.get("when_to_use", "")
    if isinstance(when, list):
        parts.append(" ".join(when))
    elif isinstance(when, str):
        parts.append(when)

    anti = chunk.get("anti_patterns", [])
    if isinstance(anti, list):
        parts.append(" ".join(anti))
    elif isinstance(anti, str):
        parts.append(anti)

    return " ".join(p for p in parts if p)


class KnowledgeBase:
    """ChromaDB-backed SQL pattern knowledge base."""

    _BUILTIN_DIR = Path(__file__).parent / "knowledge_base"

    def __init__(
        self,
        persist_dir: Optional[str] = None,
        n_results: int = 3,
        ef: Optional["_BagOfWordsEF | _SemanticEF"] = None,
    ):
        self._n_results = n_results
        self._persist_dir = persist_dir or str(Path.home() / ".exachat" / "kb")
        Path(self._persist_dir).mkdir(parents=True, exist_ok=True)

        import chromadb
        self._client = chromadb.PersistentClient(path=self._persist_dir)
        self._ef = ef if ef is not None else _BagOfWordsEF()
        self._collection = self._get_or_create("exachat_kb")

        # Always load the built-in patterns
        self._load_builtin()

    def _get_or_create(self, name: str):
        import chromadb
        try:
            return self._client.get_or_create_collection(
                name=name,
                embedding_function=self._ef,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            if "conflict" in str(e).lower() or "embedding function" in str(e).lower():
                self._client.delete_collection(name=name)
                return self._client.create_collection(
                    name=name,
                    embedding_function=self._ef,
                    metadata={"hnsw:space": "cosine"},
                )
            raise

    def _load_builtin(self) -> None:
        if not self._BUILTIN_DIR.exists():
            return
        chunks = []
        for f in sorted(self._BUILTIN_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                if isinstance(data, list):
                    chunks.extend(data)
                elif isinstance(data, dict):
                    chunks.append(data)
            except Exception:
                pass
        if chunks:
            self._upsert(chunks)

    def load_dir(self, path: str) -> int:
        """Load additional JSON chunks from a directory. Returns count ingested."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"KB directory not found: {path}")
        chunks = []
        for f in sorted(p.glob("**/*.json")):
            try:
                data = json.loads(f.read_text())
                if isinstance(data, list):
                    chunks.extend(data)
                elif isinstance(data, dict):
                    chunks.append(data)
            except Exception:
                pass
        return self._upsert(chunks)

    def load_file(self, path: str) -> int:
        """Load chunks from a single JSON file."""
        data = json.loads(Path(path).read_text())
        chunks = data if isinstance(data, list) else [data]
        return self._upsert(chunks)

    def _upsert(self, chunks: list[dict]) -> int:
        ids, documents, metadatas = [], [], []
        for chunk in chunks:
            try:
                doc_id = str(chunk.get("id") or hashlib.sha256(
                    json.dumps(chunk, sort_keys=True).encode()
                ).hexdigest()[:16])
                ids.append(doc_id)
                documents.append(_embed_text(chunk))
                metadatas.append({"chunk_json": json.dumps(chunk)})
            except Exception:
                pass
        if ids:
            self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return len(ids)

    def search(self, question: str, n_results: Optional[int] = None) -> list[dict]:
        """Return the top-N most relevant pattern chunks for a question."""
        n = n_results or self._n_results
        if self._collection.count() == 0:
            return []
        actual_n = min(n, self._collection.count())
        results = self._collection.query(query_texts=[question], n_results=actual_n)
        patterns = []
        for meta in results["metadatas"][0]:
            try:
                patterns.append(json.loads(meta["chunk_json"]))
            except Exception:
                pass
        return patterns

    def format_for_prompt(self, patterns: list[dict], dialect: str = "") -> str:
        """Render retrieved patterns as a prompt snippet."""
        parts = []
        for p in patterns:
            lines = [f"-- Pattern: {p.get('title', '')}"]

            when = p.get("when_to_use", "")
            if when:
                when_str = "; ".join(when) if isinstance(when, list) else when
                lines.append(f"-- Use when: {when_str}")

            template = p.get("template", "")
            if template:
                lines.append(f"-- Template:\n{template}")

            anti = p.get("anti_patterns", [])
            if anti:
                anti_str = "; ".join(anti) if isinstance(anti, list) else anti
                lines.append(f"-- Avoid: {anti_str}")

            hints = p.get("llm_hints", "")
            if hints:
                lines.append(f"-- Hints: {hints}")

            dialect_notes = p.get("dialect_notes", {})
            if dialect and isinstance(dialect_notes, dict) and dialect in dialect_notes:
                lines.append(f"-- {dialect} note: {dialect_notes[dialect]}")

            parts.append("\n".join(lines))
        return "\n\n".join(parts)

    @property
    def count(self) -> int:
        return self._collection.count()


# ── Schema Index ──────────────────────────────────────────────────────────────

class SchemaIndex:
    """ChromaDB-backed per-table schema retrieval for large databases.

    For schemas with more than THRESHOLD tables, each table is stored as a
    ChromaDB document (name + column names + types).  On every query, only the
    most relevant tables are retrieved instead of dumping the entire schema into
    the prompt.  Tables that are join-connected to retrieved ones are always
    included too, so JOIN paths are never accidentally broken.

    For schemas at or below THRESHOLD tables this class is a transparent
    pass-through — it returns all tables so callers don't need to branch.
    """

    THRESHOLD = 15       # activate only when schema exceeds this many tables
    DEFAULT_N  = 10      # number of tables to retrieve per query

    def __init__(
        self,
        persist_dir: Optional[str] = None,
        ef: Optional["_BagOfWordsEF | _SemanticEF"] = None,
    ):
        self._persist_dir = persist_dir or str(Path.home() / ".exachat" / "schema_idx")
        Path(self._persist_dir).mkdir(parents=True, exist_ok=True)
        import chromadb
        self._client = chromadb.PersistentClient(path=self._persist_dir)
        self._ef = ef if ef is not None else _BagOfWordsEF()
        self._collection = None
        self._tables: list[TableInfo] = []
        # Pre-computed adjacency: table_name → set of join-connected table names
        self._join_neighbors: dict[str, set[str]] = {}

    # ── Indexing ──────────────────────────────────────────────────────

    def index(self, tables: list[TableInfo], fingerprint: str) -> None:
        """Index all tables for the current connection.

        Re-indexes on every connect so schema changes are picked up
        automatically.  The collection is keyed by a short fingerprint so
        stale collections from previous connections are replaced.
        """
        import chromadb

        self._tables = tables
        # Explicit FK neighbors used for safe join expansion in retrieve()
        self._join_neighbors = self._build_explicit_neighbors(tables)

        if len(tables) <= self.THRESHOLD:
            return  # small schema — no index needed

        coll_name = f"sch{fingerprint[:12]}"  # 15 chars, safe for chroma
        try:
            self._client.delete_collection(coll_name)
        except Exception:
            pass
        self._collection = self._client.create_collection(
            name=coll_name,
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )

        ids, documents, metadatas = [], [], []
        for i, t in enumerate(tables):
            # Build searchable text: table name (repeated for weight) + all column names/types
            col_text = " ".join(f"{c.name} {c.type}" for c in t.columns)
            doc = f"{t.name} {t.name} {col_text}"
            ids.append(str(i))
            documents.append(doc)
            metadatas.append({"idx": i, "name": t.name})

        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    # ── Retrieval ─────────────────────────────────────────────────────

    def retrieve(self, question: str, n: Optional[int] = None) -> list[TableInfo]:
        """Return the tables relevant to *question*, expanded with explicit FK neighbors.

        Expansion uses only declared FK relationships — not fuzzy name matching —
        to avoid pulling in unrelated tables through coincidental column name
        overlap.  Total returned tables are capped at 2× the retrieval count.

        Falls back to all tables if the schema is small or the index is absent.
        """
        if not self._tables:
            return []

        total = len(self._tables)
        if total <= self.THRESHOLD or self._collection is None:
            return self._tables  # small schema — use all

        n_fetch = min(n or self.DEFAULT_N, total)
        results = self._collection.query(query_texts=[question], n_results=n_fetch)

        retrieved_names: set[str] = {m["name"] for m in results["metadatas"][0]}

        # Expand with explicit FK neighbors only (one hop, capped)
        max_tables = min(n_fetch * 2, total)
        expanded: set[str] = set(retrieved_names)
        for name in list(retrieved_names):          # iterate initial set only
            for neighbor in self._join_neighbors.get(name, set()):
                if len(expanded) >= max_tables:
                    break
                expanded.add(neighbor)

        # Return in original schema order
        return [t for t in self._tables if t.name in expanded]

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _build_explicit_neighbors(tables: list[TableInfo]) -> dict[str, set[str]]:
        """Build table-name → {directly FK-joined table names} from declared FKs only.

        Fuzzy name matching is intentionally excluded here — it's used by
        schema.get_join_map() for join-hint generation but is too aggressive
        for retrieval expansion (unrelated tables share column name roots and
        would pull each other in transitively).
        """
        neighbors: dict[str, set[str]] = {t.name: set() for t in tables}
        known = set(neighbors)

        for t in tables:
            for c in t.columns:
                if c.foreign_key:
                    parts = c.foreign_key.split(".")
                    ref = parts[-2] if len(parts) >= 2 else None
                    if ref and ref in known:
                        neighbors[t.name].add(ref)
                        neighbors[ref].add(t.name)

        return neighbors

    @property
    def active(self) -> bool:
        """True if the index is built and retrieval is in effect."""
        return self._collection is not None and len(self._tables) > self.THRESHOLD
