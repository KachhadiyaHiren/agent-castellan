"""Hash-chained audit log (WS4)."""

from .log import GENESIS_HASH, AuditLog
from .read import iter_entries, tail_entries
from .verify import VerifyResult, verify_log

__all__ = [
    "GENESIS_HASH",
    "AuditLog",
    "VerifyResult",
    "iter_entries",
    "tail_entries",
    "verify_log",
]
