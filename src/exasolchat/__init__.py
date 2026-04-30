"""ExasolChat — safe text-to-SQL for ExasolDB and DuckDB with local LLMs."""

from exasolchat.core import ExasolChat, QueryResult
from exasolchat.connection import ConnectionConfig
from exasolchat.safety import RiskLevel, SafetyVerdict, validate_sql

__all__ = [
    "ExasolChat",
    "QueryResult",
    "ConnectionConfig",
    "RiskLevel",
    "SafetyVerdict",
    "validate_sql",
]
