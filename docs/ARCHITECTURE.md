# Architektur & Komponenten-Design von ProtonSyncUI

Dieses Dokument beschreibt die Architektur, Datenflüsse und Entwurfsmuster von **ProtonSyncUI (v0.2.0)**.

---

## 1. Schichtenarchitektur (Clean Architecture)

ProtonSyncUI folgt dem Prinzip der sauberen Schichtentrennung:

```
┌─────────────────────────────────────────────────────────────┐
│                    Präsentationsschicht                     │
│  (Adw.NavigationSplitView, Views, StatusBadge, PairCardRow)  │
└──────────────────────────────┬──────────────────────────────┘
                               │ Ruft Services auf
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                       Service-Schicht                       │
│  (SyncService, SyncPairRepository, ConflictService, Activity)│
└──────────────────────────────┬──────────────────────────────┘
                               │ Nutzt Kern-Module
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     Domänen- & Engine-Kern                  │
│   (SyncEngine, TwoWayPlanner, RemoteScanner, SQLite Repo)   │
└──────────────────────────────┬──────────────────────────────┘
                               │ Delegiert an CLI / OS
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  Infrastruktur & Adapter                    │
│      (ProtonDriveAdapter Subprocess, systemd User Manager)  │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Komponenten im Detail

### 1. Präsentationsschicht (`src/proton_sync_ui/ui/`)
* **`window.py`**: Zentrales Anwendungsfenster basierend auf `Adw.NavigationSplitView`. Bietet adaptive Breitenanpassung (Collapsible Sidebar auf schmalen Displays) und globale Toast-Benachrichtigungen.
* **`views/`**:
  * `overview_view.py`: Hero-Statuskarte, Schnellaktionen (*Alle synchronisieren*), Vorschau der letzten 5 Aktivitäten.
  * `pairs_view.py`: Listenverwaltung mit Suchfeld, Filter nach Status (Aktiv, Laufend, Deaktiviert) und Empty-State.
  * `conflicts_view.py`: Dediziertes Konflikt-Center mit 2-Spalten-Gegenüberstellung und Schnellauflösungs-Buttons.
  * `activity_view.py`: Chronologische Historie aller Durchgänge mit Statusfilter (Erfolgreich, Fehler, Dry-Run).
  * `settings_view.py`: Globale Einstellungen (Benachrichtigungen, Standardstrategie, Datenschutz, Live-CLI-Probe).
  * `diag_view.py`: Protokollansicht, systemd-Timer-Aktualisierung und Diagnosebericht.
* **`components/`**:
  * `status_badge.py`: Wiederverwendbares Pill-Badge (`StatusBadge`) für Statuszustände (`Aktuell`, `Synchronisiert…`, `Deaktiviert`, `Warnung`, `Fehler`).
  * `pair_card.py`: Boxed-Card-Darstellung mit Toggle-Switch, Direktsync und Detailausklapper.
  * `conflict_card.py`: Konfliktkarte mit Dateivergleich und Lösungsstrategien.

### 2. Service-Schicht (`src/proton_sync_ui/services/`)
* **`contracts.py`**: Definiert typisierte `Protocol`-Schnittstellen (`SyncService`, `SyncPairRepository`, `ActivityRepository`, `ConflictService`) und die Datenklasse `ConflictItem`.
* **`default_services.py`**: Konkrete Implementierungen, die den `AsyncRunner`, das `Repository` und das Dateisystem anbinden.

### 3. Synchronisations-Engine (`src/proton_sync_ui/sync/`)
* **`remote_scanner.py`**: Paralleler asynchroner Scanner (`asyncio.Queue` mit 8 Workern), der Cloud-Verzeichnisse rekursiv über `proton-drive filesystem list` erfasst und Live-Fortschrittstickets liefert.
* **`planner.py`**: Generiert den `UploadPlan` anhand von lokalem Dateisystem, Cloud-Zustand und SQLite-Datenbank.
* **`engine.py`**: Führt den generierten Plan aus:
  * Downloads via `proton-drive filesystem download`
  * Uploads via `proton-drive filesystem upload -f create-new-revision -d merge`
  * Konflikterkennung und Speicherung von Sicherungskopien (`.conflict-<timestamp>`).

### 4. Datenhaltung & Schema (`src/proton_sync_ui/storage/`)
* **SQLite (Schema-Version 2)**:
  * `pairs`: Stammdaten der Sync-Paare (Name, lokaler Pfad, Remote-Pfad, Modus, Intervall, Aktivierung).
  * `files`: Datei-Tracking mit mtime, sha256 und Cloud-Revisionen.
  * `runs`: Verlaufshistorie aller Durchgänge mit Kennzahlen, Dauer und Fehlerprotokollen.
  * `run_errors`: Detaillierte Fehlerberichte für einzelne Dateien.

---

## 3. Sicherheitsgarantien & Schutzmechanismen

1. **Kein Löschen entfernter Daten**:
   ProtonSyncUI führt niemals `delete`, `trash` oder `empty-trash` auf Proton Drive aus.
2. **Subprocess-Sicherheit**:
   Befehle werden niemals über eine Shell (`shell=False`) ausgeführt, sondern immer als feste Tokenliste übergeben.
3. **Log-Redaction**:
   Sensible Ausgaben (Tokens, Schlüssel, Passwörter) werden vor dem Schreiben in Logdateien automatisch geschwärzt (`redact()`).
4. **Schutz vor Mehrfachausführung**:
   Lokale Sperrmechanismen verhindern, dass derselbe Sync-Auftrag mehrfach parallel gestartet wird.
