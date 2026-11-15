-- Schema von ProtonSyncUI.
--
-- Enthaelt ausschliesslich Synchronisationszustand: Pfade, Groessen,
-- Zeitstempel und Pruefsummen. Es werden keine Zugangsdaten, Tokens oder
-- Schluessel gespeichert -- die Anmeldung verwaltet ausschliesslich die
-- Proton-Drive-CLI.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

-- Konfigurierte Sync-Paare.
CREATE TABLE IF NOT EXISTS sync_pairs (
    uid                 TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    local_path          TEXT NOT NULL,
    remote_path         TEXT NOT NULL,
    enabled             INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    sync_mode           TEXT NOT NULL DEFAULT 'bidirectional'
                        CHECK (sync_mode IN ('bidirectional', 'upload_only', 'download_only')),
    schedule_kind       TEXT NOT NULL DEFAULT 'manual'
                        CHECK (schedule_kind IN ('manual', 'interval')),
    interval_minutes    INTEGER,
    exclude_patterns    TEXT NOT NULL DEFAULT '',
    max_file_size_bytes INTEGER,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    CHECK (schedule_kind <> 'interval' OR interval_minutes IS NOT NULL)
);

-- Zuletzt erfolgreich synchronisierter Zustand je Datei.
-- Ein Eintrag hier bedeutet: "diese Fassung liegt synchron vor".
CREATE TABLE IF NOT EXISTS file_states (
    pair_uid      TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    mtime_ns      INTEGER NOT NULL,
    sha256        TEXT,
    remote_path   TEXT NOT NULL,
    remote_mtime  TEXT,
    uploaded_at   TEXT NOT NULL,
    -- 1 = lokal geloescht, Cloud-Kopie bleibt bestehen ("Grabstein").
    -- Verhindert, dass die Datei beim naechsten Lauf erneut heruntergeladen
    -- wird, solange sich die Cloud-Fassung nicht aendert.
    deleted       INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1)),
    PRIMARY KEY (pair_uid, relative_path),
    FOREIGN KEY (pair_uid) REFERENCES sync_pairs (uid) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_file_states_pair ON file_states (pair_uid);

-- Historie der Laeufe.
CREATE TABLE IF NOT EXISTS runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_uid         TEXT NOT NULL,
    dry_run          INTEGER NOT NULL DEFAULT 0 CHECK (dry_run IN (0, 1)),
    status           TEXT NOT NULL,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    planned_files    INTEGER NOT NULL DEFAULT 0,
    uploaded_files   INTEGER NOT NULL DEFAULT 0,
    downloaded_files INTEGER NOT NULL DEFAULT 0,
    failed_files     INTEGER NOT NULL DEFAULT 0,
    skipped_files    INTEGER NOT NULL DEFAULT 0,
    local_deletions  INTEGER NOT NULL DEFAULT 0,
    uploaded_bytes   INTEGER NOT NULL DEFAULT 0,
    downloaded_bytes INTEGER NOT NULL DEFAULT 0,
    message          TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (pair_uid) REFERENCES sync_pairs (uid) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_runs_pair_started ON runs (pair_uid, started_at DESC);

-- Fehler einzelner Dateien. Ein Lauf wird davon nicht abgebrochen.
CREATE TABLE IF NOT EXISTS run_errors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    message       TEXT NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 1,
    permanent     INTEGER NOT NULL DEFAULT 0 CHECK (permanent IN (0, 1)),
    FOREIGN KEY (run_id) REFERENCES runs (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_run_errors_run ON run_errors (run_id);

-- Sperre gegen gleichzeitige Laeufe desselben Paars.
CREATE TABLE IF NOT EXISTS run_locks (
    pair_uid       TEXT PRIMARY KEY,
    pid            INTEGER NOT NULL,
    boot_id        TEXT NOT NULL,
    pid_start_time INTEGER NOT NULL,
    acquired_at    TEXT NOT NULL,
    source         TEXT NOT NULL DEFAULT 'unknown',
    FOREIGN KEY (pair_uid) REFERENCES sync_pairs (uid) ON DELETE CASCADE
);
