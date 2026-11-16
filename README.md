# ProtonSyncUI

<p align="center">
  <img src="data/icons/io.github.protonsyncui.ProtonSyncUI.svg" alt="ProtonSyncUI Logo" width="128" height="128">
</p>

<p align="center">
  <b>Moderne, native GTK4 & libadwaita Desktop-Anwendung für Zwei-Wege-Synchronisation und automatische Backups mit Proton Drive.</b>
</p>

<p align="center">
  <a href="https://github.com/ST1CKEL/ProtonSyncUI-Linux"><img src="https://img.shields.io/badge/GitHub-Repository-181717?style=flat-square&logo=github&logoColor=white" alt="GitHub Repo"></a>
  <img src="https://img.shields.io/badge/Python-3.13%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.13+">
  <img src="https://img.shields.io/badge/GTK-4.0-4A90D9?style=flat-square&logo=gnome&logoColor=white" alt="GTK4">
  <img src="https://img.shields.io/badge/libadwaita-1.4%2B-4A90D9?style=flat-square&logo=gnome&logoColor=white" alt="libadwaita">
  <img src="https://img.shields.io/badge/Tray-StatusNotifierItem-00C2B8?style=flat-square" alt="System Tray Support">
  <img src="https://img.shields.io/badge/Linux-Fedora%20%7C%20Ubuntu%20%7C%20Debian%20%7C%20Arch%20%7C%20openSUSE-51A2DA?style=flat-square&logo=linux&logoColor=white" alt="Linux Distros">
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License MIT">
  <img src="https://img.shields.io/badge/Tests-465%20passed-brightgreen?style=flat-square" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.3.0-0EA5A8?style=flat-square" alt="Version 0.3.0">
</p>

---

## 🌟 Highlights & Funktionen

- 🔄 **Echte 2-Wege-Synchronisation (Cloud ⇄ Lokal)**: Erkennt Änderungen auf beiden Seiten und gleicht sie nahtlos ab. Unterstützt zudem reine Upload- und Download-Modi.
- 🎨 **Modernes GNOME / libadwaita Design**: Folgt den GNOME Human Interface Guidelines (HIG) mit adaptivem Layout (`Adw.NavigationSplitView`), Dark-Mode-Unterstützung und flüssigen Animationen.
- 📥 **System-Tray & Hintergrund-Betrieb**: Läuft im Infobereich über das standardisierte `StatusNotifierItem` & `DBusMenu`-Protokoll (KDE Plasma, GNOME AppIndicator, XFCE, Sway/Waybar). Das Symbol zeigt den Zustand mit farbiger Marke (Sync, Warnung, Fehler) und meldet sich nach einem Neustart der Kontrollleiste selbst wieder an.
- 🚀 **Autostart bei der Anmeldung**: Startet auf Wunsch mit der Arbeitsfläche, minimiert im Infobereich. Die Installation kommt ohne virtuelle Umgebung aus und übersteht Distributions-Upgrades (z. B. Fedora 44 → 45).
- ⬆️ **Eingebaute Update-Funktion**: Sucht höchstens einmal täglich nach einer neuen Version und installiert sie nach Bestätigung – in der Oberfläche oder per `proton-sync-ui update`.
- 🔑 **Anmeldung per Klick**: Ist Proton Drive abgemeldet, weist eine Hinweisleiste darauf hin und startet die Anmeldung der offiziellen CLI.
- ⏱️ **systemd User-Timer**: Vollständig integrierte, native Hintergrundsynchronisation im Benutzerprofil (`systemd --user`) – zuverlässig, ressourcenschonend und ohne Root-Rechte.
- ⚖️ **Visuelles Konflikt-Center**: Bei gleichzeitigen Änderungen schützt ProtonSyncUI deine Daten mit 1-Klick-Lösungsstrategien (*Beide behalten*, *Lokal bevorzugen*, *Cloud bevorzugen*).
- 🛡️ **100% Zero-Knowledge & Datenschutz**: Keine Weitergabe von Passwörtern oder Tokens; die kryptografische Authentifizierung verbleibt vollständig bei der offiziellen `proton-drive` CLI. 0% Telemetrie.
- ⚡ **Crash-Sicherheit & Atomarer Schutz**: Speicherung des Zustands in einer SQLite-Datenbank (Schema v3). Keine doppelten Übertragungen bei Verbindungsabbrüchen; aussichtslose Läufe (abgemeldet, Dienst nicht erreichbar) enden sofort statt tausende Anfragen zu senden.
- 🖥️ **Headless CLI**: Volle Steuerbarkeit auch auf Servern oder in Skripten ohne Desktop-Umgebung.

---

## 📸 Benutzeroberfläche & Screenshots

### 1. Übersicht & Schnellzugriff (`Overview`)
> Live-Status aller Sync-Paare, Hero-Statuskarte, Schnellabgleich mit 1-Klick ("Alle synchronisieren") und Anzeige der letzten Aktivitäten.

<p align="center">
  <img src="docs/screenshots/overview.png" alt="Übersicht & Schnellzugriff" width="90%">
