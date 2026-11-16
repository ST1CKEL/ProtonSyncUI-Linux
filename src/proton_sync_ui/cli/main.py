"""Kommandozeilen-Schnittstelle von ProtonSyncUI.

Diese Schnittstelle wird von den systemd-Units aufgerufen. Sie kommt ohne
grafische Sitzung aus und laedt GTK nicht -- ``proton-sync-ui gui`` ist die
einzige Ausnahme.

Beendigungscodes:

===  ==========================================================
  0  Erfolg
  1  Warnung -- der Lauf ist gelaufen, einzelne Dateien fehlten
  2  Fehler -- nichts uebertragen (CLI fehlt, nicht angemeldet, ...)
  3  Fuer dieses Sync-Paar laeuft bereits ein Durchgang
 64  Falsche Verwendung
===  ==========================================================

``SuccessExitStatus=0 1`` in der Service-Unit sorgt dafuer, dass ein Lauf mit
einzelnen Dateifehlern nicht als fehlgeschlagene Unit gilt.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from collections.abc import Coroutine, Sequence
from datetime import datetime
from typing import Any, Final

from .. import APP_TITLE, __version__, autostart, cli_update, i18n, paths, update
from ..cli_adapter import capabilities
from ..cli_adapter.adapter import ProtonDriveAdapter
from ..logging_setup import configure_logging, get_logger
from ..models.plan import UploadPlan, action_label
from ..models.run import RunRecord, RunStatus, pair_status_from_run, pair_status_label
from ..models.sync_pair import (
    DEFAULT_REMOTE_ROOT,
    ScheduleKind,
    SyncMode,
    SyncPair,
    ValidationError,
    sync_mode_label,
)
from ..storage.database import connect
from ..storage.locking import PairLockedError, is_locked
from ..storage.repository import Repository
from ..sync.engine import SyncEngine, SyncProgress
from ..systemd.manager import SystemdManager, SystemdUnavailableError

log = get_logger("cli")

EXIT_OK: Final = 0
EXIT_WARNING: Final = 1
EXIT_ERROR: Final = 2
EXIT_LOCKED: Final = 3
EXIT_USAGE: Final = 64


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _open_repository() -> Repository:
    """Oeffnet die Datenbank und legt fehlende Verzeichnisse an."""
    paths.ensure_directories()
    return Repository(connect())


def resolve_pair(repository: Repository, token: str) -> SyncPair:
    """Findet ein Sync-Paar anhand UUID, UUID-Anfang oder Anzeigename."""
    exact = repository.get_pair(token)
    if exact is not None:
        return exact

    pairs = repository.list_pairs()
    lowered = token.lower()

    by_prefix = [pair for pair in pairs if pair.uid.lower().startswith(lowered)]
    if len(by_prefix) == 1:
        return by_prefix[0]
    if len(by_prefix) > 1:
        raise SystemExit(
            f"Die Kennung '{token}' ist mehrdeutig. Passende Paare:\n"
            + "\n".join(f"  {pair.uid}  {pair.name}" for pair in by_prefix)
        )

    by_name = [pair for pair in pairs if pair.name.lower() == lowered]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        raise SystemExit(
            f"Mehrere Sync-Paare heissen '{token}'. Bitte die UUID angeben:\n"
            + "\n".join(f"  {pair.uid}  {pair.name}" for pair in by_name)
        )

    raise SystemExit(
        f"Kein Sync-Paar mit der Kennung '{token}' gefunden. "
        "Verfuegbare Paare zeigt 'proton-sync-ui list'."
    )


def _format_timestamp(value: datetime | None) -> str:
    """Formatiert einen Zeitstempel in lokaler Zeit."""
    if value is None:
        return "nie"
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _format_size(num_bytes: int) -> str:
    """Formatiert eine Byte-Anzahl kompakt."""
    value = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"  # pragma: no cover


class _ProgressPrinter:
    """Schreibt Fortschritt zeilenweise -- journal-tauglich, ohne Steuerzeichen."""

    def __init__(self, *, quiet: bool) -> None:
        self._quiet = quiet
        self._last_phase = ""

    def __call__(self, progress: SyncProgress) -> None:
        if self._quiet:
            return
        if progress.relative_path:
            print(f"  [{progress.current + 1}/{progress.total}] {progress.relative_path}")
        elif progress.message and progress.message != self._last_phase:
            self._last_phase = progress.message
            print(f"  {progress.message}")


def _print_run_result(record: RunRecord, *, dry_run: bool) -> None:
    """Gibt das Ergebnis eines Laufs aus."""
    print()
    print(record.summary_line())
    if record.downloaded_bytes:
        print(f"Heruntergeladenes Volumen: {_format_size(record.downloaded_bytes)}")
    if record.uploaded_bytes:
        print(f"Hochgeladenes Volumen: {_format_size(record.uploaded_bytes)}")
    if record.local_deletions:
        print(
            f"Hinweis: {record.local_deletions} lokal geloeschte Datei(en). "
            "Die Kopien bei Proton Drive bleiben bestehen -- "
            "ProtonSyncUI loescht niemals entfernte Dateien."
        )
    if record.message and record.status is RunStatus.ERROR:
        print(f"\nFehler: {record.message}")
    if record.errors:
        print(f"\nFehlgeschlagene Dateien ({len(record.errors)}):")
        for error in record.errors:
            kind = "dauerhaft" if error.permanent else "voruebergehend"
            print(f"  - {error.relative_path}  ({kind}, {error.attempts} Versuch(e))")
            print(f"      {error.message}")
    if dry_run:
        print("\nEs wurde nichts uebertragen (Dry-Run).")


# ---------------------------------------------------------------------------
# Kommandos
# ---------------------------------------------------------------------------


async def _run_cancellable[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Fuehrt ``coroutine`` aus und bricht sie bei SIGTERM geordnet ab.

    Ohne das beendet systemd den Prozess beim Abmelden hart; der Lauf bliebe
    in der Historie fuer immer auf "laeuft" stehen.
    """
    task = asyncio.ensure_future(coroutine)
    loop = asyncio.get_running_loop()
    with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
    return await task


