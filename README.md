# ProtonSyncUI

<p align="center">
  <img src="data/icons/io.github.protonsyncui.ProtonSyncUI.svg" alt="ProtonSyncUI Logo" width="128" height="128">
</p>

<p align="center">
  <b>Moderne, Fedora-native GTK4 & libadwaita Desktop-Anwendung für Zwei-Wege-Synchronisation und Backups mit Proton Drive.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.13+">
  <img src="https://img.shields.io/badge/GTK-4.0-4A90D9?style=flat-square&logo=gnome&logoColor=white" alt="GTK4">
  <img src="https://img.shields.io/badge/libadwaita-1.0%2B-4A90D9?style=flat-square&logo=gnome&logoColor=white" alt="libadwaita">
  <img src="https://img.shields.io/badge/Fedora-40%2F41%2F42%2F43%2F44-51A2DA?style=flat-square&logo=fedora&logoColor=white" alt="Fedora Tested">
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License MIT">
  <img src="https://img.shields.io/badge/Tests-406%20passed-brightgreen?style=flat-square" alt="Tests">
</p>

---

## 🌟 Über das Projekt

**ProtonSyncUI** ist ein eleganter, zuverlässiger und ressourcenschonender Linux-Desktop-Client zur Synchronisation lokaler Ordner mit **Proton Drive**. 

Die Anwendung integriert sich nahtlos in die **GNOME-Desktop-Umgebung** (Fedora, Debian, Ubuntu, Arch) und nutzt als sicheres Fundament ausschließlich die **offizielle `proton-drive`-Kommandozeile**.

### Kernprinzipien & Sicherheitsmodell
* **🔒 100% Sicher & Datenschutzkonform**: Keine Passwörter, Tokens oder Session-Keys in der App. Die Authentifizierung verbleibt vollständig bei der offiziellen `proton-drive` CLI.
* **🛡️ Revisionssicherheit**: Bei Uploads wird standardmäßig `-f create-new-revision` und `-d merge` verwendet. Daten bei Proton Drive werden nicht unbemerkt vernichtet.
* **⚡ Parallele Cloud-Erfassung**: Beschleunigter Remote-Scan mit 8 parallelen asynchronen Workern.
* **🚫 Zero Telemetrie**: Keine Tracking-Tools, keine externen Cloud-Calls, kein Webserver – alles läuft rein lokal auf deinem Rechner.

---

## ✨ Hauptfunktionen

1. **Zwei-Wege- & Einweg-Synchronisation**:
   * **Bidirektional (⇄)**: Änderungen in beide Richtungen abgleichen.
   * **Upload-Only (→)**: Klassisches einseitiges Backup (lokal → Proton Drive).
   * **Download-Only (←)**: Cloud-Ordner lokal spiegeln.
2. **GNOME / libadwaita Benutzeroberfläche**:
   * Adaptive Seitenleiste (`Adw.NavigationSplitView`) mit Übersicht, Sync-Paaren, Konflikten, Aktivität, Einstellungen und Diagnose.
   * Hero-Statuskarte mit Farbcodierung (Erfolgreich, Laufend, Konflikte, Fehler) und Sofortaktionen (*Alle synchronisieren*).
   * Boxed Cards mit Pill-Status-Badges, Schnellumschaltern, Verlaufsdetails und Menüaktionen.
3. **Visuelles Konflikt-Center**:
   * Automatische Erkennung lokaler `.conflict-*` Dateien.
   * 2-Spalten-Gegenüberstellung (Lokale vs. Proton-Drive-Fassung) mit 1-Klick-Lösungsstrategien (*Beide behalten*, *Lokale bevorzugen*, *Cloud bevorzugen*).
4. **Dry-Run & Vorschau**:
   * Vollständige Simulation geplanter Uploads, Downloads, Überspringungen und Löschhinweise vor der eigentlichen Durchführung.
5. **Automatisierung via systemd-Timer**:
   * Zuverlässige Hintergrund-Synchronisation in frei wählbaren Intervallen (z. B. alle 30 oder 60 Minuten), auch wenn das GUI-Fenster geschlossen ist.
6. **Headless-CLI**:
   * Vollständige Steuerbarkeit im Terminal via `proton-sync-ui` (z. B. für Skripte oder Serverbetrieb).

---

## 🚀 Schnellstart & Installation

### 1. Repository klonen
```bash
git clone https://github.com/protonsyncui/proton-sync-ui.git
cd proton-sync-ui
```

### 2. Installationsskript ausführen
Das Skript installiert die Anwendung im Benutzerkontext (`~/.local`) und richtet bei Bedarf fehlende Systempakete (`GTK4`, `libadwaita`, `python3-gobject`) automatisch über den Paketmanager deiner Distribution ein:

```bash
chmod +x install.sh
./install.sh
```

> **Tipp für automatisierte Installationen (z. B. CI/CD):**
> ```bash
> ./install.sh -y
> ```

### 3. Proton Drive CLI anmelden (falls noch nicht geschehen)
```bash
proton-drive auth login
```

### 4. Anwendung starten
* Über das **Startmenü / Anwendungsübersicht**: Suche nach `ProtonSyncUI`.
* Über das **Terminal (GUI)**:
  ```bash
  proton-sync-ui-gui
  ```
