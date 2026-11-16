# ProtonSyncUI – CLI-Befehlsreferenz

ProtonSyncUI verfügt über ein vollwertiges Headless-Kommandozeilen-Interface (`proton-sync-ui`), mit dem sämtliche Synchronisations- und Verwaltungsaufgaben ohne grafische Oberfläche ausgeführt werden können.

---

## 📑 Inhaltsverzeichnis

1. [Übersicht der Befehle](#1-übersicht-der-befehle)
2. [Befehlsdetails](#2-befehlsdetails)
   - [`status`](#proton-sync-ui-status)
   - [`list`](#proton-sync-ui-list)
   - [`run`](#proton-sync-ui-run-identifier)
   - [`dry-run`](#proton-sync-ui-dry-run-identifier)
   - [`systemd`](#proton-sync-ui-systemd-subcommand)
   - [`logs`](#proton-sync-ui-logs)
3. [Exit-Codes & Scripting](#3-exit-codes--scripting)
4. [Headless Server & Cron-Nutzung](#4-headless-server--cron-nutzung)

---

## 1. Übersicht der Befehle

```bash
proton-sync-ui [OPTIONEN] BEFEHL [ARGUMENTE...]
```

| Befehl | Beschreibung |
|---|---|
| `status` | Zeigt den aktuellen Status aller konfigurierten Sync-Paare an. |
| `list` | Listet alle konfigurierten Sync-Paare in Tabellenform auf. |
| `run <NAME\|UUID>` | Führt die Synchronisation für das angegebene Sync-Paar aus. |
| `dry-run <NAME\|UUID>` | Führt eine Simulation ohne Änderungen für das angegebene Sync-Paar aus. |
| `systemd sync` | Generiert und aktiviert `systemd --user`-Timer für alle zeitgesteuerten Paare. |
| `systemd status` | Zeigt den Zustand aller systemd-Timer an. |
| `systemd remove` | Entfernt alle ProtonSyncUI systemd-Timer und Services. |
| `logs` | Gibt die neuesten Einträge aus der Protokolldatei aus. |
| `autostart on\|off\|status` | Schaltet den Start bei der Anmeldung (`--window`: mit sichtbarem Fenster). |
| `update [--check]` | Sucht nach einer neuen Version und installiert sie (`--check`: nur prüfen). |
| `doctor` | Prüft CLI, Anmeldung, systemd und Datenbank. |

---

## 2. Befehlsdetails

### `proton-sync-ui status`
Gibt eine Zusammenfassung des Synchronisationszustands aller konfigurierten Sync-Paare aus.

```bash
proton-sync-ui status
```

**Beispielausgabe:**
```text
Sync-Paare Status:
  ● Dokumente (UUID: 40779454-c7ca-4346-a8d0-48e0163c1180)
    Modus:     2-Wege (Cloud ⇄ Lokal)
    Lokal:     /home/user/Dokumente
    Remote:    /my-files/Dokumente
    Status:    Aktuell (Letzter Sync: vor 12 Minuten, 0 Fehler)
    Zeitplan:  Intervall (alle 60 Min)
```

---

### `proton-sync-ui list`
Listet alle konfigurierten Ordnerpaare tabellarisch auf.

```bash
proton-sync-ui list
```

---

### `proton-sync-ui run <IDENTIFIER>`
Startet die sofortige Synchronisation des angegebenen Sync-Paars. Als Identifier kann der Name oder die vollständige bzw. gekürzte UUID übergeben werden.

```bash
# Nach Name ausführen
proton-sync-ui run "Dokumente"

# Nach UUID ausführen
proton-sync-ui run 40779454-c7ca-4346-a8d0-48e0163c1180
```

---

### `proton-sync-ui dry-run <IDENTIFIER>`
Simuliert die Synchronisation und gibt aus, welche Dateien hoch- oder heruntergeladen würden. Es werden **keine** Dateien auf der Festplatte oder in Proton Drive modifiziert.

```bash
proton-sync-ui dry-run "Dokumente"
```

---

### `proton-sync-ui systemd <SUBCOMMAND>`
Verwaltet die native systemd User-Timer-Integration.

```bash
# Timer für alle aktiven Intervall-Paare einrichten/aktualisieren
proton-sync-ui systemd sync

# Status der systemd-Timer prüfen
proton-sync-ui systemd status

# Alle erstellten Timer und Services rückstandslos entfernen
proton-sync-ui systemd remove
```

---

### `proton-sync-ui logs`
Gibt die letzten Zeilen der zentralen Logdatei im Terminal aus (unterstützt `-n` zur Steuerung der Zeilenanzahl).

```bash
# Die letzten 50 Zeilen anzeigen
proton-sync-ui logs -n 50
```

---

## 3. Exit-Codes & Scripting

ProtonSyncUI verwendet standardisierte Exit-Codes für den Einsatz in CI/CD-Pipelines und Shell-Skripten:

| Exit-Code | Bedeutung | Beschreibung |
|---|---|---|
| `0` | **Erfolg (Success)** | Der Lauf wurde vollständig und ohne Fehler abgeschlossen. |
| `1` | **Teilweiser Fehler (Partial Failure)** | Der Lauf wurde abgeschlossen, aber einzelne Dateien konnten nicht übertragen werden (Details im Log). |
| `2` | **Schwerwiegender Fehler (Fatal Error)** | Der Lauf konnte nicht gestartet werden (z. B. CLI nicht angemeldet, Ordner nicht gefunden). |
| `3` | **Gesperrt (Locked)** | Ein anderer Prozess führt für dieses Sync-Paar bereits eine Synchronisation aus. |

### Beispiel für Shell-Skripte:

```bash
#!/usr/bin/env bash
set -e

echo "Starte Backup via ProtonSyncUI..."
if proton-sync-ui run "Backup"; then
    echo "Backup erfolgreich abgeschlossen!"
else
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 1 ]; then
        echo "Warnung: Einige Dateien konnten nicht übertragen werden."
    elif [ $EXIT_CODE -eq 3 ]; then
        echo "Hinweis: Synchronisation läuft bereits im Hintergrund."
    else
        echo "Fehler: Synchronisation fehlgeschlagen (Code: $EXIT_CODE)." >&2
        exit $EXIT_CODE
    fi
fi
```

---

## 4. Headless Server & Cron-Nutzung

ProtonSyncUI benötigt zur Ausführung der CLI **kein laufendes X11 oder Wayland**. 

### Betrieb ohne offene Benutzersitzung (systemd Linger)
Damit Hintergrund-Timer auch dann feuern, wenn du nicht am System angemeldet bist:

```bash
loginctl enable-linger $USER
```