def cmd_sync(args: argparse.Namespace, *, dry_run: bool) -> int:
    """Fuehrt einen Lauf oder Dry-Run aus."""
    repository = _open_repository()
    try:
        pair = resolve_pair(repository, args.uid)

        if not pair.enabled and not args.force:
            print(
                f"Das Sync-Paar '{pair.name}' ist deaktiviert. Mit --force trotzdem ausfuehren.",
                file=sys.stderr,
            )
            return EXIT_ERROR

        kind = "Dry-Run" if dry_run else "Lauf"
        if pair.sync_mode is SyncMode.BIDIRECTIONAL:
            arrow = "⇄"
        elif pair.sync_mode is SyncMode.UPLOAD_ONLY:
            arrow = "→"
        else:
            arrow = "←"
        print(f"{kind} fuer '{pair.name}' ({sync_mode_label(pair.sync_mode)})")
        print(f"  {pair.local_path}  {arrow}  {pair.remote_path}")
        print()

        engine = SyncEngine(
            repository,
            ProtonDriveAdapter(),
            progress=_ProgressPrinter(quiet=args.quiet),
            source="systemd" if args.from_systemd else "cli",
        )

        runner = engine.dry_run(pair) if dry_run else engine.sync(pair)
        try:
            record, plan = asyncio.run(_run_cancellable(runner))
        except asyncio.CancelledError:
            # SIGTERM (Abmeldung, Herunterfahren, "systemctl stop"): Der Lauf
            # ist bereits als abgebrochen verbucht.
            print("\nAbgebrochen.", file=sys.stderr)
            return EXIT_ERROR

        if dry_run:
            _print_plan(plan)

        _print_run_result(record, dry_run=dry_run)

        match record.status:
            case RunStatus.SUCCESS:
                return EXIT_OK
            case RunStatus.WARNING:
                return EXIT_WARNING
            case _:
                return EXIT_ERROR

    except PairLockedError as error:
        print(str(error), file=sys.stderr)
        return EXIT_LOCKED
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        return EXIT_ERROR
    finally:
        repository.close()


