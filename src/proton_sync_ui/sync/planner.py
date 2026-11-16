"""Erzeugung des Sync-Plans.

Der Planer vergleicht den lokalen Befund, den entfernten Befund bei Proton Drive
und den gespeicherten Zustand des letzten erfolgreichen Laufs (3-Wege-Abgleich).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath

from ..logging_setup import get_logger
from ..models.plan import PlanAction, PlanItem, SyncPlan, UploadPlan
from ..models.sync_pair import SyncMode, SyncPair
from ..storage.repository import FileState
from .ignore import IgnoreMatcher
from .remote_scanner import RemoteScannedFile, RemoteScanResult
from .scanner import ScannedFile, ScanResult, compute_sha256, scan_directory

log = get_logger("sync.planner")

Hasher = Callable[[Path], str]


def build_plan(
    pair: SyncPair,
    local_scan: ScanResult,
    states: Mapping[str, FileState],
    *,
    remote_scan: RemoteScanResult | None = None,
    hasher: Hasher = compute_sha256,
) -> UploadPlan:
    """Erstellt den Sync-Plan aus lokalem/entferntem Scan und DB-Zustand."""
    items: list[PlanItem] = []
    errors = list(local_scan.errors)
    if remote_scan is not None:
        errors.extend(remote_scan.errors)

    # Skips sammeln (doppelte Schluessel vermeiden)
    skip_keys: set[str] = set()
    for skip in local_scan.skips:
        key = skip.relative_path.as_posix()
        skip_keys.add(key)
        items.append(
            PlanItem(
                relative_path=skip.relative_path,
                action=skip.action,
                size_bytes=skip.size_bytes,
                reason=skip.reason,
            )
        )

    if remote_scan is not None:
        for skip in remote_scan.skips:
            key = skip.relative_path.as_posix()
            if key not in skip_keys:
                skip_keys.add(key)
                items.append(
                    PlanItem(
                        relative_path=skip.relative_path,
                        action=skip.action,
                        size_bytes=skip.size_bytes,
                        reason=skip.reason,
                    )
                )

    local_by_key = local_scan.by_key()
    remote_by_key = remote_scan.by_key() if remote_scan is not None else {}

    all_keys = sorted(
        (set(local_by_key.keys()) | set(remote_by_key.keys()) | set(states.keys())) - skip_keys
    )

    mode = pair.sync_mode

    for key in all_keys:
        local = local_by_key.get(key)
        remote = remote_by_key.get(key)
        state = states.get(key)
        rel_path = PurePosixPath(key)

        if (
            remote_scan is not None
            and mode is not SyncMode.UPLOAD_ONLY
            and remote_scan.is_unreadable(key)
        ):
            # Der Cloud-Ordner dieser Datei konnte nicht gelesen werden. Ohne
            # gesicherten Cloud-Stand wird weder uebertragen noch ein Zustand
            # veraendert -- der naechste Lauf entscheidet neu.
            size = local.size_bytes if local else (state.size_bytes if state else 0)
            items.append(
                PlanItem(
                    relative_path=rel_path,
                    action=PlanAction.SKIP_REMOTE_UNKNOWN,
                    size_bytes=size,
                    mtime_ns=local.mtime_ns if local else 0,
                    reason="Cloud-Ordner konnte nicht gelesen werden; Datei wird zurueckgestellt.",
                )
            )
            continue

        if mode is SyncMode.UPLOAD_ONLY or remote_scan is None:
            _plan_upload_only(
                pair,
                rel_path,
                local,
                state,
                items=items,
                errors=errors,
                hasher=hasher,
            )
        elif mode is SyncMode.DOWNLOAD_ONLY:
            _plan_download_only(
                rel_path,
                local,
                remote,
                state,
                items=items,
            )
        else:
            _plan_bidirectional(
                pair,
                rel_path,
                local,
                remote,
                state,
                items=items,
                errors=errors,
                hasher=hasher,
            )

    return UploadPlan.from_items(pair.uid, items, scan_errors=errors)


def _plan_upload_only(
    pair: SyncPair,
    rel_path: PurePosixPath,
    local: ScannedFile | None,
    state: FileState | None,
    *,
    items: list[PlanItem],
    errors: list[str],
    hasher: Hasher,
) -> None:
    if state is not None and state.deleted:
        # Grabstein aus dem 2-Wege-Modus: fuer Einweg-Upload bedeutungslos.
        if local is None:
            items.append(
                PlanItem(
                    relative_path=rel_path,
                    action=PlanAction.LOCAL_DELETED,
                    size_bytes=state.size_bytes,
                    reason="Lokal geloescht (Kopie bei Proton Drive bleibt bestehen).",
                )
            )
            return
        state = None

    if local is None:
        if state is not None:
            items.append(
                PlanItem(
                    relative_path=rel_path,
                    action=PlanAction.LOCAL_DELETED,
                    size_bytes=state.size_bytes,
                    reason="Lokal geloescht (Kopie bei Proton Drive bleibt bestehen).",
                )
            )
        return

    if state is None:
        items.append(
            PlanItem(
                relative_path=rel_path,
                action=PlanAction.UPLOAD_NEW,
                size_bytes=local.size_bytes,
                mtime_ns=local.mtime_ns,
                remote_path=pair.remote_path_for(rel_path),
                reason="Noch nicht hochgeladen.",
            )
        )
        return

    if state.size_bytes != local.size_bytes:
        items.append(
            PlanItem(
                relative_path=rel_path,
                action=PlanAction.UPLOAD_CHANGED,
                size_bytes=local.size_bytes,
                mtime_ns=local.mtime_ns,
                remote_path=pair.remote_path_for(rel_path),
                reason=f"Groesse geaendert: {state.size_bytes} -> {local.size_bytes} Bytes.",
            )
        )
        return

    if state.mtime_ns == local.mtime_ns:
        items.append(
            PlanItem(
                relative_path=rel_path,
                action=PlanAction.SKIP_UNCHANGED,
                size_bytes=local.size_bytes,
                mtime_ns=local.mtime_ns,
                remote_path=pair.remote_path_for(rel_path),
                reason="Unveraendert.",
            )
        )
        return

    items.append(_resolve_ambiguous_local(local, state, hasher=hasher, errors=errors))


def _plan_download_only(
    rel_path: PurePosixPath,
    local: ScannedFile | None,
    remote: RemoteScannedFile | None,
    state: FileState | None,
    *,
    items: list[PlanItem],
) -> None:
    if state is not None and state.deleted:
        # Der Download-Modus spiegelt die Cloud; lokale Loeschungen gelten nicht.
        state = None

    if remote is None:
        if local is not None:
            items.append(
                PlanItem(
                    relative_path=rel_path,
                    action=PlanAction.SKIP_UNCHANGED,
                    size_bytes=local.size_bytes,
                    mtime_ns=local.mtime_ns,
                    reason="Nur lokal vorhanden (Download-Modus).",
                )
            )
        return

    if local is None:
        items.append(
            PlanItem(
                relative_path=rel_path,
                action=PlanAction.DOWNLOAD_NEW,
                size_bytes=remote.size_bytes,
                remote_path=remote.remote_path,
                remote_mtime=remote.modification_time,
                reason="In der Cloud neu vorhanden.",
            )
        )
        return

    if state is None:
        if local.size_bytes == remote.size_bytes:
            items.append(
                PlanItem(
                    relative_path=rel_path,
                    action=PlanAction.SKIP_UNCHANGED,
                    size_bytes=local.size_bytes,
                    mtime_ns=local.mtime_ns,
                    remote_path=remote.remote_path,
                    remote_mtime=remote.modification_time,
                    reason="Beidseitig vorhanden mit gleicher Groesse.",
                    record_initial_state=True,
                )
            )
        else:
            items.append(
                PlanItem(
                    relative_path=rel_path,
                    action=PlanAction.CONFLICT_LOCAL_RENAMED,
                    size_bytes=remote.size_bytes,
                    mtime_ns=local.mtime_ns,
                    remote_path=remote.remote_path,
                    remote_mtime=remote.modification_time,
                    reason=(
                        "Initialer Abgleich mit abweichender Groesse: lokale Fassung wird "
                        "gesichert, Cloud-Fassung uebernommen."
                    ),
                )
            )
        return

    if _remote_changed(state, remote):
        local_changed = local.size_bytes != state.size_bytes or local.mtime_ns != state.mtime_ns
        items.append(
            PlanItem(
                relative_path=rel_path,
                action=(
                    PlanAction.CONFLICT_LOCAL_RENAMED
                    if local_changed
                    else PlanAction.DOWNLOAD_CHANGED
                ),
                size_bytes=remote.size_bytes,
                mtime_ns=local.mtime_ns,
                remote_path=remote.remote_path,
                remote_mtime=remote.modification_time,
                reason=(
                    "In der Cloud und lokal geaendert: lokale Fassung wird gesichert."
                    if local_changed
                    else "In der Cloud geaendert."
                ),
            )
        )
        return

    items.append(
        PlanItem(
            relative_path=rel_path,
            action=PlanAction.SKIP_UNCHANGED,
            size_bytes=local.size_bytes,
            mtime_ns=local.mtime_ns,
            remote_path=remote.remote_path,
            remote_mtime=remote.modification_time,
            reason="Lokal und remote synchron.",
            needs_remote_mtime_refresh=_remote_mtime_missing(state, remote),
        )
    )


def _plan_bidirectional(
    pair: SyncPair,
    rel_path: PurePosixPath,
    local: ScannedFile | None,
    remote: RemoteScannedFile | None,
    state: FileState | None,
    *,
    items: list[PlanItem],
    errors: list[str],
    hasher: Hasher,
) -> None:
    if state is not None and state.deleted and local is not None:
        # Die lokal geloeschte Datei wurde neu angelegt: wie unbekannt behandeln.
        state = None

    # Fall 1: Lokal existiert, Remote existiert NICHT
    if local is not None and remote is None:
        if state is None:
            items.append(
                PlanItem(
                    relative_path=rel_path,
                    action=PlanAction.UPLOAD_NEW,
                    size_bytes=local.size_bytes,
                    mtime_ns=local.mtime_ns,
                    remote_path=pair.remote_path_for(rel_path),
                    reason="Lokal neu angelegt.",
                )
            )
        elif state.size_bytes == local.size_bytes and state.mtime_ns == local.mtime_ns:
            items.append(
                PlanItem(
                    relative_path=rel_path,
                    action=PlanAction.SKIP_UNCHANGED,
                    size_bytes=local.size_bytes,
                    mtime_ns=local.mtime_ns,
                    remote_path=pair.remote_path_for(rel_path),
                    reason="Lokal unveraendert.",
                )
            )
        elif state.size_bytes != local.size_bytes:
            items.append(
                PlanItem(
                    relative_path=rel_path,
                    action=PlanAction.UPLOAD_CHANGED,
                    size_bytes=local.size_bytes,
                    mtime_ns=local.mtime_ns,
                    remote_path=pair.remote_path_for(rel_path),
                    reason=(f"Groesse geaendert: {state.size_bytes} -> {local.size_bytes} Bytes."),
                )
            )
        else:
            items.append(_resolve_ambiguous_local(local, state, hasher=hasher, errors=errors))
        return

    # Fall 2: Remote existiert, Lokal existiert NICHT
    if remote is not None and local is None:
        if state is None:
            items.append(
                PlanItem(
                    relative_path=rel_path,
                    action=PlanAction.DOWNLOAD_NEW,
                    size_bytes=remote.size_bytes,
                    remote_path=remote.remote_path,
                    remote_mtime=remote.modification_time,
                    reason="In der Cloud neu vorhanden.",
                )
            )
        elif state.deleted:
            if _remote_changed(state, remote):
                items.append(
                    PlanItem(
                        relative_path=rel_path,
                        action=PlanAction.DOWNLOAD_NEW,
                        size_bytes=remote.size_bytes,
                        remote_path=remote.remote_path,
                        remote_mtime=remote.modification_time,
                        reason="Nach der lokalen Loeschung in der Cloud geaendert.",
                    )
                )
            else:
                items.append(
                    PlanItem(
                        relative_path=rel_path,
                        action=PlanAction.SKIP_UNCHANGED,
                        size_bytes=remote.size_bytes,
                        remote_path=remote.remote_path,
                        remote_mtime=remote.modification_time,
                        reason="Lokal geloescht; die Cloud-Kopie bleibt erhalten.",
                    )
                )
        else:
            items.append(
                PlanItem(
                    relative_path=rel_path,
                    action=PlanAction.LOCAL_DELETED,
                    size_bytes=remote.size_bytes,
                    remote_path=remote.remote_path,
                    remote_mtime=remote.modification_time,
                    reason="Lokal geloescht (Cloud-Kopie bleibt unberuehrt).",
                    keep_tombstone=True,
                )
            )
        return

    # Fall 3: Weder lokal noch remote vorhanden, aber state existiert
    if local is None and remote is None:
        if state is not None:
            items.append(
                PlanItem(
                    relative_path=rel_path,
                    action=PlanAction.LOCAL_DELETED,
                    size_bytes=state.size_bytes,
                    reason="Datei existiert weder lokal noch remote.",
                )
            )
        return

    # Fall 4: Beide existieren (local is not None AND remote is not None)
    assert local is not None and remote is not None

    if state is None:
        if local.size_bytes == remote.size_bytes:
            items.append(
                PlanItem(
                    relative_path=rel_path,
                    action=PlanAction.SKIP_UNCHANGED,
                    size_bytes=local.size_bytes,
                    mtime_ns=local.mtime_ns,
                    remote_path=remote.remote_path,
                    remote_mtime=remote.modification_time,
                    reason="Beidseitig vorhanden mit gleicher Groesse.",
                    record_initial_state=True,
                )
            )
        else:
            # Ohne gespeicherten Zustand ist unklar, welche Seite neuer ist.
            # Die lokale Fassung wird deshalb gesichert statt ueberschrieben.
            items.append(
                PlanItem(
                    relative_path=rel_path,
                    action=PlanAction.CONFLICT_LOCAL_RENAMED,
                    size_bytes=remote.size_bytes,
                    mtime_ns=local.mtime_ns,
                    remote_path=remote.remote_path,
                    remote_mtime=remote.modification_time,
                    reason=(
                        "Initialer Abgleich mit abweichender Groesse: lokale Fassung wird "
                        "gesichert, Cloud-Fassung uebernommen."
                    ),
                )
            )
        return

    local_size_changed = local.size_bytes != state.size_bytes
    local_mtime_changed = local.mtime_ns != state.mtime_ns
    local_changed = local_size_changed or local_mtime_changed

    remote_changed = _remote_changed(state, remote)

    if not local_changed and not remote_changed:
        items.append(
            PlanItem(
                relative_path=rel_path,
                action=PlanAction.SKIP_UNCHANGED,
                size_bytes=local.size_bytes,
                mtime_ns=local.mtime_ns,
                remote_path=remote.remote_path,
                remote_mtime=remote.modification_time,
                reason="Unveraendert.",
                needs_remote_mtime_refresh=_remote_mtime_missing(state, remote),
            )
        )
        return

    if local_changed and not remote_changed:
        if local_size_changed:
            items.append(
                PlanItem(
                    relative_path=rel_path,
                    action=PlanAction.UPLOAD_CHANGED,
                    size_bytes=local.size_bytes,
                    mtime_ns=local.mtime_ns,
                    remote_path=pair.remote_path_for(rel_path),
                    reason=f"Groesse geaendert: {state.size_bytes} -> {local.size_bytes} Bytes.",
                )
            )
        else:
            items.append(_resolve_ambiguous_local(local, state, hasher=hasher, errors=errors))
        return

    if not local_changed and remote_changed:
        items.append(
            PlanItem(
                relative_path=rel_path,
                action=PlanAction.DOWNLOAD_CHANGED,
                size_bytes=remote.size_bytes,
                remote_path=remote.remote_path,
                remote_mtime=remote.modification_time,
                reason="In der Cloud geaendert.",
            )
        )
        return

    items.append(
        PlanItem(
            relative_path=rel_path,
            action=PlanAction.CONFLICT_LOCAL_RENAMED,
            size_bytes=remote.size_bytes,
            mtime_ns=local.mtime_ns,
            remote_path=remote.remote_path,
            remote_mtime=remote.modification_time,
            reason="Konflikt: Beidseitig geaendert. Lokale Version wird archiviert.",
        )
    )


def _remote_changed(state: FileState, remote: RemoteScannedFile) -> bool:
    """Wahr, wenn sich die Cloud-Fassung seit dem gespeicherten Zustand geaendert hat."""
    if remote.size_bytes != state.size_bytes:
        return True
    return bool(state.remote_mtime and remote.modification_time != state.remote_mtime)


def _remote_mtime_missing(state: FileState | None, remote: RemoteScannedFile) -> bool:
    """Wahr, wenn die entfernte Aenderungszeit nachgetragen werden sollte."""
    return state is not None and not state.remote_mtime and bool(remote.modification_time)


def _resolve_ambiguous_local(
    found: ScannedFile,
    state: FileState,
    *,
    hasher: Hasher,
    errors: list[str],
) -> PlanItem:
    """Entscheidet den Fall 'gleiche Groesse, andere mtime' per Pruefsumme."""
    relative_path = found.relative_path
    absolute_path = found.absolute_path
    size_bytes = found.size_bytes
    mtime_ns = found.mtime_ns

    if state.sha256 is None:
        try:
            digest: str | None = hasher(absolute_path)
        except OSError as error:
            digest = None
            errors.append(f"{relative_path}: Pruefsumme nicht berechenbar ({error}).")
        return PlanItem(
            relative_path=relative_path,
            action=PlanAction.UPLOAD_CHANGED,
            size_bytes=size_bytes,
            mtime_ns=mtime_ns,
            reason="Aenderungszeit abweichend, keine gespeicherte Pruefsumme zum Vergleich.",
            sha256=digest,
        )

    try:
        digest = hasher(absolute_path)
    except OSError as error:
        errors.append(f"{relative_path}: Pruefsumme nicht berechenbar ({error}).")
        return PlanItem(
            relative_path=relative_path,
            action=PlanAction.SKIP_UNREADABLE,
            size_bytes=size_bytes,
            mtime_ns=mtime_ns,
            reason=f"Pruefsumme nicht berechenbar: {error}",
        )

    if digest == state.sha256:
        return PlanItem(
            relative_path=relative_path,
            action=PlanAction.SKIP_UNCHANGED,
            size_bytes=size_bytes,
            mtime_ns=mtime_ns,
            reason="Aenderungszeit abweichend, Inhalt laut Pruefsumme identisch.",
            sha256=digest,
            needs_mtime_refresh=True,
        )

    return PlanItem(
        relative_path=relative_path,
        action=PlanAction.UPLOAD_CHANGED,
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        reason="Inhalt laut Pruefsumme geaendert.",
        sha256=digest,
    )


def plan_for_pair(
    pair: SyncPair,
    states: Mapping[str, FileState],
    *,
    hasher: Hasher = compute_sha256,
) -> UploadPlan:
    """Bequemlichkeitsfunktion: scannt den lokalen Quellordner und erstellt den Plan."""
    matcher = IgnoreMatcher(pair.exclude_patterns)
    scan = scan_directory(
        pair.local_path,
        matcher=matcher,
        max_file_size_bytes=pair.max_file_size_bytes,
    )
    return build_plan(pair, scan, states, hasher=hasher)


__all__ = ["Hasher", "SyncPlan", "build_plan", "plan_for_pair"]
