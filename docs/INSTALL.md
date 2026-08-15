# Installationsanleitung für ProtonSyncUI

Diese Anleitung beschreibt die Installation, Abhängigkeiten und Fehlerbehebung von **ProtonSyncUI** auf verschiedenen Linux-Distributionen.

---

## 1. Schnellinstallation (Empfohlen)

Das mitgelieferte Installationsskript [`install.sh`](../install.sh) erkennt die verwendete Distribution, installiert bei Bedarf fehlende Systempakete und richtet die Anwendung isoliert im Benutzerverzeichnis (`~/.local`) ein.

```bash
git clone https://github.com/protonsyncui/proton-sync-ui.git
cd proton-sync-ui
chmod +x install.sh
./install.sh
```

---

## 2. Manuelle Installation nach Distribution

Falls du die System-Abhängigkeiten manuell vorab installieren möchtest:

### Fedora / RHEL / Rocky Linux / AlmaLinux
```bash
sudo dnf install -y python3-gobject gtk4 libadwaita python3-pip python3-devel desktop-file-utils
```

### Ubuntu (ab 24.04 LTS) / Debian (ab 12 Bookworm) / Pop!_OS / Linux Mint
```bash
sudo apt update
sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libadwaita-1-0 python3-pip python3-venv desktop-file-utils
```

### Arch Linux / Manjaro / EndeavourOS
```bash
sudo pacman -S --needed python-gobject gtk4 libadwaita python-pip desktop-file-utils
```

### openSUSE (Tumbleweed / Leap 15+)
```bash
sudo zypper install -y python3-gobject typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 libadwaita-1-0 python3-pip desktop-file-utils
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

## 5. Fehlerbehebung & Häufige Fragen

### Problem: `proton-drive: command not found`
* Stelle sicher, dass `~/.local/bin` in deiner `$PATH`-Umgebungsvariable liegt.
* Füge in deiner `~/.bashrc` oder `~/.zshrc` folgendes ein:
  ```bash
  export PATH="$HOME/.local/bin:$PATH"
  ```
* Lade die Shell neu mit `source ~/.bashrc`.

### Problem: `Adwaita oder Gtk konnte nicht importiert werden`
* Dies tritt auf, wenn `python3-gobject`, `gtk4` oder `libadwaita` im System fehlen oder die venv ohne `--system-site-packages` erstellt wurde.
* Führe `./install.sh` erneut aus, um die Umgebung sauber neu aufzubauen.

### Problem: Hintergrund-Synchronisation startet nicht automatisch
* Prüfe den Status deiner user-systemd-Timer:
  ```bash
  systemctl --user list-timers "proton-sync-ui*"
  ```
* Aktualisiere die Timer über das Terminal:
  ```bash
  proton-sync-ui systemd sync
  ```