def _print_plan(plan: UploadPlan) -> None:
    """Gibt die Bestandteile eines Plans aus."""
    print(f"Plan: {plan.describe()}")
    if plan.downloads:
        print("\nHerunterzuladen (Cloud ➔ Lokal):")
        for item in plan.downloads:
            print(
                f"  {action_label(item.action):<15} {item.posix_path}  "
                f"({_format_size(item.size_bytes)})"
            )
        print(f"Download-Volumen: {_format_size(plan.total_download_bytes)}")

    if plan.uploads:
        print("\nHochzuladen (Lokal ➔ Cloud):")
        for item in plan.uploads:
            print(
                f"  {action_label(item.action):<15} {item.posix_path}  "
                f"({_format_size(item.size_bytes)})"
            )
        print(f"Upload-Volumen: {_format_size(plan.total_upload_bytes)}")

    if not plan.downloads and not plan.uploads:
        print("\nNichts zu uebertragen -- alles auf dem aktuellen Stand.")

    if plan.local_deletions:
        print("\nLokal geloescht (bleibt bei Proton Drive erhalten):")
        for item in plan.local_deletions:
            print(f"  {item.posix_path}")

    if plan.scan_errors:
        print("\nHinweise beim Lesen des Ordners:")
        for warning in plan.scan_errors:
            print(f"  {warning}")


def cmd_status(args: argparse.Namespace) -> int:
    """Zeigt den Zustand aller Sync-Paare."""
    repository = _open_repository()
    try:
        pairs = repository.list_pairs()
        if args.uid:
            pairs = [resolve_pair(repository, args.uid)]

        if not pairs:
            print("Es ist noch kein Sync-Paar eingerichtet.")
            print("Anlegen mit der Oberflaeche (proton-sync-ui gui) oder 'proton-sync-ui add'.")
            return EXIT_OK

        caps = asyncio.run(capabilities.probe(ProtonDriveAdapter()))
        print(f"{APP_TITLE} {__version__} -- {caps.describe()}")
        if caps.problem:
            print(f"  ! {caps.problem.splitlines()[0]}")
        print()

        last_runs = repository.last_runs()
        manager = SystemdManager()
        systemd_ok = manager.available
        worst = EXIT_OK

        for pair in pairs:
            record = last_runs.get(pair.uid)
            status = pair_status_from_run(record.status if record else None, enabled=pair.enabled)
            running = is_locked(repository.connection, pair.uid)
            label = "Laeuft" if running else pair_status_label(status)

            print(f"{pair.name}")
            print(f"  UUID:        {pair.uid}")
            print(f"  Modus:       {sync_mode_label(pair.sync_mode)}")
            print(f"  Status:      {label}")
            print(f"  Quelle:      {pair.local_path}")
            print(f"  Ziel:        {pair.remote_path}")

            if pair.schedule_kind is ScheduleKind.INTERVAL and pair.interval_minutes:
                schedule = f"alle {pair.interval_minutes} Minuten"
            else:
                schedule = "manuell"
            print(f"  Zeitplan:    {schedule}")

            if systemd_ok:
                with contextlib.suppress(SystemdUnavailableError):
                    print(f"  Timer:       {manager.timer_status(pair.uid).describe()}")

            if record is not None:
                print(f"  Letzter Lauf: {_format_timestamp(record.started_at)}")
                parts = [f"geplant {record.planned_files}"]
                if record.downloaded_files > 0:
                    parts.append(f"heruntergeladen {record.downloaded_files}")
                if record.uploaded_files > 0 or record.downloaded_files == 0:
                    parts.append(f"hochgeladen {record.uploaded_files}")
                parts.append(f"fehlgeschlagen {record.failed_files}")
                parts.append(f"uebersprungen {record.skipped_files}")
                print(f"  Dateien:     {', '.join(parts)}")
                if record.message:
                    print(f"  Meldung:     {record.message}")
                if record.status is RunStatus.WARNING:
                    worst = max(worst, EXIT_WARNING)
                elif record.status is RunStatus.ERROR:
                    worst = EXIT_ERROR
            else:
                print("  Letzter Lauf: nie")
            print()

        return worst
    finally:
        repository.close()


def cmd_list(args: argparse.Namespace) -> int:
    """Listet alle Sync-Paare kompakt."""
    repository = _open_repository()
    try:
        pairs = repository.list_pairs()
        if not pairs:
            print("Es ist noch kein Sync-Paar eingerichtet.")
            return EXIT_OK
        for pair in pairs:
            marker = " " if pair.enabled else "-"
            print(f"{marker} {pair.uid}  {pair.name}  [{sync_mode_label(pair.sync_mode)}]")
            if args.verbose:
                print(f"    {pair.local_path}  <->  {pair.remote_path}")
        return EXIT_OK
    finally:
        repository.close()