* Über das **Terminal (CLI Status)**:
  ```bash
  proton-sync-ui status
  ```

---

## 📦 Systemvoraussetzungen

| Komponente | Anforderung | Hinweis |
|---|---|---|
| **Betriebssystem** | Linux (Fedora 40+, Ubuntu 24.04+, Debian 12+, Arch Linux, openSUSE) | Getestet & optimiert für Fedora |
| **Python** | `>= 3.13` | Python-Standardbibliothek |
| **Desktop / Toolkit** | GTK 4.0 & libadwaita 1.0+ | Wird bei Bedarf von `install.sh` installiert |
| **Backend-CLI** | `proton-drive` | Offizielle Proton Drive Kommandozeile |

---

## 🖥️ Bedienung & CLI-Referenz

### Grafische Oberfläche
* **Neues Sync-Paar anlegen**: Klicke in der Seitenleiste auf **Sync-Paare** -> **Sync-Paar hinzufügen**, wähle einen lokalen Ordner, den Zielpfad in Proton Drive, den Modus und optional ein systemd-Intervall.
* **Manuelle Synchronisation**: Klicke auf den Sync-Button in der Zeile des Paars oder auf **Alle synchronisieren** in der Übersicht.
* **Dry-Run prüfen**: Klicke auf das 3-Punkte-Menü des Paars -> **Dry-Run (Vorschau)**.
* **Konflikte auflösen**: Wechsle in den Bereich **Konflikte** und wähle die gewünschte Auflösungsstrategie.

### Kommandozeile (`proton-sync-ui`)

```bash
# Status aller konfigurierten Sync-Paare anzeigen
proton-sync-ui status

# Bestimmtes Sync-Paar synchronisieren
proton-sync-ui run <PAIR-UID-ODER-NAME>

# Dry-Run (Simulation) für ein Paar ausführen
proton-sync-ui dry-run <PAIR-UID-ODER-NAME>

# Liste aller Paare tabellarisch ausgeben
proton-sync-ui list

# systemd Hintergrund-Timer abgleichen
proton-sync-ui systemd sync

# Protokolldatei einsehen
proton-sync-ui logs
```

---

## 🏗️ Architektur & Code-Struktur

```
ProtonSyncUI/
├── data/                                 # Desktop-Metadaten & Symbole
│   ├── icons/io.github.protonsyncui.ProtonSyncUI.svg
│   └── io.github.protonsyncui.ProtonSyncUI.desktop
├── docs/                                 # Weiterführende Dokumentation
│   ├── ARCHITECTURE.md                   # System- & Komponentenarchitektur
│   └── INSTALL.md                        # Detaillierte Installationsanleitung
├── src/proton_sync_ui/                   # Python-Quellpaket
│   ├── cli/                              # Headless-CLI-Befehle
│   ├── cli_adapter/                      # Sicherer Subprocess-Adapter für proton-drive
│   ├── models/                           # Datamodels (SyncPair, RunRecord, UploadPlan)
│   ├── services/                         # Service-Layer (Contracts, DefaultServices)
│   ├── storage/                          # SQLite Schema & Repository (v2)
│   ├── sync/                             # 2-Wege Engine, Paralleler Remote-Scanner & Planer
│   ├── systemd/                          # systemd User-Timer & Service-Manager
│   └── ui/                               # GTK4 / libadwaita Benutzeroberfläche
│       ├── components/                   # StatusBadge, PairCardRow, ConflictCard
│       ├── views/                        # Overview, Pairs, Conflicts, Activity, Settings, Diag
│       ├── application.py                # Adw.Application
│       └── window.py                     # Adw.NavigationSplitView Hauptfenster
├── tests/                                # 406 Unittests & Smoke-Tests
├── install.sh                            # Automatisiertes Multi-Distro Installationsskript
├── uninstall.sh                          # Vollständiges Deinstallationsskript
└── pyproject.toml                        # PEP 621 Projekt- & Build-Definition
```

---

## 🛠️ Entwicklung & Qualitätssicherung

Zur Entwicklung und Ausführung der Testsuite:

```bash
# Entwicklerumgebung einrichten
./install.sh --dev

# Virtuelle Umgebung aktivieren
source ~/.local/share/proton-sync-ui/venv/bin/activate

# Gesamte Testsuite ausführen (406 Tests)
pytest

# Linter & Formatierung prüfen
ruff check .
ruff format --check .

# Statische Typprüfung
mypy
```

---

## 🗑️ Deinstallation

Um ProtonSyncUI sauber zu entfernen:

```bash
# Standard-Entfernung (Konfiguration und Verläufe bleiben erhalten)
./uninstall.sh

# Vollständige Entfernung inklusive lokaler Datenbank und Logs
./uninstall.sh --purge
```

> **Wichtig:** Deine zu Proton Drive übertragenen Dateien bleiben bei der Deinstallation in jedem Fall unberührt.

---

## 📄 Lizenz

Dieses Projekt ist unter der **MIT-Lizenz** lizenziert. Siehe [LICENSE](LICENSE) für Details.
