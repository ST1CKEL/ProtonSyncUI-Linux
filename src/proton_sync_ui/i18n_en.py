"""English catalogue: German source text -> English.

Generated together with the call sites; tests/test_i18n.py checks that every
tr() key used in the code has an entry here."""

from __future__ import annotations

ENGLISH: dict[str, str] = {
    "Die Proton-Drive-CLI ist nicht angemeldet. Bitte einmalig 'proton-drive auth login' im Terminal ausfuehren.": (
        "The Proton Drive CLI is not signed in. Please run 'proton-drive auth login' once in a terminal."
    ),
    "Die CLI endete mit Code {0}.": "The CLI exited with code {0}.",
    "Das Programm 'proton-drive' wurde nicht gefunden.\n\nProtonSyncUI benoetigt die offizielle Proton-Drive-Kommandozeile. Bitte installiere sie und stelle sicher, dass sie im PATH liegt (haeufig ~/.local/bin). Danach einmalig anmelden mit:\n\n    proton-drive auth login": (
        "The program 'proton-drive' was not found.\n\nProtonSyncUI needs the official Proton Drive command line. Please install it and make sure it is on your PATH (often ~/.local/bin). Then sign in once with:\n\n    proton-drive auth login"
    ),
    "Die Proton-Drive-CLI wurde unter '{0}' nicht gefunden oder ist nicht ausfuehrbar.": (
        "The Proton Drive CLI was not found at '{0}' or is not executable."
    ),
    "Der CLI-Aufruf hat das Zeitlimit von {0:.0f} Sekunden ueberschritten und wurde beendet.": (
        "The CLI call exceeded the time limit of {0:.0f} seconds and was stopped."
    ),
    "Die Proton-Drive-CLI ist nicht angemeldet.\n\nBitte in ProtonSyncUI unter Einstellungen auf 'Anmelden' klicken oder im Terminal ausfuehren:\n\n    proton-drive auth login\n\nDie Anmeldung oeffnet einen Browser. ProtonSyncUI verarbeitet dabei keinerlei Zugangsdaten.": (
        "The Proton Drive CLI is not signed in.\n\nClick 'Sign in' under Settings in ProtonSyncUI or run in a terminal:\n\n    proton-drive auth login\n\nSigning in opens a browser. ProtonSyncUI never handles any credentials."
    ),
    "proton-drive nicht gefunden": "proton-drive not found",
    "angemeldet": "signed in",
    "nicht angemeldet": "not signed in",
    "Die CLI antwortet nicht wie erwartet: {0}": "The CLI does not respond as expected: {0}",
    "Der Anmeldezustand konnte nicht geprueft werden: {0}": (
        "The sign-in state could not be checked: {0}"
    ),
    "Upload (neu)": "Upload (new)",
    "Upload (geaendert)": "Upload (changed)",
    "Download (neu)": "Download (new)",
    "Download (geaendert)": "Download (changed)",
    "Konflikt (lokal umbenannt)": "Conflict (local copy renamed)",
    "Unveraendert": "Unchanged",
    "Ausgeschlossen": "Excluded",
    "Zu gross": "Too large",
    "Name nicht unterstuetzt": "Name not supported",
    "Nicht lesbar": "Not readable",
    "Proton Doc/Sheet (nicht downloadbar)": "Proton Doc/Sheet (cannot be downloaded)",
    "Cloud-Stand unbekannt": "Cloud state unknown",
    "Lokal geloescht": "Deleted locally",
    "Keine Uebertragungen noetig": "No transfers needed",
    "Download: {0} neu, {1} geaendert": "Download: {0} new, {1} changed",
    "Upload: {0} neu, {1} geaendert": "Upload: {0} new, {1} changed",
    "{0} uebersprungen": "{0} skipped",
    "{0} lokal geloescht": "{0} deleted locally",
    "Inaktiv": "Idle",
    "Wartet": "Waiting",
    "Laeuft": "Running",
    "Erfolgreich": "Successful",
    "Warnung": "Warning",
    "Fehler": "Error",
    "Deaktiviert": "Disabled",
    "Abgebrochen": "Cancelled",
    "Lauf": "Run",
    "geplant: {0}": "planned: {0}",
    "uebertragen: {0} ({1} empfangen, {2} gesendet)": "transferred: {0} ({1} received, {2} sent)",
    "fehlgeschlagen: {0}": "failed: {0}",
    "uebersprungen: {0}": "skipped: {0}",
    "Dauer: {0:.1f}s": "Duration: {0:.1f}s",
    "uebertragen: {0} heruntergeladen": "transferred: {0} downloaded",
    "uebertragen: {0}": "transferred: {0}",
    "2-Wege-Synchronisation (Cloud ⇄ Lokal)": "Two-way sync (Cloud ⇄ Local)",
    "Nur Upload (Lokal ➔ Cloud)": "Upload only (Local ➔ Cloud)",
    "Nur Download (Cloud ➔ Lokal)": "Download only (Cloud ➔ Local)",
    "Der Proton-Drive-Zielpfad darf nicht leer sein.": (
        "The Proton Drive target path must not be empty."
    ),
    "Der Zielpfad enthaelt nicht darstellbare Steuerzeichen.": (
        "The target path contains control characters that cannot be displayed."
    ),
    "Backslashes werden im Zielpfad nicht unterstuetzt. Bitte verwende Ordnernamen ohne '\\'.": (
        "Backslashes are not supported in the target path. Please use folder names without '\\'."
    ),
    "Der Zielpfad darf keine Bestandteile '.' oder '..' enthalten.": (
        "The target path must not contain the components '.' or '..'."
    ),
    "Der lokale Quellordner darf nicht leer sein.": "The local source folder must not be empty.",
    "Der lokale Quellordner muss ein absoluter Pfad sein.": (
        "The local source folder must be an absolute path."
    ),
    "Der Quellordner ist ein symbolischer Link. Bitte waehle den tatsaechlichen Ordner aus -- Symlinks werden nicht synchronisiert.": (
        "The source folder is a symbolic link. Please choose the actual folder -- symlinks are not synchronized."
    ),
    "Das Wurzelverzeichnis '/' ist als Quellordner nicht zulaessig.": (
        "The root directory '/' is not allowed as a source folder."
    ),
    "Der Anzeigename darf nicht leer sein.": "The display name must not be empty.",
    "Das Groessenlimit pro Datei muss groesser als 0 sein.": (
        "The size limit per file must be greater than 0."
    ),
    "Der Zielpfad muss absolut sein und mit '/' beginnen, z. B. {0}/Backup.": (
        "The target path must be absolute and start with '/', e.g. {0}/Backup."
    ),
    "Der Zielpfad darf nicht das Wurzelverzeichnis '/' sein. Waehle einen Ordner unterhalb von {0}.": (
        "The target path must not be the root directory '/'. Choose a folder below {0}."
    ),
    "'{0}' ist kein bekannter Proton-Drive-Bereich. Moegliche Ziele: {1}.": (
        "'{0}' is not a known Proton Drive section. Possible targets: {1}."
    ),
    "In den Bereich '{0}' darf ProtonSyncUI nicht hochladen. Moegliche Ziele: {1}.": (
        "ProtonSyncUI must not upload to the section '{0}'. Possible targets: {1}."
    ),
    "Bitte waehle einen Unterordner in '{0}', nicht den Bereich selbst.": (
        "Please choose a subfolder in '{0}', not the section itself."
    ),
    "Fuer den Zeitplan 'Intervall' fehlt die Angabe in Minuten.": (
        "The schedule 'Interval' is missing its number of minutes."
    ),
    "Der Ordnername '{0}' enthaelt nicht unterstuetzte Zeichen.": (
        "The folder name '{0}' contains unsupported characters."
    ),
    "Der Ordner '{0}' existiert nicht.": "The folder '{0}' does not exist.",
    "'{0}' ist kein Ordner.": "'{0}' is not a folder.",
    "Das Intervall muss zwischen {0} und {1} Minuten liegen.": (
        "The interval must be between {0} and {1} minutes."
    ),
    "nie": "never",
    "Fuer dieses Sync-Paar laeuft bereits ein Durchgang (Prozess {0}, gestartet {1:%H:%M:%S}, Quelle: {2}).": (
        "A run is already in progress for this sync pair (process {0}, started {1:%H:%M:%S}, source: {2})."
    ),
    "Vorbereitung": "Preparing",
    "Ordner wird gelesen": "Reading folder",
    "Lokaler Ordner wird gelesen": "Reading local folder",
    "Proton Drive wird gelesen": "Reading Proton Drive",
    "Plan wird erstellt": "Building plan",
    "Verzeichnisse werden vorbereitet": "Preparing directories",
    "Dateien werden heruntergeladen": "Downloading files",
    "Dateien werden hochgeladen": "Uploading files",
    "Abschluss": "Finishing",
    "Fertig": "Done",
    "Der Lauf wurde abgebrochen.": "The run was cancelled.",
    "Die Proton-Drive-CLI ist nicht angemeldet.": "The Proton Drive CLI is not signed in.",
    "Lokale Dateien werden gesucht": "Looking for local files",
    "Plan wird berechnet": "Calculating plan",
    "Lokaler Schreibfehler": "Local write error",
    "CLI wird geprueft": "Checking CLI",
    "Der Quellordner '{0}' existiert nicht (mehr).": (
        "The source folder '{0}' does not exist (any more)."
    ),
    "Dry-Run: {0}": "Dry run: {0}",
    "{0} -- {1} Datei(en) zurueckgestellt, weil Cloud-Ordner nicht gelesen werden konnten": (
        "{0} -- {1} file(s) deferred because cloud folders could not be read"
    ),
    "Proton-Drive-Dateien werden gesucht": "Looking for Proton Drive files",
    "Zielordner werden geprueft": "Checking target folders",
    "Die CLI hat den Download gemeldet, aber keine Datei geliefert.": (
        "The CLI reported the download but delivered no file."
    ),
    "Die Datei ist seit dem Scan verschwunden.": "The file disappeared after the scan.",
    "{0} Dateien in Folge sind fehlgeschlagen; der Lauf wurde beendet. Letzter Fehler: {1}": (
        "{0} files failed in a row; the run was stopped. Last error: {1}"
    ),
    "Fehler bei der Planerstellung: {0}": "Error while building the plan: {0}",
    "Unerwarteter Fehler waehrend der Uebertragung: {0}": (
        "Unexpected error during the transfer: {0}"
    ),
    "Proton Drive konnte nicht gelesen werden: {0}": "Proton Drive could not be read: {0}",
    "Lokale Fassung konnte nicht gesichert werden": "The local copy could not be backed up",
    "{0} -- {1} von {2} Datei(en) wurden zuvor uebertragen.": (
        "{0} -- {1} of {2} file(s) were transferred before that."
    ),
    "Lokaler Dateifehler: {0}": "Local file error: {0}",
    "Cloud-Dateien werden gesucht ({0} Ordner, {1} Dateien)": (
        "Looking for cloud files ({0} folders, {1} files)"
    ),
    "Inhalt laut Pruefsumme geaendert.": "Content changed according to checksum.",
    "Lokal und remote synchron.": "Local and remote in sync.",
    "Konflikt: Beidseitig geaendert. Lokale Version wird archiviert.": (
        "Conflict: changed on both sides. The local version is archived."
    ),
    "Aenderungszeit abweichend, keine gespeicherte Pruefsumme zum Vergleich.": (
        "Modification time differs, no stored checksum to compare."
    ),
    "Aenderungszeit abweichend, Inhalt laut Pruefsumme identisch.": (
        "Modification time differs, content identical according to checksum."
    ),
    "Noch nicht hochgeladen.": "Not uploaded yet.",
    "Unveraendert.": "Unchanged.",
    "In der Cloud neu vorhanden.": "New in the cloud.",
    "In der Cloud geaendert.": "Changed in the cloud.",
    "Cloud-Ordner konnte nicht gelesen werden; Datei wird zurueckgestellt.": (
        "Cloud folder could not be read; the file is deferred."
    ),
    "Lokal geloescht (Kopie bei Proton Drive bleibt bestehen).": (
        "Deleted locally (the copy on Proton Drive stays)."
    ),
    "Nur lokal vorhanden (Download-Modus).": "Only present locally (download mode).",
    "Beidseitig vorhanden mit gleicher Groesse.": "Present on both sides with the same size.",
    "Initialer Abgleich mit abweichender Groesse: lokale Fassung wird gesichert, Cloud-Fassung uebernommen.": (
        "Initial comparison with different sizes: the local copy is backed up, the cloud copy is taken."
    ),
    "In der Cloud und lokal geaendert: lokale Fassung wird gesichert.": (
        "Changed in the cloud and locally: the local copy is backed up."
    ),
    "Lokal neu angelegt.": "Newly created locally.",
    "Datei existiert weder lokal noch remote.": "File exists neither locally nor remotely.",
    "{0}: Pruefsumme nicht berechenbar ({1}).": "{0}: checksum cannot be computed ({1}).",
    "Groesse geaendert: {0} -> {1} Bytes.": "Size changed: {0} -> {1} bytes.",
    "Lokal unveraendert.": "Unchanged locally.",
    "Lokal geloescht (Cloud-Kopie bleibt unberuehrt).": (
        "Deleted locally (the cloud copy is left untouched)."
    ),
    "Pruefsumme nicht berechenbar: {0}": "Checksum cannot be computed: {0}",
    "Nach der lokalen Loeschung in der Cloud geaendert.": (
        "Changed in the cloud after the local deletion."
    ),
    "Lokal geloescht; die Cloud-Kopie bleibt erhalten.": "Deleted locally; the cloud copy is kept.",
    "Name enthaelt nicht unterstuetzte Zeichen.": "Name contains unsupported characters.",
    "Proton Docs und Sheets koennen nicht ueber die CLI heruntergeladen werden.": (
        "Proton Docs and Sheets cannot be downloaded through the CLI."
    ),
    "Durch Ausschlussregel ausgenommen.": "Excluded by an exclusion rule.",
    "Dateigroesse ueberschreitet Limit.": "File size exceeds the limit.",
    "Entfernter Ordner durch Ausschlussregel ausgenommen.": (
        "Remote folder excluded by an exclusion rule."
    ),
    "Der Name enthaelt Zeichen, die die Proton-Drive-CLI nicht eindeutig verarbeiten kann (z. B. Backslash).": (
        "The name contains characters the Proton Drive CLI cannot process unambiguously (e.g. backslash)."
    ),
    "Keine Leseberechtigung.": "No read permission.",
    "Symbolische Links werden nicht synchronisiert.": "Symbolic links are not synchronized.",
    "Keine regulaere Datei.": "Not a regular file.",
    "{0} ueberschreitet das Limit von {1}.": "{0} exceeds the limit of {1}.",
    "Verzeichnis durch Ausschlussregel ausgenommen.": "Directory excluded by an exclusion rule.",
    "Dateiinformationen nicht lesbar: {0}": "File information not readable: {0}",
    "2-Wege-Synchronisation und Backups mit Proton Drive.\nProtonSyncUI steuert ausschliesslich die offizielle proton-drive-CLI. Bei Proton Drive wird niemals etwas geloescht.": (
        "Two-way sync and backups with Proton Drive.\nProtonSyncUI only drives the official proton-drive CLI. Nothing is ever deleted on Proton Drive."
    ),
    "Entwickelt von": "Developed by",
    "Entwickler": "Developer",
    "Projektseite": "Project page",
    "Quelltext und Dokumentation bei GitHub": "Source code and documentation on GitHub",
    "Fehler melden": "Report an issue",
    "Problem oder Wunsch einreichen": "File a problem or a request",
    "Lizenz": "License",
    "MIT-Lizenz -- freie Software": "MIT License -- free software",
    "Copyright © 2026 ProtonSyncUI Contributors\n\nHiermit wird jeder Person, die eine Kopie dieser Software und der zugehoerigen Dokumentation erhaelt, kostenlos die Erlaubnis erteilt, uneingeschraenkt mit der Software zu handeln -- einschliesslich der Rechte, sie zu nutzen, zu kopieren, zu aendern, zusammenzufuehren, zu veroeffentlichen, zu verbreiten, zu unterlizenzieren und zu verkaufen --, sofern der Urheberrechtsvermerk und dieser Erlaubnishinweis in allen Kopien enthalten sind.\n\nDIE SOFTWARE WIRD OHNE JEDE GEWAEHRLEISTUNG BEREITGESTELLT. Massgeblich ist der englische Originaltext der MIT-Lizenz in der Datei LICENSE.": (
        'Copyright © 2026 ProtonSyncUI Contributors\n\nPermission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files, to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, provided that the copyright notice and this permission notice are included in all copies.\n\nTHE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND. The full text of the MIT License is in the LICENSE file.'
    ),
    "Ueber {0}": "About {0}",
    "Synchronisation und Backups mit Proton Drive ueber die offizielle CLI.": (
        "Sync and backups with Proton Drive through the official CLI."
    ),
    "Datei wurde sowohl lokal als auch bei Proton Drive geaendert.": (
        "The file was changed both locally and on Proton Drive."
    ),
    "Beide behalten (umbenennen)": "Keep both (rename)",
    "Lokale Fassung behalten": "Keep local version",
    "Cloud-Fassung behalten": "Keep cloud version",
    "Lokale Fassung": "Local version",
    "Proton-Drive-Fassung": "Proton Drive version",
    "Groesse: {0}": "Size: {0}",
    "Dry-Run (Vorschau)": "Dry run (preview)",
    "Im Dateimanager oeffnen": "Open in file manager",
    "Bearbeiten": "Edit",
    "Entfernen": "Remove",
    "manuell": "manual",
    " -- deaktiviert": " -- disabled",
    " (Dry-Run)": " (dry run)",
    "Jetzt synchronisieren": "Sync now",
    "Weitere Aktionen": "More actions",
    "Modus": "Mode",
    "Lokaler Ordner": "Local folder",
    "Proton-Drive-Ordner": "Proton Drive folder",
    "Zeitplan": "Schedule",
    "Letzter Lauf": "Last run",
    "Aktuell": "Up to date",
    "Synchronisiert…": "Syncing…",
    "Bereit": "Ready",
    "Noch kein Durchgang erfolgt": "No run yet",
    "alle {0} Minuten (systemd-Timer)": "every {0} minutes (systemd timer)",
    "Neu laden": "Reload",
    "Sichtbare Eintraege in die Zwischenablage kopieren": "Copy visible entries to the clipboard",
    "Protokoll": "Log",
    "Filtern…": "Filter…",
    "Keine Eintraege fuer die gewaehlten Filter.\n": "No entries for the selected filters.\n",
    "0 Eintraege": "0 entries",
    "Anzeigen:": "Show:",
    "Nur dieses Paar": "Only this pair",
    "{0} Eintraege": "{0} entries",
    "Protokoll – {0}": "Log – {0}",
    "Intervall in Minuten": "Interval in minutes",
    "Sync-Paar bearbeiten": "Edit sync pair",
    "Sync-Paar hinzufuegen": "Add sync pair",
    "Abbrechen": "Cancel",
    "Speichern": "Save",
    "Allgemein": "General",
    "Anzeigename": "Display name",
    "Synchronisationsmodus": "Sync mode",
    "Aktiviert": "Enabled",
    "Deaktivierte Paare laufen weder manuell noch per Zeitplan.": (
        "Disabled pairs run neither manually nor on a schedule."
    ),
    "Ordner-Pfade": "Folder paths",
    "Lokaler Ordner und zugehoeriger Ordner bei Proton Drive. Dateien bei Proton Drive werden niemals geloescht.": (
        "Local folder and its folder on Proton Drive. Files on Proton Drive are never deleted."
    ),
    "Noch nichts ausgewaehlt": "Nothing selected yet",
    "Auswaehlen…": "Choose…",
    "Proton-Drive-Pfad": "Proton Drive path",
    "Hinweis zum Proton-Drive-Pfad": "Note on the Proton Drive path",
    "Bei einem Intervall wird ein systemd-Timer im Benutzerkontext eingerichtet.": (
        "An interval sets up a systemd timer in your user session."
    ),
    "Ausloesung": "Trigger",
    "Groessenlimit pro Datei": "Size limit per file",
    "Groessere Dateien werden uebersprungen und protokolliert.": (
        "Larger files are skipped and logged."
    ),
    "Ausschlussregeln": "Exclusion rules",
    "Eine Regel pro Zeile, im Stil von .gitignore. Beispiele:\n*.tmp — alle temporaeren Dateien\ncache/ — den Ordner cache auf jeder Ebene\n/nur-oben.txt — nur im Wurzelverzeichnis\n!wichtig.tmp — Ausnahme von einer vorherigen Regel": (
        "One rule per line, in the style of .gitignore. Examples:\n*.tmp — all temporary files\ncache/ — the folder cache on every level\n/top-only.txt — only in the root directory\n!important.tmp — exception from an earlier rule"
    ),
    "Lokalen Quellordner waehlen": "Choose local source folder",
    "Der gewaehlte Ort liegt nicht im lokalen Dateisystem.": (
        "The chosen location is not on the local file system."
    ),
    "Bitte einen lokalen Quellordner auswaehlen.": "Please choose a local source folder.",
    "Absoluter Pfad, z. B. {0}/Dokumente. Fehlende Ordner werden automatisch angelegt.": (
        "Absolute path, e.g. {0}/Documents. Missing folders are created automatically."
    ),
    "Manuell": "Manual",
    "Alle X Minuten": "Every X minutes",
    "Zeigt, was uebertragen wuerde, ohne etwas zu uebertragen.": (
        "Shows what would be transferred without transferring anything."
    ),
    "Sync-Paar entfernen. Dateien bei Proton Drive bleiben erhalten.": (
        "Remove sync pair. Files on Proton Drive are kept."
    ),
    "Laeuft im Hintergrund (Zeitplan)": "Running in the background (schedule)",
    "Dateien": "Files",
    "Jetzt starten": "Start now",
    "Log anzeigen": "Show log",
    "Deaktivieren": "Disable",
    "Aktivieren": "Enable",
    "Vorbereitung…": "Preparing…",
    "geplant {0}": "planned {0}",
    "fehlgeschlagen {0}": "failed {0}",
    "uebersprungen {0}": "skipped {0}",
    "heruntergeladen {0}": "downloaded {0}",
    "hochgeladen {0}": "uploaded {0}",
    "{0} lokal geloescht (Proton Drive unveraendert)": (
        "{0} deleted locally (Proton Drive unchanged)"
    ),
    "Verstanden": "Got it",
    "Befehl kopieren": "Copy command",
    "Schliessen": "Close",
    "Proton-Drive-CLI nicht gefunden": "Proton Drive CLI not found",
    "Proton-Drive-CLI nicht angemeldet": "Proton Drive CLI not signed in",
    "Hinweis zur Proton-Drive-CLI": "Note on the Proton Drive CLI",
    "Alle jetzt synchronisieren": "Sync everything now",
    "Beenden": "Quit",
    "Nach Updates suchen": "Check for updates",
    "{0} oeffnen": "Open {0}",
    " (Dry-Run Vorschau)": " (dry run preview)",
    "Aktivitaeten aktualisieren": "Refresh activity",
    "Alle": "All",
    "Keine Aktivitaeten vorhanden": "No activity yet",
    "Sobald Synchronisationslaeufe stattfinden, werden sie hier aufgefuehrt.": (
        "Sync runs are listed here as soon as they take place."
    ),
    "Chronologischer Verlauf": "Chronological history",
    "Lauf vom {0}": "Run of {0}",
    "Uebertragene Daten": "Transferred data",
    "Zusammenfassung kopieren": "Copy summary",
    "ProtonSyncUI Lauf:\nStatus: {0}\nZeit: {1}\nMeldung: {2}\nDateien geplant: {3}, uebertragen: {4}\nUpload: {5} B, Download: {6} B": (
        "ProtonSyncUI run:\nStatus: {0}\nTime: {1}\nMessage: {2}\nFiles planned: {3}, transferred: {4}\nUpload: {5} B, download: {6} B"
    ),
    "Dauer": "Duration",
    "Lauf-Informationen kopiert.": "Run details copied.",
    "Dateien: {0} uebertragen / {1} geplant · Upload: {2} · Download: {3}": (
        "Files: {0} transferred / {1} planned · Upload: {2} · Download: {3}"
    ),
    "{0:.1f} Sekunden": "{0:.1f} seconds",
    "Alle: Beide behalten": "All: keep both",
    "Keine Konflikte vorhanden": "No conflicts",
    "Alle Dateien wurden erfolgreich synchronisiert.": "All files were synchronized successfully.",
    "Offene Dateikonflikte": "Open file conflicts",
    "Waehle fuer jede Datei, welche Version beibehalten werden soll.": (
        "Choose for each file which version to keep."
    ),
    "Konflikt '{0}' geloest.": "Conflict '{0}' resolved.",
    "{0} Konflikte geloest (Beide Versionen behalten).": (
        "{0} conflicts resolved (both versions kept)."
    ),
    "Systemdiagnose": "System diagnosis",
    "Ueberpruefe Hintergrunddienste und Systemd-Timer.": (
        "Check background services and systemd timers."
    ),
    "Systemd-Timer abgleichen": "Reconcile systemd timers",
    "Richtet Hintergrund-Timer fuer alle konfigurierten Intervalle ein.": (
        "Sets up background timers for all configured intervals."
    ),
    "Timer aktualisieren": "Update timers",
    "Diagnosebericht erstellen": "Create diagnostic report",
    "Kopiert System-, Versions- und Statusinformationen fuer Support.": (
        "Copies system, version and status information for support."
    ),
    "Bericht kopieren": "Copy report",
    "Protokolle und Logs": "Logs",
    "Detailprotokolle der Hintergrundprozesse.": "Detailed logs of the background processes.",
    "Logdatei oeffnen": "Open log file",
    "Ueber ProtonSyncUI": "About ProtonSyncUI",
    "2-Wege-Synchronisation mit Proton Drive · entwickelt von Stickelbroeck Labs": (
        "Two-way sync with Proton Drive · developed by Stickelbroeck Labs"
    ),
    "Info & Lizenz": "About & License",
    "Diagnosebericht in Zwischenablage kopiert.": "Diagnostic report copied to the clipboard.",
    "Alle synchronisieren": "Sync all",
    "Letzte Aktivitaeten": "Recent activity",
    "Die neuesten Uebertragungen und Ereignisse.": "The latest transfers and events.",
    "Alle Aktivitaeten anzeigen": "Show all activity",
    "Alles synchronisiert": "Everything is in sync",
    "Alle konfigurierten Ordner sind auf dem aktuellen Stand.": (
        "All configured folders are up to date."
    ),
    "Letzter Lauf: soeben": "Last run: just now",
    "Synchronisierung laeuft": "Sync in progress",
    "laeuft": "running",
    "Noch kein Durchgang ausgefuehrt": "No run yet",
    "Keine aktiven Sync-Paare zum Starten.": "No enabled sync pairs to start.",
    "Synchronisierung nicht moeglich": "Sync not possible",
    "Noch keine Aktivitaeten vorhanden": "No activity yet",
    "Unbekannt": "Unknown",
    "Waehle in der Konfliktansicht, welche Fassungen beibehalten werden sollen.": (
        "Choose in the conflict view which versions to keep."
    ),
    "Letzter Lauf: {0} · {1}": "Last run: {0} · {1}",
    "{0} Sync-Paar(e) gestartet.": "{0} sync pair(s) started.",
    "Noch kein Sync-Paar eingerichtet": "No sync pair set up yet",
    "Füge dein erstes Sync-Paar hinzu, um die Synchronisation zu starten.": (
        "Add your first sync pair to start synchronizing."
    ),
    "{0} Konflikt(e) erfordern Aufmerksamkeit": "{0} conflict(s) need attention",
    "Alle {0} Sync-Paare sind auf dem aktuellen Stand.": "All {0} sync pairs are up to date.",
    "Sync-Paare durchsuchen…": "Search sync pairs…",
    "Keine Sync-Paare gefunden": "No sync pairs found",
    "Lege ein neues Sync-Paar an, um Ordner mit Proton Drive abzugleichen.": (
        "Create a new sync pair to keep folders in sync with Proton Drive."
    ),
    "Sync-Paar anlegen": "Create sync pair",
    "Konfigurierte Ordnerpaare": "Configured folder pairs",
    "'{0}': Synchronisierung gestartet.": "'{0}': sync started.",
    "'{0}': Dry-Run gestartet.": "'{0}': dry run started.",
    "'{0}': Abbruch angefordert.": "'{0}': cancellation requested.",
    "Wird geprueft …": "Checking …",
    "Allgemein und Autostart": "General and autostart",
    "Systemintegration, Infobereich und Hintergrundstart.": (
        "System integration, system tray and background start."
    ),
    "Beim Anmelden automatisch starten": "Start automatically at login",
    "Startet ProtonSyncUI mit der Arbeitsflaeche (KDE Plasma, GNOME)": (
        "Starts ProtonSyncUI with the desktop (KDE Plasma, GNOME)"
    ),
    "Minimiert im Infobereich starten": "Start minimized in the system tray",
    "Beim Autostart nur das Symbol in der Kontrollleiste zeigen": (
        "Only show the tray icon when started at login"
    ),
    "Desktop-Benachrichtigungen": "Desktop notifications",
    "Bei fehlgeschlagenen Laeufen und verfuegbaren Updates benachrichtigen": (
        "Notify about failed runs and available updates"
    ),
    "Infobereich": "System tray",
    "Beim Schliessen des Fensters laeuft ProtonSyncUI im Infobereich weiter. Beenden ueber das Symbol-Menue oder Strg+Q.": (
        "When the window is closed, ProtonSyncUI keeps running in the system tray. Quit through the tray menu or Ctrl+Q."
    ),
    "Neue Versionen von ProtonSyncUI suchen und installieren.": (
        "Look for and install new versions of ProtonSyncUI."
    ),
    "Noch nicht nach Updates gesucht.": "Not checked for updates yet.",
    "Installieren": "Install",
    "Automatisch nach Updates suchen": "Check for updates automatically",
    "Hoechstens einmal taeglich; installiert wird erst nach Bestaetigung": (
        "At most once a day; nothing is installed without your confirmation"
    ),
    "Anmeldung und Zustand der offiziellen Proton-Drive-CLI.": (
        "Sign-in and state of the official Proton Drive CLI."
    ),
    "Verbindung": "Connection",
    "Anmelden": "Sign in",
    "Erneut pruefen": "Check again",
    "Neue CLI-Version verfuegbar": "New CLI version available",
    "Download-Seite": "Download page",
    "Datenschutz": "Privacy",
    "Keine Nutzungsdaten": "No usage data",
    "ProtonSyncUI arbeitet lokal und sendet keine Nutzungsdaten. Die Update-Suche ruft lediglich die aktuelle Versionsnummer bei GitHub ab; die Anmeldung geschieht ausschliesslich in der Proton-Drive-CLI.": (
        "ProtonSyncUI works locally and sends no usage data. The update check only fetches the current version number from GitHub; sign-in happens exclusively in the Proton Drive CLI."
    ),
    "Die Proton-Drive-CLI wurde nicht gefunden.": "The Proton Drive CLI was not found.",
    " (minimiert)": " (minimized)",
    "Installierte Version: {0}": "Installed version: {0}",
    "Autostart deaktiviert.": "Autostart disabled.",
    "Angemeldet (CLI {0}).": "Signed in (CLI {0}).",
    "CLI {0} gefunden; Anmeldezustand nicht pruefbar (keine Verbindung?).": (
        "CLI {0} found; sign-in state cannot be checked (no connection?)."
    ),
    "Autostart{0} aktiviert.": "Autostart{0} enabled.",
    "Autostart konnte nicht geaendert werden: {0}": "Autostart could not be changed: {0}",
    "Nicht angemeldet (CLI {0}).": "Not signed in (CLI {0}).",
    "Protokoll anzeigen": "Show log",
    "Zeitplaene aktualisieren": "Update schedules",
    "Uebersicht": "Overview",
    "Sync-Paare": "Sync pairs",
    "Aktivitaet": "Activity",
    "Konflikte": "Conflicts",
    "Einstellungen": "Settings",
    "Diagnose & Hilfe": "Diagnosis & Help",
    "Anmeldung im Terminal gestartet – bitte im Browser abschliessen.": (
        "Sign-in started in a terminal – please finish it in the browser."
    ),
    "Suche nach Updates …": "Checking for updates …",
    "Behalten": "Keep",
    "Jetzt installieren": "Install now",
    "Proton Drive ist nicht angemeldet": "Proton Drive is not signed in",
    "Letzter Lauf mit einzelnen Dateifehlern": "Last run had individual file errors",
    "Proton Drive ist angemeldet. Die Synchronisation startet.": (
        "Proton Drive is signed in. Synchronization starts."
    ),
    "Kein Terminalprogramm gefunden": "No terminal program found",
    "Bitte in einem Terminal ausfuehren:\n\n    proton-drive auth login": (
        "Please run in a terminal:\n\n    proton-drive auth login"
    ),
    "Bitte zuerst die laufende Synchronisierung abwarten.": (
        "Please wait for the running sync to finish first."
    ),
    "Spaeter": "Later",
    "Jetzt neu starten": "Restart now",
    "Die Installation ist fehlgeschlagen.": "The installation failed.",
    "Update fehlgeschlagen": "Update failed",
    "Entfernt werden nur die Konfiguration und der lokale Sync-Status.\n\nIhre Dateien bei Proton Drive und auf der Festplatte bleiben vollstaendig erhalten.": (
        "Only the configuration and the local sync state are removed.\n\nYour files on Proton Drive and on disk are kept completely."
    ),
    "Vorschau der Aktionen": "Preview of actions",
    "Geplante Datenmengen": "Planned data volume",
    "Der Lauf wurde fortgesetzt. Uebrige Dateien wurden uebertragen.": (
        "The run continued. The remaining files were transferred."
    ),
    "Proton Drive ist nicht angemeldet – es wird nichts synchronisiert.": (
        "Proton Drive is not signed in – nothing is being synchronized."
    ),
    "Die Update-Suche ist fehlgeschlagen (keine Verbindung?).": (
        "The update check failed (no connection?)."
    ),
    "Version {0} wird installiert …": "Installing version {0} …",
    "Update installiert": "Update installed",
    "Sync-Paar": "Sync pair",
    "'{0}' gespeichert.": "'{0}' saved.",
    "Unveraenderte oder ausgenommene Dateien.": "Unchanged or excluded files.",
    "Diese Dateien wurden lokal entfernt. Bei Proton Drive bleiben sie erhalten.": (
        "These files were removed locally. They are kept on Proton Drive."
    ),
    "Hinweise beim Einlesen": "Notes from scanning",
    "systemd nicht verfuegbar": "systemd not available",
    "'systemctl' wurde nicht gefunden. Hintergrund-Timer stehen nicht zur Verfuegung.": (
        "'systemctl' was not found. Background timers are not available."
    ),
    "Zeitplaene sind aktuell.": "Schedules are up to date.",
    "Zeitplan konnte nicht geschrieben werden": "Schedule could not be written",
    "Synchronisiert: {0}": "Syncing: {0}",
    "{0} Konflikt(e) zu klaeren": "{0} conflict(s) to resolve",
    "Update fuer ProtonSyncUI verfuegbar": "Update available for ProtonSyncUI",
    "ProtonSyncUI ist aktuell.": "ProtonSyncUI is up to date.",
    "Update-Suche fehlgeschlagen: {0}": "Update check failed: {0}",
    "Version {0} ist installiert – Neustart erforderlich.": (
        "Version {0} is installed – restart required."
    ),
    "Fehler: {0}": "Error: {0}",
    "'{0}' entfernen?": "Remove '{0}'?",
    "Dry-Run – {0}": "Dry run – {0}",
    "Downloads: {0} ({1}) · Uploads: {2} ({3}) · Uebersprungen: {4}": (
        "Downloads: {0} ({1}) · Uploads: {2} ({3}) · Skipped: {4}"
    ),
    "Lauf fuer '{0}'": "Run for '{0}'",
    "Fehler – {0}": "Errors – {0}",
    "{0} Datei(en) fehlgeschlagen": "{0} file(s) failed",
    "Fehler bei '{0}': {1}": "Error in '{0}': {1}",
    "ProtonSyncUI {0} ist verfuegbar (installiert: {1}).": (
        "ProtonSyncUI {0} is available (installed: {1})."
    ),
    "Version {0} ist verfuegbar.": "Version {0} is available.",
    "ProtonSyncUI ist aktuell (Version {0}).": "ProtonSyncUI is up to date (version {0}).",
    "ProtonSyncUI {0} wurde installiert. Die neue Version wird nach einem Neustart der Anwendung aktiv.": (
        "ProtonSyncUI {0} was installed. The new version becomes active after restarting the application."
    ),
    "'{0}': Synchronisierung erfolgreich abgeschlossen.": "'{0}': sync finished successfully.",
    "Sync-Paar '{0}' entfernt.": "Sync pair '{0}' removed.",
    "Uebersprungen ({0})": "Skipped ({0})",
    "Lokal geloescht ({0})": "Deleted locally ({0})",
    "Zeitplaene aktualisiert ({0} Aenderung(en)).": "Schedules updated ({0} change(s)).",
    "Lauf fehlgeschlagen": "Run failed",
    "'{0}': Synchronisierung fehlgeschlagen": "'{0}': sync failed",
    "Update auf Version {0} verfuegbar.": "Update to version {0} available.",
    "Version {0} kann in den Einstellungen installiert werden.": (
        "Version {0} can be installed in the settings."
    ),
    "'{0}': abgeschlossen, {1} Datei(en) fehlgeschlagen.": "'{0}': finished, {1} file(s) failed.",
    "{0} Versuch(e): {1}": "{0} attempt(s): {1}",
    "Das heruntergeladene Archiv enthaelt kein gueltiges install.sh.": (
        "The downloaded archive does not contain a valid install.sh."
    ),
    "Die Antwort des Servers ist unerwartet gross.": "The server response is unexpectedly large.",
    "Die Versionsnummer im Repository konnte nicht gelesen werden.": (
        "The version number in the repository could not be read."
    ),
    "'bash' wurde nicht gefunden; das Update kann nicht installiert werden.": (
        "'bash' was not found; the update cannot be installed."
    ),
    "Entpacke Archiv …": "Unpacking archive …",
    "Installiere …": "Installing …",
    "Version {0} wurde installiert.": "Version {0} was installed.",
    "Unsichere Adresse abgelehnt: {0}": "Insecure address rejected: {0}",
    "Lade Version {0} herunter …": "Downloading version {0} …",
    "Die Update-Suche ist fehlgeschlagen: {0}": "The update check failed: {0}",
    "Die Installation endete mit Code {0}:\n{1}": "The installation exited with code {0}:\n{1}",
    "Der Download ist fehlgeschlagen: {0}": "The download failed: {0}",
    "Das Archiv konnte nicht entpackt werden: {0}": "The archive could not be unpacked: {0}",
    "Die Installation ist fehlgeschlagen: {0}": "The installation failed: {0}",
    "Die Download-Seite von Proton hat ein unerwartetes Format.": (
        "Proton's download page has an unexpected format."
    ),
    "Pruefe SHA-512-Pruefsumme …": "Verifying SHA-512 checksum …",
    "Auf der Download-Seite von Proton fehlt ein Eintrag fuer {0}.": (
        "Proton's download page has no entry for {0}."
    ),
    "Die Pruefsumme des Downloads stimmt nicht mit der Angabe von Proton ueberein. Es wurde nichts installiert.": (
        "The checksum of the download does not match the one published by Proton. Nothing was installed."
    ),
    "Die heruntergeladene CLI laesst sich nicht starten. Es wurde nichts installiert.": (
        "The downloaded CLI cannot be started. Nothing was installed."
    ),
    "Proton-Drive-CLI {0} ist installiert.": "Proton Drive CLI {0} is installed.",
    "Fuer diese Plattform ({0}/{1}) bietet Proton keine CLI an.": (
        "Proton does not offer a CLI for this platform ({0}/{1})."
    ),
    "Lade Proton-Drive-CLI {0} herunter …": "Downloading Proton Drive CLI {0} …",
    "Installiere nach {0} …": "Installing to {0} …",
    "Die Download-Seite von Proton ist nicht erreichbar: {0}": (
        "Proton's download page cannot be reached: {0}"
    ),
    "Der Zielordner {0} kann nicht angelegt werden: {1}": (
        "The target folder {0} cannot be created: {1}"
    ),
    "Die CLI konnte nicht nach {0} geschrieben werden: {1}": (
        "The CLI could not be written to {0}: {1}"
    ),
    "Sprache geaendert": "Language changed",
    "Die neue Sprache wird nach einem Neustart der Anwendung verwendet.": (
        "The new language is used after restarting the application."
    ),
    "Sprache": "Language",
    "Gilt fuer Fenster, Infobereich und Benachrichtigungen": (
        "Applies to the window, system tray and notifications"
    ),
    "Aktualisieren": "Update",
    "Proton-Drive-CLI installieren": "Install Proton Drive CLI",
    "Laedt die aktuelle CLI von proton.me und prueft ihre SHA-512-Pruefsumme.": (
        "Downloads the current CLI from proton.me and verifies its SHA-512 checksum."
    ),
    "Automatisch (Sprache des Systems)": "Automatic (system language)",
    "Version {0} (installiert: {1}). Der Download von proton.me wird per SHA-512 geprueft; die Anmeldung bleibt erhalten.": (
        "Version {0} (installed: {1}). The download from proton.me is verified by SHA-512; you stay signed in."
    ),
    "Suche bei Proton nach der aktuellen CLI …": "Looking up the current CLI at Proton …",
    "Die Proton-Drive-CLI wird gerade von einem Sync-Lauf benutzt. Bitte nach dessen Ende erneut versuchen.": (
        "The Proton Drive CLI is currently in use by a sync run. Please try again once it has finished."
    ),
    "Proton-Drive-CLI": "Proton Drive CLI",
    "Die Proton-Drive-CLI ist aktuell.": "The Proton Drive CLI is up to date.",
    "Proton-Drive-CLI {0} wird heruntergeladen …": "Downloading Proton Drive CLI {0} …",
    "Version {0} steht bei Proton bereit.": "Version {0} is available from Proton.",
    "Die Proton-Drive-CLI ist aktuell (Version {0}).": (
        "The Proton Drive CLI is up to date (version {0})."
    ),
    "Quelle: proton.me (offizieller Download). Die SHA-512-Pruefsumme wird vor der Installation geprueft.\n\nZiel: {0}\nDie bisherige Fassung bleibt als {1} erhalten, die Anmeldung bei Proton Drive ebenfalls.": (
        "Source: proton.me (official download). The SHA-512 checksum is verified before installing.\n\nTarget: {0}\nThe previous version is kept as {1}, and you stay signed in to Proton Drive."
    ),
    "Proton-Drive-CLI {0} installieren?": "Install Proton Drive CLI {0}?",
    "Proton-Drive-CLI auf {0} aktualisieren?": "Update Proton Drive CLI to {0}?",
}

#: Texte, die in beiden Sprachen gleich lauten.
SAME_IN_BOTH: frozenset[str] = frozenset(
    {
        "Symlink",
        "Download: {0}",
        "Upload: {0}",
        "Debug",
        "Info",
        "Limit in MiB",
        "Filter:",
        "Downloads ({0})",
        "Uploads ({0})",
        "Download: {0} %",
    }
)