def cmd_add(args: argparse.Namespace) -> int:
    """Legt ein Sync-Paar ohne grafische Oberflaeche an."""
    repository = _open_repository()
    try:
        schedule = ScheduleKind.INTERVAL if args.interval is not None else ScheduleKind.MANUAL
        patterns = tuple(args.exclude or ())
        mode = SyncMode(args.mode) if getattr(args, "mode", None) else SyncMode.BIDIRECTIONAL
        try:
            pair = SyncPair.create(
                name=args.name,
                local_path=args.local,
                remote_path=args.remote,
                sync_mode=mode,
                schedule_kind=schedule,
                interval_minutes=args.interval,
                exclude_patterns=patterns,
                max_file_size_bytes=args.max_size,
                enabled=not args.disabled,
            )
        except ValidationError as error:
            print(f"Ungueltige Eingabe: {error}", file=sys.stderr)
            return EXIT_USAGE

        repository.save_pair(pair)
        print(f"Sync-Paar angelegt: {pair.uid}")
        print(f"  Modus:  {sync_mode_label(pair.sync_mode)}")
        print(f"  Pfade:  {pair.local_path}  ->  {pair.remote_path}")

        if pair.is_scheduled:
            _apply_systemd(repository)
            print("  Timer eingerichtet.")
        print("\nEmpfehlung: zuerst einen Dry-Run ausfuehren:")
        print(f"  proton-sync-ui dry-run {pair.uid}")
        return EXIT_OK
    finally:
        repository.close()


def cmd_remove(args: argparse.Namespace) -> int:
    """Entfernt ein Sync-Paar aus der lokalen Konfiguration."""
    repository = _open_repository()
    try:
        pair = resolve_pair(repository, args.uid)
        if not args.yes:
            print(f"Sync-Paar '{pair.name}' ({pair.uid}) wirklich entfernen?")
            print("Dies loescht nur die lokale Konfiguration und Historie.")
            print("Dateien bei Proton Drive bleiben unveraendert bestehen.")
            answer = input("Zum Bestaetigen 'ja' eingeben: ").strip().lower()
            if answer not in ("ja", "j", "yes", "y"):
                print("Abgebrochen.")
                return EXIT_OK

        manager = SystemdManager()
        if manager.timer_exists(pair.uid):
            manager.remove_timer(pair.uid)
        repository.delete_pair(pair.uid)
        print(f"Sync-Paar '{pair.name}' entfernt. Proton Drive wurde nicht veraendert.")
        return EXIT_OK
    finally:
        repository.close()


def cmd_enable(args: argparse.Namespace, *, enabled: bool) -> int:
    """Aktiviert oder deaktiviert ein Sync-Paar."""
    repository = _open_repository()
    try:
        pair = resolve_pair(repository, args.uid)
        repository.set_pair_enabled(pair.uid, enabled=enabled)
        _apply_systemd(repository)
        state = "aktiviert" if enabled else "deaktiviert"
        print(f"Sync-Paar '{pair.name}' {state}.")
        return EXIT_OK
    finally:
        repository.close()


def _apply_systemd(repository: Repository) -> dict[str, str]:
    """Bringt die systemd-Units mit der Konfiguration in Einklang."""
    manager = SystemdManager()
    return manager.sync_pairs(repository.list_pairs())


def cmd_systemd(args: argparse.Namespace) -> int:
    """Verwaltet die systemd-Units."""
    repository = _open_repository()
    try:
        manager = SystemdManager()

        if args.systemd_action == "status":
            print(f"Unit-Verzeichnis: {manager.unit_dir}")
            print(f"systemctl verfuegbar: {'ja' if manager.available else 'nein'}")
            timers = manager.list_managed_timers()
            if not timers:
                print("Keine Timer eingerichtet.")
                return EXIT_OK
            for uid in timers:
                pair = repository.get_pair(uid)
                name = pair.name if pair else "(unbekanntes Paar)"
                print(f"  {uid}  {name}  -- {manager.timer_status(uid).describe()}")
            return EXIT_OK

        if args.systemd_action == "remove":
            removed = manager.remove_all()
            if removed:
                print("Entfernt:")
                for unit in removed:
                    print(f"  {unit}")
            else:
                print("Es waren keine Units eingerichtet.")
            return EXIT_OK

        # "sync" -- Standardfall
        try:
            actions = _apply_systemd(repository)
        except SystemdUnavailableError as error:
            print(str(error), file=sys.stderr)
            return EXIT_ERROR

        if not actions:
            print("Keine Aenderungen -- es gibt kein Paar mit Intervall-Zeitplan.")
        else:
            for uid, action in actions.items():
                pair = repository.get_pair(uid)
                name = pair.name if pair else uid
                print(f"  {name}: {action}")
        print(f"\nUnits liegen in: {manager.unit_dir}")
        return EXIT_OK
    finally:
        repository.close()


