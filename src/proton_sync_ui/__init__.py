"""ProtonSyncUI -- 2-Wege-Synchronisation und Backups mit Proton Drive.

Die Anwendung spricht Proton Drive ausschliesslich ueber die offizielle
``proton-drive``-Kommandozeile an. Es gibt keine direkte API-Nutzung, keine
Browser-Automation und keinerlei Zugriff auf Passwoerter, Sitzungscookies,
Tokens oder Schluesselmaterial. Die Anmeldung erfolgt einmalig ausserhalb
dieser Anwendung mit ``proton-drive auth login``.
"""

from __future__ import annotations

__version__ = "0.3.1"
APP_ID = "io.github.protonsyncui.ProtonSyncUI"
APP_NAME = "proton-sync-ui"
APP_TITLE = "ProtonSyncUI"

__all__ = ["APP_ID", "APP_NAME", "APP_TITLE", "__version__"]
