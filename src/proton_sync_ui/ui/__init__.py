"""GTK4-/libadwaita-Oberflaeche.

Dieses Paket ist die einzige Stelle, die GTK importiert. Kommandozeile und
Sync-Logik kommen ohne grafische Sitzung aus.
"""

from __future__ import annotations

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Startet die Oberflaeche.

    Der Import steht bewusst in der Funktion: Wer nur ``proton_sync_ui.ui``
    importiert, soll dabei nicht GTK und libadwaita mitladen.
    """
    from .application import main as run  # noqa: PLC0415 -- s. o.

    return run(argv)