def cmd_doctor(args: argparse.Namespace) -> int:
    """Prueft die Umgebung und meldet konkrete Probleme."""
    print(f"{APP_TITLE} {__version__}")
    print(f"  Konfiguration: {paths.config_dir()}")
    print(f"  Datenbank:     {paths.database_path()}")
    print(f"  Logs:          {paths.log_dir()}")
    print()

    adapter = ProtonDriveAdapter()
    caps = asyncio.run(capabilities.probe(adapter, check_auth=not args.offline))

    if not caps.available:
        print("[FEHLER] proton-drive nicht gefunden.")
        print(caps.problem)
        return EXIT_ERROR

    print(f"[OK] proton-drive gefunden: {caps.binary_path}")
    if caps.cli_version:
        print(f"     CLI-Version: {caps.cli_version}")
    if caps.sdk_version:
        print(f"     SDK-Version: {caps.sdk_version}")
    if caps.cli_version and caps.cli_version not in capabilities.VERIFIED_CLI_VERSIONS:
        print(
            f"     Hinweis: Der Adapter wurde gegen {capabilities.VERIFIED_CLI_VERSION} "
            "geprueft. Bei Syntaxfehlern bitte "
            "proton_sync_ui/cli_adapter/commands.py anpassen."
        )

    if args.offline:
        print("[--] Anmeldezustand nicht geprueft (--offline).")
    elif caps.authenticated:
        print("[OK] Die CLI ist angemeldet.")
    else:
        print("[FEHLER] Die CLI ist nicht angemeldet.")
        print(caps.problem)
        return EXIT_ERROR

    manager = SystemdManager()
    if manager.available:
        print(f"[OK] systemctl verfuegbar, Units in {manager.unit_dir}")
    else:
        print("[WARN] systemctl nicht verfuegbar -- Zeitplanung nicht moeglich.")

    repository = _open_repository()
    try:
        pairs = repository.list_pairs()
        print(f"[OK] Datenbank lesbar, {len(pairs)} Sync-Paar(e) konfiguriert.")
        for pair in pairs:
            if not pair.local_path.is_dir():
                print(f"[WARN] Quellordner fehlt: {pair.local_path} ({pair.name})")
    finally:
        repository.close()

    return EXIT_OK


def cmd_update(args: argparse.Namespace) -> int:
    """Sucht nach einer neuen Version und installiert sie."""
    try:
        info = update.check_for_update()
    except update.UpdateError as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR

    print(f"Installiert: {info.current_version}")
    print(f"Verfuegbar:  {info.latest_version}")
    if not info.available and not args.force:
        print("ProtonSyncUI ist aktuell.")
        return EXIT_OK
    if args.check:
        print("Ein Update ist verfuegbar. Installieren mit: proton-sync-ui update")
        return EXIT_WARNING

    try:
        update.install_update(info, progress=print)
    except update.UpdateError as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    print("Bitte ProtonSyncUI neu starten, damit die neue Version aktiv wird.")
    return EXIT_OK


