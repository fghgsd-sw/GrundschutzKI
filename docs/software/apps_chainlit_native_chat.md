# Modul: `apps/chainlit/native_chat.py`

**Pfad:** [apps/chainlit/native_chat.py](../../apps/chainlit/native_chat.py)
**Schicht:** Persistenz- und Export-Layer der Chainlit-Anwendung
**Sprache:** Python 3.12, async

## Zweck

Implementiert die native PostgreSQL-Datenzugriffsschicht für Benutzerverwaltung, Schema-Bootstrap, Feedback-Persistenz und Datenexporte. Das Modul kapselt direkte `asyncpg`-Operationen auf den Chainlit-Tabellen (`User`, `Thread`, `Step`, `Element`, `Feedback`) und stellt dafür asynchrone Hilfsfunktionen mit klaren Verantwortlichkeiten bereit.

## Position im System

```
[apps/chainlit/app.py]
  auth/register/export/feedback routes
               │
               ▼
[apps/chainlit/native_chat.py]
  - ensure_native_schema()
  - user CRUD (read/create/check)
  - upsert_feedback()
  - export_all_chats_zip()
  - export_feedback_csv()
               │
               ▼
     PostgreSQL (Chainlit-Schema)
```

Die Datei wird zur **Laufzeit** von API- und Event-Flows in `app.py` aufgerufen. Jede Funktion öffnet eine eigene DB-Verbindung, führt die Operation aus und schließt die Verbindung deterministisch im `finally`-Block.

## Externe Abhängigkeiten

| Quelle | Verwendung |
|--------|-----------|
| `asyncpg` | Asynchrone PostgreSQL-Verbindungen und SQL-Ausführung |
| `csv` | CSV-Export für Chat- und Feedback-Daten |
| `json` | Serialisierung von Metadata-/Export-Payloads |
| `zipfile` | Verpackung mehrerer Exportdateien in ein ZIP-Bundle |
| `pathlib.Path` | Dateipfade und Zielverzeichnisse für Exporte |
| `datetime/timezone` | UTC-basierte Zeitstempel für Dateinamen |

## Aufrufer

| Aufrufer | Importierte Funktionen | Zweck |
|----------|------------------------|-------|
| [apps/chainlit/app.py](../../apps/chainlit/app.py) | `ensure_native_schema`, `create_user`, `check_user_exists`, `get_user_by_identifier`, `upsert_feedback`, `export_all_chats_zip`, `export_feedback_csv` | Registrierung/Login-nahe Flows, Schema-Initialisierung, Feedback-Speicherung und Download-Exporte |

## Öffentliche API

| Funktion | Signatur (gekürzt) | Zweck |
|----------|-------------------|-------|
| `ensure_native_schema` | `(database_url) -> None` | Führt idempotent das SQL-Schema inkl. Tabellen, Spalten-Migrationen und Indizes aus. |
| `create_user` | `(database_url, username, email, password_hash) -> dict \| None` | Legt lokalen Benutzer an; gibt bei Konflikt (`identifier`/`email`) `None` zurück. |
| `get_user_by_identifier` | `(database_url, identifier) -> dict \| None` | Lädt Benutzerdatensatz per `identifier`. |
| `get_user_by_email` | `(database_url, email) -> dict \| None` | Lädt Benutzerdatensatz per E-Mail-Adresse. |
| `check_user_exists` | `(database_url, username=None, email=None) -> dict[str, bool]` | Prüft separat, ob Username und/oder E-Mail bereits existieren. |
| `upsert_feedback` | `(database_url, *, feedback_id, step_id, value, comment=None) -> None` | Speichert oder aktualisiert Feedback je `stepId` (idempotent via Unique-Index + `ON CONFLICT`). |
| `export_all_chats_zip` | `(*, database_url, out_dir, user_id=None) -> Path` | Exportiert Threads + Steps nach JSONL und CSV und bündelt beide Dateien als ZIP. |
| `export_feedback_csv` | `(*, database_url, out_dir) -> Path` | Exportiert Feedback inkl. Nutzerfrage/Antwort-Kontext als CSV. |

