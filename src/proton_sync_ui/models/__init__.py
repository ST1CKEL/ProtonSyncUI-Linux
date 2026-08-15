"""Datenmodelle ohne Abhaengigkeit zu Speicher, CLI oder Oberflaeche."""

from __future__ import annotations

from .plan import PlanAction, PlanItem, SyncPlan, UploadPlan
from .run import FileError, PairStatus, RunRecord, RunStatus
from .sync_pair import (
    ScheduleKind,
    SyncMode,
    SyncPair,
    ValidationError,
    sync_mode_label,
    validate_remote_path,
)

__all__ = [
    "FileError",
    "PairStatus",
    "PlanAction",
    "PlanItem",
    "RunRecord",
    "RunStatus",
    "ScheduleKind",
    "SyncMode",
    "SyncPair",
    "SyncPlan",
    "UploadPlan",
    "ValidationError",
    "sync_mode_label",
    "validate_remote_path",
]
