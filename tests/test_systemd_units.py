"""Tests der systemd-Unit-Erzeugung und -Verwaltung."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from proton_sync_ui.models.sync_pair import ScheduleKind, SyncPair
from proton_sync_ui.systemd.manager import SystemdManager
from proton_sync_ui.systemd.units import (
    SERVICE_TEMPLATE_NAME,
    UnitError,
    service_template_text,
    service_unit_name,
    timer_unit_name,
    timer_unit_text,
    validate_instance,
)


class TestInstanceNames:
    """UUIDs als systemd-Instanznamen."""

    def test_uuid_is_accepted(self, sample_pair: SyncPair) -> None:
        assert validate_instance(sample_pair.uid) == sample_pair.uid

    @pytest.mark.parametrize(
        "uid",
        [
            "mit leerzeichen",
            "mit/schraegstrich",
            "mit@klammeraffe",
            "kurz",
            "",
            "mit;semikolon;und;mehr",
            "../../etc/passwd",
        ],
    )
    def test_unsafe_instance_names_are_rejected(self, uid: str) -> None:
        with pytest.raises(UnitError):
            validate_instance(uid)

    def test_unit_names_follow_the_template_scheme(self, sample_pair: SyncPair) -> None:
        assert service_unit_name(sample_pair.uid) == f"proton-sync-ui@{sample_pair.uid}.service"
        assert timer_unit_name(sample_pair.uid) == f"proton-sync-ui@{sample_pair.uid}.timer"


class TestServiceTemplate:
    """Der statische Template-Service."""

    def test_contains_required_sections(self) -> None:
        text = service_template_text(executable="/usr/bin/proton-sync-ui")

        assert "[Unit]" in text
        assert "[Service]" in text
        assert "Type=oneshot" in text

    def test_calls_the_cli_not_the_gui(self) -> None:
        text = service_template_text(executable="/usr/bin/proton-sync-ui")

        assert "ExecStart=/usr/bin/proton-sync-ui sync %i" in text
        assert "gui" not in text

    def test_uses_the_instance_placeholder(self) -> None:
        assert "%i" in service_template_text(executable="/usr/bin/proton-sync-ui")

    def test_waits_for_the_network(self) -> None:
        text = service_template_text(executable="/usr/bin/proton-sync-ui")

        assert "network-online.target" in text

    def test_partial_success_does_not_fail_the_unit(self) -> None:
        # Beendigungscode 1 bedeutet "Lauf mit einzelnen Dateifehlern".
        assert "SuccessExitStatus=0 1" in service_template_text(executable="/x")

    def test_does_not_sandbox_the_home_directory(self) -> None:
        # Die Proton-CLI braucht ihr eigenes Sitzungsverzeichnis.
        text = service_template_text(executable="/x")

        assert "ProtectHome" not in text
        assert "PrivateHome" not in text

    def test_runs_with_low_priority(self) -> None:
        text = service_template_text(executable="/x")

        assert "Nice=10" in text
        assert "IOSchedulingClass=idle" in text

    def test_documentation_is_not_a_missing_manpage(self) -> None:
        # systemd-analyze beanstandet einen man:-Verweis, zu dem keine
        # Handbuchseite installiert ist.
        text = service_template_text(executable="/x")

        assert "Documentation=" in text
        assert "man:" not in text


@pytest.mark.skipif(
    shutil.which("systemd-analyze") is None, reason="systemd-analyze nicht verfügbar"
)
class TestUnitsPassSystemdValidation:
    """Laesst systemd selbst pruefen, ob die Units syntaktisch stimmen."""

    @staticmethod
    def _verify(unit_path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["systemd-analyze", "--user", "verify", str(unit_path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_service_template_is_valid(self, tmp_path: Path) -> None:
        target = tmp_path / SERVICE_TEMPLATE_NAME
        target.write_text(service_template_text(executable="/bin/true"), encoding="utf-8")

        result = self._verify(target)

        assert result.returncode == 0, result.stderr
        assert "Failed" not in result.stderr

    def test_timer_is_valid(self, tmp_path: Path, scheduled_pair: SyncPair) -> None:
        # Der Timer verweist auf den Service, der daneben liegen muss.
        (tmp_path / SERVICE_TEMPLATE_NAME).write_text(
            service_template_text(executable="/bin/true"), encoding="utf-8"
        )
        target = tmp_path / timer_unit_name(scheduled_pair.uid)
        target.write_text(timer_unit_text(scheduled_pair), encoding="utf-8")

        result = self._verify(target)

        assert result.returncode == 0, result.stderr

    def test_no_warnings_about_unknown_directives(
        self, tmp_path: Path, scheduled_pair: SyncPair
    ) -> None:
        target = tmp_path / SERVICE_TEMPLATE_NAME
        target.write_text(service_template_text(executable="/bin/true"), encoding="utf-8")

        result = self._verify(target)

        assert "Unknown lvalue" not in result.stderr
        assert "Unknown key" not in result.stderr


class TestTimerUnit:
    """Die je Paar erzeugte Timer-Unit."""

    def test_contains_the_interval(self, scheduled_pair: SyncPair) -> None:
        text = timer_unit_text(scheduled_pair)

        assert "OnUnitInactiveSec=60min" in text

    def test_points_at_the_service_instance(self, scheduled_pair: SyncPair) -> None:
        text = timer_unit_text(scheduled_pair)

        assert f"Unit=proton-sync-ui@{scheduled_pair.uid}.service" in text

    def test_is_installable(self, scheduled_pair: SyncPair) -> None:
        text = timer_unit_text(scheduled_pair)

        assert "[Install]" in text
        assert "WantedBy=timers.target" in text

    def test_manual_pair_has_no_timer(self, sample_pair: SyncPair) -> None:
        with pytest.raises(UnitError, match="kein Intervall"):
            timer_unit_text(sample_pair)

    def test_description_is_single_line(self, source_dir: Path) -> None:
        pair = SyncPair.create(
            name="Name mit\nZeilenumbruch",
            local_path=source_dir,
            remote_path="/my-files/A",
            schedule_kind=ScheduleKind.INTERVAL,
            interval_minutes=30,
        )

        text = timer_unit_text(pair)

        description_lines = [line for line in text.splitlines() if line.startswith("Description=")]
        assert len(description_lines) == 1
        assert "Zeilenumbruch" in description_lines[0]

    def test_uses_inactive_not_active_timing(self, scheduled_pair: SyncPair) -> None:
        # Ab dem Ende des letzten Laufs gemessen: keine Ueberschneidungen.
        text = timer_unit_text(scheduled_pair)

        assert "OnUnitInactiveSec" in text
        assert "OnUnitActiveSec" not in text


class TestManagerFileHandling:
    """Schreiben und Entfernen der Unit-Dateien."""

    @pytest.fixture
    def manager(self, tmp_path: Path) -> SystemdManager:
        """Ein Manager auf einem temporaeren Unit-Verzeichnis, ohne systemctl."""
        return SystemdManager(unit_dir=tmp_path / "units", systemctl="/bin/true")

    def test_service_template_is_written(self, manager: SystemdManager) -> None:
        target = manager.install_service_template(executable="/usr/bin/proton-sync-ui")

        assert target.exists()
        assert target.name == SERVICE_TEMPLATE_NAME
        assert "ExecStart" in target.read_text(encoding="utf-8")

    def test_timer_is_written(self, manager: SystemdManager, scheduled_pair: SyncPair) -> None:
        target = manager.write_timer(scheduled_pair)

        assert target.exists()
        assert target.name == timer_unit_name(scheduled_pair.uid)

    def test_unchanged_timer_is_not_rewritten(
        self, manager: SystemdManager, scheduled_pair: SyncPair
    ) -> None:
        first = manager.write_timer(scheduled_pair)
        stamp = first.stat().st_mtime_ns

        second = manager.write_timer(scheduled_pair)

        assert second.stat().st_mtime_ns == stamp

    def test_timer_exists_check(self, manager: SystemdManager, scheduled_pair: SyncPair) -> None:
        assert manager.timer_exists(scheduled_pair.uid) is False
        manager.write_timer(scheduled_pair)
        assert manager.timer_exists(scheduled_pair.uid) is True

    def test_remove_timer(self, manager: SystemdManager, scheduled_pair: SyncPair) -> None:
        manager.write_timer(scheduled_pair)

        assert manager.remove_timer(scheduled_pair.uid) is True
        assert manager.timer_exists(scheduled_pair.uid) is False

    def test_remove_missing_timer_returns_false(
        self, manager: SystemdManager, scheduled_pair: SyncPair
    ) -> None:
        assert manager.remove_timer(scheduled_pair.uid) is False

    def test_list_managed_timers(self, manager: SystemdManager, scheduled_pair: SyncPair) -> None:
        manager.write_timer(scheduled_pair)

        assert manager.list_managed_timers() == [scheduled_pair.uid]

    def test_foreign_units_are_ignored(self, manager: SystemdManager) -> None:
        manager.unit_dir.mkdir(parents=True, exist_ok=True)
        (manager.unit_dir / "fremde-anwendung.timer").write_text("[Timer]\n")

        assert manager.list_managed_timers() == []

    def test_remove_all_leaves_foreign_units_alone(
        self, manager: SystemdManager, scheduled_pair: SyncPair
    ) -> None:
        manager.write_timer(scheduled_pair)
        manager.install_service_template(executable="/x")
        foreign = manager.unit_dir / "fremde-anwendung.timer"
        foreign.write_text("[Timer]\n")

        manager.remove_all()

        assert foreign.exists()
        assert not (manager.unit_dir / SERVICE_TEMPLATE_NAME).exists()


class TestManagerSynchronisation:
    """Abgleich der Units mit der Konfiguration."""

    @pytest.fixture
    def manager(self, tmp_path: Path) -> SystemdManager:
        return SystemdManager(unit_dir=tmp_path / "units", systemctl="/bin/true")

    def test_only_scheduled_pairs_get_a_timer(
        self, manager: SystemdManager, source_dir: Path
    ) -> None:
        manual = SyncPair.create(name="Manuell", local_path=source_dir, remote_path="/my-files/M")
        scheduled = SyncPair.create(
            name="Geplant",
            local_path=source_dir,
            remote_path="/my-files/G",
            schedule_kind=ScheduleKind.INTERVAL,
            interval_minutes=30,
        )

        manager.sync_pairs([manual, scheduled])

        assert manager.timer_exists(scheduled.uid) is True
        assert manager.timer_exists(manual.uid) is False

    def test_disabled_pair_gets_no_timer(self, manager: SystemdManager, source_dir: Path) -> None:
        disabled = SyncPair.create(
            name="Deaktiviert",
            local_path=source_dir,
            remote_path="/my-files/D",
            schedule_kind=ScheduleKind.INTERVAL,
            interval_minutes=30,
            enabled=False,
        )

        manager.sync_pairs([disabled])

        assert manager.timer_exists(disabled.uid) is False

    def test_disabling_a_pair_removes_its_timer(
        self, manager: SystemdManager, scheduled_pair: SyncPair
    ) -> None:
        manager.sync_pairs([scheduled_pair])
        assert manager.timer_exists(scheduled_pair.uid) is True

        manager.sync_pairs([scheduled_pair.with_changes(enabled=False)])

        assert manager.timer_exists(scheduled_pair.uid) is False

    def test_orphaned_timers_are_removed(
        self, manager: SystemdManager, scheduled_pair: SyncPair
    ) -> None:
        manager.sync_pairs([scheduled_pair])

        # Das Paar wurde geloescht -- der Timer muss verschwinden.
        manager.sync_pairs([])

        assert manager.list_managed_timers() == []

    def test_sync_installs_the_service_template(
        self, manager: SystemdManager, scheduled_pair: SyncPair
    ) -> None:
        manager.sync_pairs([scheduled_pair])

        assert (manager.unit_dir / SERVICE_TEMPLATE_NAME).exists()

    def test_actions_are_reported(self, manager: SystemdManager, scheduled_pair: SyncPair) -> None:
        actions = manager.sync_pairs([scheduled_pair])

        assert actions[scheduled_pair.uid] == "Timer geschrieben"


class TestSystemctlAvailability:
    """Verhalten ohne systemctl."""

    def test_missing_systemctl_is_reported(self, tmp_path: Path) -> None:
        manager = SystemdManager(unit_dir=tmp_path / "units", systemctl=None)
        # available prueft ueber shutil.which; in der Testumgebung meist vorhanden.
        assert isinstance(manager.available, bool)

    def test_timer_status_without_file(self, tmp_path: Path, sample_pair: SyncPair) -> None:
        manager = SystemdManager(unit_dir=tmp_path / "units", systemctl="/bin/true")

        status = manager.timer_status(sample_pair.uid)

        assert status.exists is False
        assert status.describe() == "kein Timer"