## Interne Helfer (`_private`)

| Funktion | Zweck |
|----------|-------|
| `_stamp` | Erzeugt UTC-Zeitstempel (`YYYYMMDD-HHMMSS`) für eindeutige Exportdateinamen. |

## SQL-Schema und Datenmodell

Das Modul enthält mit `SCHEMA_SQL` ein idempotentes Bootstrap-/Migrationsskript für:

| Tabelle/Objekt | Inhalt |
|---------------|--------|
| `User` | Benutzer mit `identifier`, optional `email`, `password_hash`, `metadata` |
| `Thread` | Chat-Thread-Metadaten, Referenz auf `User`, Soft-Delete über `deletedAt` |
| `Step` | Nachrichten-/Schrittobjekte inkl. Hierarchie (`parentId`) und Zeitstempel |
| `Element` | Anhänge/Assets zu Threads/Steps |
| `Feedback` | Bewertungsdaten zu Assistant-Steps |
| Indizes | Performance-Indizes auf Thread-/Step-/Element-Zugriffspfade |
| Migrationsteil | Fügt fehlende Spalten (`email`, `password_hash`) in Bestandsdatenbanken hinzu |

## Exportlogik

### `export_all_chats_zip`

- Lädt Threads (optional auf `user_id` gefiltert, nur nicht gelöschte Threads).
- Lädt zu jedem Thread die Steps in zeitlicher Reihenfolge.
- Schreibt:
  - **JSONL**: ein Objekt pro Thread mit eingebetteter Step-Liste.
  - **CSV**: tabellarische Zeilen auf Step-Ebene.
- Verpackt JSONL + CSV in eine ZIP-Datei und gibt den ZIP-Pfad zurück.

### `export_feedback_csv`

- Joint `Feedback`, `Step`, `Thread`, `User`.
- Verwendet `LATERAL`-Subqueries, um die letzte Nutzerfrage vor dem bewerteten Step und die korrespondierende Assistant-Antwort zuzuordnen.
- Exportiert eine analytikfreundliche CSV mit Nutzer-, Frage-, Antwort- und Bewertungsfeldern.

## Verhaltenshinweise und Edge-Cases

- **Idempotente Schemaausführung**: Wiederholtes `ensure_native_schema()` ist vorgesehen und verursacht keine Duplikate.
- **Feedback-Deduplizierung je Step**: `upsert_feedback()` erzwingt Eindeutigkeit auf `stepId`; wiederholte Bewertungen überschreiben den vorhandenen Eintrag.
- **Konfliktbehandlung bei Registrierung**: `create_user()` liefert bei Kollision bewusst `None`, statt Exception-basiertem Flow.
- **Robuste Dateiablage**: Exportfunktionen erstellen Zielordner automatisch (`mkdir(..., exist_ok=True)`).

## Konfiguration

Das Modul erwartet primär `database_url` als Aufruferparameter (typisch aus [apps/chainlit/settings.py](../../apps/chainlit/settings.py)).

| Parameter | Wirkung |
|----------|---------|
| `database_url` | PostgreSQL-DSN für alle DB-Operationen |
| `out_dir` | Zielordner für Exportartefakte (CSV/JSONL/ZIP) |
| `user_id` (optional) | Einschränkung des Chat-Exports auf einen Benutzer |

## Bekannte Einschränkungen

- **Kein Connection-Pooling im Modul**: Jede Funktion öffnet/schließt eine eigene Verbindung; für sehr hohe Last wäre ein zentraler Pool effizienter.
- **Schema + Runtime in einer Datei**: DDL (`SCHEMA_SQL`) und operative Queries sind zusammengefasst; langfristig könnten Migrations-/Repository-Schichten getrennt werden.
- **Teilweise JSON-Textfelder**: Metadata-Felder liegen als TEXT/JSON-String vor; inkonsistente Altwerte können zusätzliche Validierung erfordern.