</p>

---

### 2. Sync-Paare verwalten (`Sync Pairs`)
> Übersichtliche Boxed-Cards je Ordnerpaar mit Status-Badges, Schnellumschaltern für automatische Läufe, Dry-Run-Simulation und Einzelfortschrittsanzeige.

<p align="center">
  <img src="docs/screenshots/pairs.png" alt="Sync-Paare Verwaltung" width="90%">
</p>

---

### 3. Visuelles Konflikt-Center (`Conflicts`)
> Automatische Erkennung divergierender Dateistände mit übersichtlicher 2-Spalten-Gegenüberstellung und 1-Klick-Lösungsstrategien.

<p align="center">
  <img src="docs/screenshots/conflicts.png" alt="Konflikt-Center" width="90%">
</p>

---

### 4. Einstellungen & System-Integration (`Settings`)
> Autostart beim Anmelden (auch minimiert im Infobereich), Desktop-Benachrichtigungen, eingebaute Update-Funktion sowie Anmeldung und Zustand der Proton-Drive-CLI.

<p align="center">
  <img src="docs/screenshots/settings.png" alt="Einstellungen" width="90%">
</p>

---

### 5. Aktivitäts- & Historienverlauf (`Activity`)
> Lückenloser Verlauf aller Synchronisationen, geplante Übertragungen, Dateifehler und detaillierte Kennzahlen (übertragene Datenmenge, Dauer).

<p align="center">
  <img src="docs/screenshots/activity.png" alt="Aktivitätsverlauf" width="90%">
</p>

---

## 🏗️ Architektur & Funktionsweise

ProtonSyncUI setzt auf eine strikte Schichtenarchitektur (Clean Architecture) mit robuster Trennung von Benutzeroberfläche, Synchronisationslogik und CLI-Infrastruktur:

```mermaid
graph TD
    UI[GTK4 / libadwaita UI & Tray] -->|Ruft Services auf| SVC[Service Layer]
    CLI[Headless CLI] -->|Ruft Services auf| SVC
    SYSTEMD[systemd User-Timer] -->|Startet CLI-Lauf| CLI
    
    SVC --> ENGINE[2-Wege Sync Engine]
    SVC --> REPO[(SQLite Repository v2)]
    
    ENGINE --> SCANNER[Paralleler Remote-Scanner]
    ENGINE --> PLANNER[3-Wege Sync-Planer]
    ENGINE --> ADAPTER[ProtonDrive CLI Adapter]
    
    ADAPTER -->|Subprocess Execution| PCLI[Offizielle proton-drive CLI]
    PCLI -->|E2E-Verschlüsselt| CLOUD[Proton Drive Cloud]
```

### 3-Wege-Abgleich (Sync Matrix)
Der Planer vergleicht den Zustand des lokalen Dateisystems, den Remote-Zustand auf Proton Drive und den in SQLite gespeicherten Stand des letzten erfolgreichen Laufs:

| Lokaler Zustand | Cloud-Zustand | DB-Zustand (Letzter Sync) | Geplante Aktion |
|---|---|---|---|
| Neu angelegt | Nicht vorhanden | Nicht vorhanden | **Upload (Neu)** |
| Nicht vorhanden | Neu angelegt | Nicht vorhanden | **Download (Neu)** |
| Geändert | Unverändert | Gespeichert | **Upload (Aktualisierung)** |
| Unverändert | Geändert | Gespeichert | **Download (Aktualisierung)** |
| Geändert | Geändert | Gespeichert | ⚠️ **Konflikt erkannt (Archivierung / Lösungsdialog)** |
| Gelöscht | Vorhanden | Gespeichert | **Lokal gelöscht** *(Remote-Kopie bleibt geschützt erhalten und wird nicht erneut heruntergeladen)* |
| Gelöscht | Danach geändert | Gelöscht vermerkt | **Download (Neu)** *(neue Cloud-Fassung wird wieder geladen)* |
| Vorhanden | Vorhanden, gleiche Größe | Nicht vorhanden | **Überspringen** *(Stand wird als synchron vermerkt)* |
| Vorhanden | Vorhanden, andere Größe | Nicht vorhanden | ⚠️ **Konflikt** *(lokale Fassung wird gesichert, Cloud-Fassung übernommen)* |
| Unverändert | Unverändert | Gespeichert | **Überspringen (Identisch)** |

---

## 📋 Systemanforderungen & Distributionen

| Distribution | Mindestversion | Paketmanager | Installationsbefehl für Abhängigkeiten |
|---|---|---|---|
| **Fedora / RHEL** | 41, 42, 43, 44, 45 (Python ≥ 3.13) | `dnf` | `sudo dnf install -y python3-gobject gtk4 libadwaita python3-cairo librsvg2-tools` |
| **Ubuntu / Debian** | Ubuntu 24.04+, Debian 12+ | `apt` | `sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libadwaita-1-0 librsvg2-bin` |
| **Arch Linux / Manjaro** | Rolling Release | `pacman` | `sudo pacman -S --needed python-gobject gtk4 libadwaita python-cairo librsvg` |
| **openSUSE** | Tumbleweed / Leap 15.6+ | `zypper` | `sudo zypper install -y python3-gobject gtk4 libadwaita-1-0 python3-cairo librsvg-tools` |

