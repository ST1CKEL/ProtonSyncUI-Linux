# systemd-Integration im Detail

ProtonSyncUI nutzt ausschließlich **`systemd --user`**. Es werden keine
System-Units geschrieben und keine Root-Rechte benötigt.

## Aufbau

| Datei | Art | Zweck |
|---|---|---|
| `proton-sync-ui@.service` | statisch, einmal installiert | Führt einen Lauf aus; `%i` ist die UUID des Sync-Paars |
| `proton-sync-ui@<UUID>.timer` | je Sync-Paar erzeugt | Trägt das paarspezifische Intervall |

Warum diese Aufteilung: Der Service ist für alle Paare identisch, nur das
Intervall unterscheidet sich. Ein Template-Service plus generierte Timer hält
die Zahl der Dateien klein und `daemon-reload`-Zyklen selten.

Beide liegen unter `~/.config/systemd/user/` (bzw. unter
`$XDG_CONFIG_HOME/systemd/user/`, falls gesetzt).

**Der Service ruft die Kommandozeile auf, nie die grafische Oberfläche.**

## Verwaltung über ProtonSyncUI

```bash
proton-sync-ui systemd sync     # Units schreiben, daemon-reload, aktivieren
proton-sync-ui systemd status   # Zustand aller verwalteten Timer
proton-sync-ui systemd remove   # alle Units entfernen
```

`systemd sync` legt Timer **nur** für Paare an, die aktiviert sind **und**
einen Intervall-Zeitplan haben. Timer deaktivierter oder gelöschter Paare
werden entfernt. Fremde Units im selben Verzeichnis werden nie angefasst –
verwaltet wird ausschließlich, was mit `proton-sync-ui@` beginnt.

## Verwaltung von Hand

```bash
systemctl --user daemon-reload                                  # nach jeder Änderung
systemctl --user enable --now proton-sync-ui@<UUID>.timer        # aktivieren
systemctl --user disable --now proton-sync-ui@<UUID>.timer       # deaktivieren
systemctl --user start proton-sync-ui@<UUID>.service             # sofort ausführen
systemctl --user status proton-sync-ui@<UUID>.service            # Zustand
systemctl --user list-timers 'proton-sync-ui@*'                  # nächste Läufe
```

## Protokolle

```bash
journalctl --user -u proton-sync-ui@<UUID>.service
journalctl --user -u proton-sync-ui@<UUID>.service -f            # mitlaufen
journalctl --user -u proton-sync-ui@<UUID>.service -n 50 --no-pager
journalctl --user -u 'proton-sync-ui@*' --since today            # alle Paare
journalctl --user -u 'proton-sync-ui@*' -p warning               # nur Probleme
```

## Ohne offene Sitzung laufen lassen

```bash
loginctl enable-linger $USER
```

Ohne Linger beendet systemd die Benutzerinstanz beim Abmelden, und Timer
feuern nicht.

**Einschränkung:** Die Proton-Drive-CLI verwaltet ihre Anmeldung selbst. Liegt
diese in einem Schlüsselbund, der erst beim grafischen Anmelden entsperrt
wird, kann ein Lauf ohne aktive Sitzung an der fehlenden Entsperrung
scheitern. ProtonSyncUI meldet in dem Fall sauber „nicht angemeldet" und
beendet sich, statt zu hängen – die Dateien bleiben für den nächsten Lauf
vorgemerkt. Das liegt außerhalb des Einflussbereichs dieser Anwendung.

## Gestaltungsentscheidungen

**`OnUnitInactiveSec` statt `OnUnitActiveSec`.** Der Abstand wird ab dem
*Ende* des letzten Laufs gemessen. Ein Lauf, der länger dauert als das
Intervall, kann sich damit nicht mit dem nächsten überschneiden.

**`Type=oneshot` und `TimeoutStartSec=infinity`.** Ein Backup-Lauf über eine
langsame Leitung darf beliebig lange dauern, ohne abgeschossen zu werden.

**`SuccessExitStatus=0 1`.** Beendigungscode 1 bedeutet „gelaufen, aber
einzelne Dateien sind fehlgeschlagen". Das ist ein Ergebnis, kein Defekt der
Unit – die Einzelheiten stehen im Protokoll. Nur Code 2 und höher markieren
die Unit als `failed`.

**`Nice=10`, `IOSchedulingClass=idle`, `CPUSchedulingPolicy=idle`.** Ein
Hintergrund-Backup soll die interaktive Arbeit nicht ausbremsen.

**Kein `ProtectHome`/`PrivateHome`.** Die Proton-Drive-CLI legt ihre
Anmeldedaten im Benutzerverzeichnis ab und braucht den Sitzungsbus. Ein
strenges Sandboxing würde die Anmeldung unbrauchbar machen. `NoNewPrivileges`
ist gesetzt, weil es keine solchen Nebenwirkungen hat.

**Absoluter Pfad in `ExecStart`.** systemd-Units erben den PATH einer
Login-Shell nicht. ProtonSyncUI trägt deshalb den ermittelten absoluten Pfad
der Kommandozeile ein – das funktioniert auch bei Installation in einer
virtuellen Umgebung.

## Parallele Läufe

Zusätzlich zur Timer-Logik verhindert eine Sperre in der SQLite-Datenbank,
dass zwei Läufe desselben Sync-Paars gleichzeitig arbeiten – unabhängig davon,
ob der Anstoß aus der Oberfläche oder von systemd kommt. Der zweite Lauf
beendet sich mit Code 3 und einer Meldung.

Verwaiste Sperren nach einem Absturz werden über Boot-Kennung, Prozess-ID und
Prozess-Startzeit erkannt und automatisch entfernt. Es bleibt keine Sperrdatei
zurück, die von Hand gelöscht werden müsste.
