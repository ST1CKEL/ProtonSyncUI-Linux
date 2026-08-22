# Installationsanleitung für ProtonSyncUI

Diese Anleitung beschreibt die Installation, Abhängigkeiten und Fehlerbehebung von **ProtonSyncUI** auf verschiedenen Linux-Distributionen.

---

## 1. Schnellinstallation (Empfohlen)

Das mitgelieferte Installationsskript [`install.sh`](../install.sh) erkennt die verwendete Distribution automatisch, installiert bei Bedarf fehlende Systempakete und richtet die Anwendung isoliert im Benutzerverzeichnis (`~/.local`) ein.

```bash
git clone https://github.com/ST1CKEL/ProtonSyncUI-Linux.git
cd ProtonSyncUI-Linux
chmod +x install.sh
./install.sh
```

*(Für automatisierte Installationen ohne Bestätigungsabfragen: `./install.sh -y`)*

---

## 2. Manuelle Installation nach Distribution

Falls du die System-Abhängigkeiten manuell vorab installieren möchtest:

### Fedora / RHEL / Rocky Linux / AlmaLinux
```bash
sudo dnf install -y python3-gobject gtk4 libadwaita python3-cairo librsvg2-tools python3-pip python3-devel desktop-file-utils
```

### Ubuntu (ab 24.04 LTS) / Debian (ab 12 Bookworm) / Pop!_OS / Linux Mint
```bash
sudo apt update
sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libadwaita-1-0 librsvg2-bin python3-pip python3-venv desktop-file-utils
```

### Arch Linux / Manjaro / EndeavourOS
```bash
sudo pacman -S --needed python-gobject gtk4 libadwaita python-cairo librsvg python-pip desktop-file-utils
```

### openSUSE (Tumbleweed / Leap 15+)
```bash
sudo zypper install -y python3-gobject gtk4 libadwaita-1-0 python3-cairo librsvg-tools python3-pip desktop-file-utils
```

---

## 3. Proton Drive CLI einrichten

ProtonSyncUI benötigt die offizielle `proton-drive`-Kommandozeile.

### Installation der CLI
Falls noch nicht vorhanden:
```bash
pip install proton-drive
```
*(Oder über das offizielle Paket/Repository von Proton).*

### Einmalige Authentifizierung
Melde dich im Terminal bei Proton Drive an:
```bash
proton-drive auth login
```
Folge den Anweisungen im Terminal (Benutzername, Passwort, ggf. 2FA). ProtonSyncUI erkennt den Anmeldestatus anschließend automatisch.

---

## 4. Installierte Pfade

ProtonSyncUI verändert keine Systemdateien und benötigt keine Root-Rechte zur Laufzeit:

| Pfad | Zweck |
|---|---|
| `~/.local/share/proton-sync-ui/venv` | Isolierte Python-Laufzeitumgebung (mit Zugriff auf System-GTK) |
| `~/.local/bin/proton-sync-ui` | Headless-CLI-Startskript (auch für systemd) |
| `~/.local/bin/proton-sync-ui-gui` | Grafischer GUI-Starter |
| `~/.local/share/applications/io.github.protonsyncui.ProtonSyncUI.desktop` | Startmenü-Eintrag |
| `~/.local/share/icons/hicolor/scalable/apps/io.github.protonsyncui.ProtonSyncUI.svg` | Desktop-Anwendungssymbol |
| `~/.local/state/proton-sync-ui/database.sqlite` | Lokale SQLite-Zustands- und Verlaufsdatenbank |
| `~/.local/state/proton-sync-ui/proton-sync-ui.log` | Anwendungs- und Sync-Protokoll |
| `~/.config/systemd/user/proton-sync-ui@*.timer` | Automatisch erzeugte systemd-Hintergrund-Timer |

---

## 5. Weiterführende Dokumentation

* 📖 **[Benutzerhandbuch (User Guide)](USER_GUIDE.md)** – Anleitung zur Nutzung und Konfiguration der UI.
* 🏛️ **[Architektur & Design](ARCHITECTURE.md)** – Systemarchitektur und Sicherheitskonzept.
* 💻 **[CLI-Referenz](CLI_REFERENCE.md)** – Befehle für Terminal und Serverbetrieb.
* 🔧 **[Fehlerbehebung (Troubleshooting)](TROUBLESHOOTING.md)** – Lösungen für typische Probleme.
* ⏱️ **[systemd Integration](../systemd/README-systemd.md)** – Details zu den Hintergrund-Timern.