---

## 🚀 Installation & Schnellstart

### 1. Repository klonen
```bash
git clone https://github.com/ST1CKEL/ProtonSyncUI-Linux.git
cd ProtonSyncUI-Linux
```

### 2. Automatisierten Installer ausführen
```bash
chmod +x install.sh
./install.sh
```

*(Nicht-interaktiv: `./install.sh -y` · gleich mit Autostart bei der Anmeldung: `./install.sh --autostart`)*

Die Anwendung wird ohne virtuelle Umgebung nach `~/.local/share/proton-sync-ui/app` kopiert und
läuft mit dem Python des Systems. Sie übersteht damit Distributions-Upgrades (z. B. Fedora 44 → 45)
ohne Neuinstallation.

### 3. Bei Proton Drive anmelden (falls noch nicht erfolgt)
In der Anwendung auf **Anmelden** klicken (Hinweisleiste oder *Einstellungen → Proton Drive*) –
oder im Terminal:
```bash
proton-drive auth login
```

### 4. Anwendung starten
* **Über die Anwendungsübersicht**: Nach `ProtonSyncUI` suchen.
* **Über das Terminal**:
  ```bash
  proton-sync-ui-gui
  ```
* **Minimiert im Infobereich starten**:
  ```bash
  proton-sync-ui-gui --minimized
  ```

### 5. Autostart & Updates
```bash
proton-sync-ui autostart on     # bei der Anmeldung starten (KDE Plasma, GNOME), minimiert im Infobereich
proton-sync-ui autostart off
proton-sync-ui update --check   # nach einer neuen Version suchen
proton-sync-ui update           # neue Version herunterladen und installieren
```
Beides lässt sich auch unter *Einstellungen* schalten. Die Update-Suche läuft auf Wunsch einmal
täglich automatisch; installiert wird erst nach Bestätigung.

---

## ⌨️ CLI-Befehlsreferenz (Headless-Betrieb)

ProtonSyncUI lässt sich auch auf Servern oder in eigenen Skripten steuern:

```bash
# Status aller Paare anzeigen
proton-sync-ui status

# Synchronisation für ein Paar starten
proton-sync-ui run <PAIR-UID-ODER-NAME>

# Dry-Run (Simulation) ohne Änderungen
proton-sync-ui dry-run <PAIR-UID-ODER-NAME>

# Alle konfigurierten Paare auflisten
proton-sync-ui list

# systemd Timer aktualisieren
proton-sync-ui systemd sync

# Aktuelle Protokolldatei einsehen
proton-sync-ui logs
```

---

## 📚 Ausführliche Dokumentation

Weitere detaillierte Anleitungen und technische Referenzen findest du im Ordner [`docs/`](docs/):

* 📖 **[Benutzerhandbuch (User Guide)](docs/USER_GUIDE.md)** – Vollständige Anleitung zur Konfiguration, Konfliktlösung und Benutzeroberfläche.
* 🏛️ **[Architektur & Design](docs/ARCHITECTURE.md)** – Tiefgehende Systemdokumentation, Schichtenmodell, SQLite Schema und Scanner-Pipeline.
* 📦 **[Installationsanleitung](docs/INSTALL.md)** – Detaillierte Anleitung für alle Linux-Distributionen & manuelle Einrichtung.
* 💻 **[CLI-Referenz](docs/CLI_REFERENCE.md)** – Headless-Nutzung, Scripting, Exit-Codes und Automatisierung.
* 🔧 **[Fehlerbehebung (Troubleshooting)](docs/TROUBLESHOOTING.md)** – Diagnoseleitfaden für Schlüsselbunde, Berechtigungen und Logs.
* ⏱️ **[systemd Integration](systemd/README-systemd.md)** – Funktionsweise der User-Units und Hintergrund-Timer.

---

## 🛠️ Entwicklung & Tests

```bash
# Entwicklermodus: die Startbefehle verwenden direkt diesen Quellbaum
./install.sh --dev

# Entwicklerwerkzeuge (pytest, ruff, mypy)
python3 -m venv --system-site-packages .venv && .venv/bin/pip install -e ".[dev]"

# Testsuite ausführen
PYTHONPATH=src python3 -m pytest

# Code-Qualität & Formatierung prüfen
ruff check .
ruff format --check .

# Typanalyse
mypy
```

---

## 🗑️ Deinstallation

```bash
# Standard-Deinstallation (Konfiguration und Datenbank bleiben erhalten)
./uninstall.sh

# Vollständige Bereinigung (inklusive lokaler Datenbank und Logs)
./uninstall.sh --purge
```

---

## 📄 Lizenz

Dieses Projekt ist unter der **MIT-Lizenz** lizenziert. Siehe [LICENSE](LICENSE) für weitere Details.