def cmd_cli_update(args: argparse.Namespace) -> int:
    """Installiert oder aktualisiert die offizielle Proton-Drive-CLI."""
    adapter = ProtonDriveAdapter()
    try:
        current_binary: str | None = adapter.resolve_binary()
    except capabilities.ProtonCliNotFoundError:
        current_binary = None
    current_version = cli_update.installed_version(current_binary) if current_binary else ""

    try:
        release = cli_update.fetch_release()
    except cli_update.CliUpdateError as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR

    print(f"Installiert: {current_version or '--'}")
    print(f"Verfuegbar:  {release.version} ({release.platform})")
    if not cli_update.is_update_available(release, current_version) and not args.force:
        print("Die Proton-Drive-CLI ist aktuell.")
        return EXIT_OK
    if args.check:
        print("Aktualisieren mit: proton-sync-ui cli-update")
        return EXIT_WARNING

    repository = _open_repository()
    try:
        if any(is_locked(repository.connection, pair.uid) for pair in repository.list_pairs()):
            print(
                "Es laeuft gerade ein Sync-Lauf. Bitte nach dessen Ende erneut versuchen.",
                file=sys.stderr,
            )
            return EXIT_LOCKED
    finally:
        repository.close()

    try:
        cli_update.install_release(release, cli_update.target_path(current_binary), progress=print)
    except cli_update.CliUpdateError as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def cmd_autostart(args: argparse.Namespace) -> int:
    """Schaltet den Start bei der Anmeldung."""
    match args.autostart_action:
        case "on":
            path = autostart.enable(minimized=not args.window)
            print(f"Autostart aktiviert: {path}")
        case "off":
            removed = autostart.disable()
            print("Autostart deaktiviert." if removed else "Autostart war nicht aktiv.")
        case "refresh":
            refreshed = autostart.refresh()
            print("Autostart-Eintrag aktualisiert." if refreshed else "Autostart ist nicht aktiv.")
        case _:
            if autostart.is_enabled():
                mode = "minimiert" if autostart.is_minimized() else "mit Fenster"
                print(f"Autostart ist aktiv ({mode}): {autostart.autostart_file()}")
            else:
                print("Autostart ist nicht aktiv.")
    with contextlib.suppress(Exception):
        SystemdManager().daemon_reload()
    return EXIT_OK


def cmd_gui(_args: argparse.Namespace) -> int:
    """Startet die grafische Oberflaeche.

    GTK wird bewusst erst hier importiert: alle uebrigen Kommandos sollen
    ohne grafische Sitzung und ohne PyGObject auskommen.
    """
    try:
        from ..ui.application import main as gui_main  # noqa: PLC0415 -- s. o.
    except ImportError as error:
        print(
            "Die grafische Oberflaeche benoetigt PyGObject mit GTK4 und libadwaita.\n"
            "Auf Fedora installieren mit:\n\n"
            "    sudo dnf install python3-gobject gtk4 libadwaita\n\n"
            f"Ursache: {error}",
            file=sys.stderr,
        )
        return EXIT_ERROR
    return gui_main(argv=[])


