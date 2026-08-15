"""Ansichten fuer ProtonSyncUI."""

from __future__ import annotations

from .activity_view import ActivityView
from .conflicts_view import ConflictsView
from .diag_view import DiagnosticsView
from .overview_view import OverviewView
from .pairs_view import SyncPairsView
from .settings_view import SettingsView

__all__ = [
    "ActivityView",
    "ConflictsView",
    "DiagnosticsView",
    "OverviewView",
    "SettingsView",
    "SyncPairsView",
]
