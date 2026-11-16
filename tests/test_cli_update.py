"""Installation und Aktualisierung der Proton-Drive-CLI -- ohne Netz."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from proton_sync_ui import cli_update

FAKE_CLI = "#!/bin/sh\necho 'Proton Drive CLI cli-drive@{version}+abc'\n"


def index_page(sha512: str, *, url: str | None = None, version: str = "0.9.0") -> str:
    link = url or f"https://proton.me/download/drive/cli/{version}/linux-x64/proton-drive"
    return f"""<html><head><title>Proton Drive CLI {version}</title></head><body>
    <h1>Proton Drive CLI {version}</h1><table><tbody>
    <tr>
        <td>macos/arm64</td>
        <td><a href="https://proton.me/download/drive/cli/{version}/darwin-arm64/proton-drive">x</a></td>
        <td><code>{"a" * 128}</code></td>
    </tr>
    <tr>
        <td>linux/x64</td>
        <td><a href="{link}">{link}</a></td>
        <td><code>{sha512}</code></td>
    </tr></tbody></table></body></html>"""


def fake_download(content: str):
    def download(_url: str, destination: Path) -> str:
        destination.write_text(content, encoding="utf-8")
        return hashlib.sha512(content.encode()).hexdigest()

    return download


class TestIndex:
    def test_picks_the_row_of_this_platform(self) -> None:
        release = cli_update.parse_index(index_page("b" * 128), key="linux/x64")
        assert release.version == "0.9.0"
        assert release.url.endswith("/0.9.0/linux-x64/proton-drive")
        assert release.sha512 == "b" * 128

    def test_foreign_download_host_is_refused(self) -> None:
        page = index_page("b" * 128, url="https://example.invalid/proton-drive")
        with pytest.raises(cli_update.CliUpdateError):
            cli_update.parse_index(page, key="linux/x64")

    def test_missing_platform_is_reported(self) -> None:
        with pytest.raises(cli_update.CliUpdateError):
            cli_update.parse_index(index_page("b" * 128), key="linux/riscv")

    @pytest.mark.parametrize(
        ("machine", "expected"),
        [("x86_64", "linux/x64"), ("aarch64", "linux/arm64"), ("arm64", "linux/arm64")],
    )
    def test_platform_key(self, machine: str, expected: str) -> None:
        assert cli_update.platform_key(machine, "Linux") == expected

    def test_unknown_platform(self) -> None:
        with pytest.raises(cli_update.CliUpdateError):
            cli_update.platform_key("riscv64", "Linux")

    def test_update_is_only_offered_for_newer_versions(self) -> None:
        release = cli_update.CliRelease("0.9.0", "u", "s", "linux/x64")
        assert cli_update.is_update_available(release, "0.8.0")
        assert cli_update.is_update_available(release, "")
        assert not cli_update.is_update_available(release, "0.9.0")
        assert not cli_update.is_update_available(release, "0.10.0")


class TestInstall:
    def _release(self, content: str, *, sha512: str | None = None) -> cli_update.CliRelease:
        return cli_update.CliRelease(
            version="0.9.0",
            url="https://proton.me/download/drive/cli/0.9.0/linux-x64/proton-drive",
            sha512=sha512 or hashlib.sha512(content.encode()).hexdigest(),
            platform="linux/x64",
        )

    def test_fresh_install(self, tmp_path: Path) -> None:
        content = FAKE_CLI.format(version="0.9.0")
        target = tmp_path / "bin" / "proton-drive"

        version = cli_update.install_release(
            self._release(content), target, download=fake_download(content)
        )

        assert version == "0.9.0"
        assert cli_update.installed_version(target) == "0.9.0"
        assert not (target.parent / "proton-drive.bak").exists()

    def test_update_keeps_a_backup(self, tmp_path: Path) -> None:
        target = tmp_path / "proton-drive"
        target.write_text(FAKE_CLI.format(version="0.8.0"))
        target.chmod(0o755)
        content = FAKE_CLI.format(version="0.9.0")

        cli_update.install_release(self._release(content), target, download=fake_download(content))

        assert cli_update.installed_version(target) == "0.9.0"
        assert cli_update.installed_version(target.with_name("proton-drive.bak")) == "0.8.0"
        assert [p.name for p in tmp_path.iterdir() if ".new-" in p.name] == []

    def test_wrong_checksum_installs_nothing(self, tmp_path: Path) -> None:
        target = tmp_path / "proton-drive"
        old = FAKE_CLI.format(version="0.8.0")
        target.write_text(old)
        target.chmod(0o755)
        content = FAKE_CLI.format(version="0.9.0")

        with pytest.raises(cli_update.CliUpdateError, match="Pruefsumme"):
            cli_update.install_release(
                self._release(content, sha512="0" * 128), target, download=fake_download(content)
            )

        assert target.read_text() == old
        leftovers = [p.name for p in tmp_path.iterdir() if "proton-drive" in p.name]
        assert leftovers == ["proton-drive"]

    def test_binary_that_does_not_start_is_not_installed(self, tmp_path: Path) -> None:
        target = tmp_path / "proton-drive"
        content = "kein Programm"

        with pytest.raises(cli_update.CliUpdateError, match="starten"):
            cli_update.install_release(
                self._release(content), target, download=fake_download(content)
            )

        assert not target.exists()

    def test_untrusted_url_is_refused(self, tmp_path: Path) -> None:
        release = cli_update.CliRelease(
            "9.9.9", "https://example.invalid/x", "0" * 128, "linux/x64"
        )
        with pytest.raises(cli_update.CliUpdateError):
            cli_update.install_release(release, tmp_path / "proton-drive")

    def test_target_follows_the_existing_binary(self, tmp_path: Path) -> None:
        existing = tmp_path / "proton-drive"
        existing.write_text("x")
        assert cli_update.target_path(str(existing)) == existing
        assert cli_update.target_path(None) == Path.home() / ".local" / "bin" / "proton-drive"
