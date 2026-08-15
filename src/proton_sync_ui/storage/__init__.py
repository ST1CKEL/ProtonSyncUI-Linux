"""Persistenz: SQLite-Schema, Repository und Lauf-Sperren."""

from __future__ import annotations

from .database import SCHEMA_VERSION, connect, initialize, transaction
from .locking import LockInfo, PairLockedError, acquire, is_locked, release, run_lock
from .repository import FileState, Repository

__all__ = [
    "SCHEMA_VERSION",
    "FileState",
    "LockInfo",
    "PairLockedError",
    "Repository",
    "acquire",
    "connect",
    "initialize",
    "is_locked",
    "release",
    "run_lock",
    "transaction",
]
