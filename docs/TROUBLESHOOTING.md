# ProtonSyncUI – Fehlerbehebung & Diagnose (Troubleshooting)

Dieser Leitfaden hilft dir bei der schnellen Lösung häufiger Probleme und Fehlermeldungen bei der Nutzung von **ProtonSyncUI**.

---

## 📑 Inhaltsverzeichnis

1. [Probleme bei der Authentifizierung & Anmeldung](#1-probleme-bei-der-authentifizierung--anmeldung)
2. [CLI & Pfad-Probleme (`command not found`)](#2-cli--pfad-probleme-command-not-found)
3. [Fehler bei GTK4 / libadwaita & Python-Abhängigkeiten](#3-fehler-bei-gtk4--libadwaita--python-abhängigkeiten)
4. [System-Tray Icon wird nicht angezeigt](#4-system-tray-icon-wird-nicht-angezeigt)
5. [systemd Hintergrund-Timer starten nicht](#5-systemd-hintergrund-timer-starten-nicht)
6. [Fehlerhafte oder blockierte Synchronisationen (Sperren)](#6-fehlerhafte-oder-blockierte-synchronisationen-sperren)
7. [Protokolldateien analysieren & Bug-Reports erstellen](#7-protokolldateien-analysieren--bug-reports-erstellen)

---

## 1. Probleme bei der Authentifizierung & Anmeldung

### Symptom: `Fehler: Proton Drive CLI ist nicht angemeldet`
* **Ursache:** Die Sitzung der offiziellen `proton-drive` CLI ist abgelaufen oder wurde noch nicht eingerichtet.
* **Lösung:** Führe die Anmeldung im Terminal erneut durch:
  ```bash
  proton-drive auth login
  ```
  Prüfe anschließend den Status mit:
  ```bash
  proton-drive auth status
  ```

### Symptom: Fehler beim Schlüsselbund (Keyring Lock)
* **Ursache:** Wenn du dich ohne grafische Benutzeroberfläche (z. B. via SSH) einloggst, ist der GNOME-Keyring oder KWallet oft gesperrt.
* **Lösung:** Entsperre den Schlüsselbund oder richte einen Session-Keyring ein. Bei reinen Servern kannst du `gnome-keyring-daemon --unlock` verwenden.

---

## 2. CLI & Pfad-Probleme (`command not found`)

### Symptom: `proton-drive: command not found` oder `proton-sync-ui: command not found`
* **Ursache:** Das Verzeichnis `~/.local/bin` befindet sich nicht in deiner Umgebungsvariable `$PATH`.
* **Lösung:**
  Füge folgende Zeile zu deiner Shell-Konfigurationsdatei hinzu (`~/.bashrc` oder `~/.zshrc`):
  ```bash
  export PATH="$HOME/.local/bin:$PATH"
  ```
  Lade deine Shell neu:
  ```bash
  source ~/.bashrc
  ```

---

## 3. Fehler bei GTK4 / libadwaita & Python-Abhängigkeiten

### Symptom: `ModuleNotFoundError: No module named 'gi'` oder `SystemError: gi.FunctionInfo(init)...`
* **Ursache:** Die Python-GObject-Introspektionspakete oder libadwaita fehlen im System.
* **Lösung nach Distribution:**

#### Fedora / RHEL:
```bash
sudo dnf install -y python3-gobject gtk4 libadwaita python3-cairo
```

#### Ubuntu / Debian:
```bash
sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libadwaita-1-0
```

#### Arch Linux:
```bash
sudo pacman -S --needed python-gobject gtk4 libadwaita python-cairo
```

Führe danach `./install.sh` erneut aus, um die isolierte virtuelle Umgebung mit `--system-site-packages` zu aktualisieren.

---

## 4. System-Tray Icon wird nicht angezeigt

### Symptom: Nach dem Starten von ProtonSyncUI erscheint kein Icon in der Taskleiste (GNOME Shell).
* **Ursache:** Die GNOME-Desktop-Umgebung blendet System-Tray-Icons standardmäßig aus.
* **Lösung:** Installiere die offizielle AppIndicator-Erweiterung:
  * **Fedora:** `sudo dnf install -y gnome-shell-extension-appindicator`
  * **Ubuntu:** `sudo apt install -y gnome-shell-extension-appindicator`
  * Öffne anschließend die App **Erweiterungen** (*Extensions*) und aktiviere **AppIndicator and KStatusNotifierItem Support**.

---

## 5. systemd Hintergrund-Timer starten nicht

### Symptom: Automatische Läufe werden nicht zur geplanten Zeit ausgeführt.
1. **Timer-Status überprüfen:**
   ```bash
   systemctl --user list-timers 'proton-sync-ui*'
   ```
2. **Timer neu synchronisieren:**
   ```bash
   proton-sync-ui systemd sync
   ```
3. **Timer-Dienst neu laden:**
   ```bash
   systemctl --user daemon-reload
   ```
4. **Prüfen, ob User-Linger aktiviert ist (für Läufe nach Abmeldung):**
   ```bash
   loginctl enable-linger $USER
   ```

---

## 6. Fehlerhafte oder blockierte Synchronisationen (Sperren)

### Symptom: `Synchronisation für dieses Paar wird bereits ausgeführt (gesperrt).`
* **Ursache:** Ein vorheriger Lauf wurde durch einen plötzlichen Stromausfall oder `kill -9` beendet.
* **Lösung:**
  ProtonSyncUI bereinigt verwaiste Sperren automatisch beim nächsten Start, wenn der Prozess nicht mehr existiert.
  Sollte die Meldung dennoch fälschlicherweise auftreten, kannst du den Status prüfen mit:
  ```bash
  proton-sync-ui status
  ```
  Oder die SQLite-Sperrtabelle manuell zurücksetzen:
  ```bash
  sqlite3 ~/.local/state/proton-sync-ui/database.sqlite "DELETE FROM run_locks;"
  ```

---

## 7. Protokolldateien analysieren & Bug-Reports erstellen

Die zentrale Protokolldatei erfasst alle Vorgänge, Dateitransfers und Fehler:

```bash
# Pfad zur Logdatei:
~/.local/state/proton-sync-ui/proton-sync-ui.log
```

### Live-Logs mitlesen:
```bash
tail -f ~/.local/state/proton-sync-ui/proton-sync-ui.log
```

### Sensible Daten in Bug-Reports:
> **🔒 Schutz deiner Privatsphäre:** ProtonSyncUI schwärzt sensible Anmeldedaten und Tokens in Protokolldateien automatisch. Bitte prüfe Logs vor der Veröffentlichung in öffentlichen GitHub-Issues dennoch kurz auf eventuell private Pfadnamen.