# ---------------------------------------------------------------------------
# Argumentparser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Baut den vollstaendigen Argumentparser."""
    parser = argparse.ArgumentParser(
        prog="proton-sync-ui",
        description=(
            "Einseitige Backup-Uploads zu Proton Drive ueber die offizielle "
            "proton-drive-Kommandozeile. Entfernte Dateien werden niemals geloescht."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Voraussetzung: die offizielle Proton-Drive-CLI muss installiert und "
            "einmalig mit 'proton-drive auth login' angemeldet sein.\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"{APP_TITLE} {__version__}")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="ausfuehrliche Protokollausgabe"
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Fortschritt nicht ausgeben")

    sub = parser.add_subparsers(dest="command", metavar="KOMMANDO")

    sync_parser = sub.add_parser("sync", help="einen Sync-Lauf ausfuehren")
    sync_parser.add_argument("uid", metavar="UUID", help="UUID oder Name des Sync-Paars")
    sync_parser.add_argument(
        "--force", action="store_true", help="auch deaktivierte Paare ausfuehren"
    )
    sync_parser.add_argument("--from-systemd", action="store_true", help=argparse.SUPPRESS)

    dry_parser = sub.add_parser("dry-run", help="Plan anzeigen, ohne zu uebertragen")
    dry_parser.add_argument("uid", metavar="UUID", help="UUID oder Name des Sync-Paars")
    dry_parser.add_argument("--force", action="store_true", help="auch deaktivierte Paare pruefen")
    dry_parser.add_argument("--from-systemd", action="store_true", help=argparse.SUPPRESS)

    status_parser = sub.add_parser("status", help="Zustand aller Sync-Paare zeigen")
    status_parser.add_argument("uid", metavar="UUID", nargs="?", help="nur dieses Sync-Paar zeigen")

    list_parser = sub.add_parser("list", help="Sync-Paare auflisten")
    list_parser.add_argument("-l", "--verbose", action="store_true", help="Pfade mit anzeigen")

    add_parser = sub.add_parser("add", help="Sync-Paar anlegen")
    add_parser.add_argument("--name", required=True, help="Anzeigename")
    add_parser.add_argument("--local", required=True, help="lokaler Quellordner")
    add_parser.add_argument(
        "--remote",
        required=True,
        help=f"Proton-Drive-Zielpfad, z. B. {DEFAULT_REMOTE_ROOT}/Backup",
    )
    add_parser.add_argument(
        "--mode",
        choices=("bidirectional", "upload_only", "download_only"),
        default="bidirectional",
        help="Synchronisationsmodus (Standard: bidirectional)",
    )
    add_parser.add_argument(
        "--interval", type=int, metavar="MINUTEN", help="Zeitplan: alle X Minuten"
    )
    add_parser.add_argument(
        "--exclude", action="append", metavar="MUSTER", help="Ausschlussregel (mehrfach moeglich)"
    )
    add_parser.add_argument("--max-size", type=int, metavar="BYTES", help="Groessenlimit pro Datei")
    add_parser.add_argument("--disabled", action="store_true", help="deaktiviert anlegen")

    remove_parser = sub.add_parser("remove", help="Sync-Paar entfernen (nur lokal)")
    remove_parser.add_argument("uid", metavar="UUID")
    remove_parser.add_argument("-y", "--yes", action="store_true", help="nicht nachfragen")

    enable_parser = sub.add_parser("enable", help="Sync-Paar aktivieren")
    enable_parser.add_argument("uid", metavar="UUID")

    disable_parser = sub.add_parser("disable", help="Sync-Paar deaktivieren")
    disable_parser.add_argument("uid", metavar="UUID")

    systemd_parser = sub.add_parser("systemd", help="systemd-Timer verwalten")
    systemd_parser.add_argument(
        "systemd_action",
        choices=("sync", "status", "remove"),
        nargs="?",
        default="sync",
        metavar="AKTION",
        help="sync (Standard), status oder remove",
    )

    doctor_parser = sub.add_parser("doctor", help="Umgebung pruefen")
    doctor_parser.add_argument(
        "--offline", action="store_true", help="Anmeldezustand nicht pruefen"
    )

    update_parser = sub.add_parser("update", help="nach Updates suchen und installieren")
    update_parser.add_argument(
        "--check", action="store_true", help="nur pruefen, nichts installieren"
    )
    update_parser.add_argument(
        "--force", action="store_true", help="auch ohne neuere Version neu installieren"
    )

    cli_parser = sub.add_parser(
        "cli-update", help="Proton-Drive-CLI installieren oder aktualisieren"
    )
    cli_parser.add_argument("--check", action="store_true", help="nur pruefen")
    cli_parser.add_argument("--force", action="store_true", help="auch ohne neuere Version")

    autostart_parser = sub.add_parser("autostart", help="Start bei der Anmeldung schalten")
    autostart_parser.add_argument(
        "autostart_action",
        choices=("on", "off", "status", "refresh"),
        nargs="?",
        default="status",
        metavar="AKTION",
        help="on, off, status (Standard) oder refresh",
    )
    autostart_parser.add_argument(
        "--window", action="store_true", help="mit sichtbarem Fenster statt minimiert starten"
    )

    sub.add_parser("gui", help="grafische Oberflaeche starten")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Einstiegspunkt der Kommandozeile."""
    i18n.init()
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(level=logging.DEBUG if args.verbose else logging.INFO, console=args.verbose)

    if args.command is None:
        parser.print_help()
        return EXIT_USAGE

    try:
        match args.command:
            case "sync":
                return cmd_sync(args, dry_run=False)
            case "dry-run":
                return cmd_sync(args, dry_run=True)
            case "status":
                return cmd_status(args)
            case "list":
                return cmd_list(args)
            case "add":
                return cmd_add(args)
            case "remove":
                return cmd_remove(args)
            case "enable":
                return cmd_enable(args, enabled=True)
            case "disable":
                return cmd_enable(args, enabled=False)
            case "systemd":
                return cmd_systemd(args)
            case "doctor":
                return cmd_doctor(args)
            case "update":
                return cmd_update(args)
            case "cli-update":
                return cmd_cli_update(args)
            case "autostart":
                return cmd_autostart(args)
            case "gui":
                return cmd_gui(args)
            case _:  # pragma: no cover -- argparse verhindert das
                parser.print_help()
                return EXIT_USAGE
    except SystemExit as error:
        if isinstance(error.code, str):
            print(error.code, file=sys.stderr)
            return EXIT_USAGE
        return error.code if isinstance(error.code, int) else EXIT_ERROR
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        return EXIT_ERROR
    except Exception as error:
        log.exception("Unerwarteter Fehler")
        print(f"Unerwarteter Fehler: {error}", file=sys.stderr)
        print(f"Einzelheiten stehen im Protokoll: {paths.log_file()}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
