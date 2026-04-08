# Feedback-Persistierung & CSV-Export

**Branch:** `feature/feedback-export`  
**Commit:** `6ead407`  
**Datum:** 2026-04-08  
**Geänderte Dateien:** 2 Dateien, +155 Zeilen

## Überblick

Chainlit zeigt in der Chat-UI Feedback-Buttons (Helpful / Not helpful + optionaler Freitext-Kommentar).
Ohne einen registrierten `@cl.on_feedback`-Handler werden diese Klicks jedoch **nicht** in der Datenbank gespeichert.

Dieses Feature ergänzt:

1. **Persistierung** – Feedback wird beim Klick in die PostgreSQL-`Feedback`-Tabelle geschrieben.
2. **CSV-Export** – Ein authentifizierter HTTP-Endpoint liefert alle Feedback-Daten aller Nutzer als CSV-Download.

## Geänderte Dateien

### `apps/chainlit/native_chat.py` (+124 Zeilen)

| Funktion | Beschreibung |
|---|---|
| `upsert_feedback()` | Speichert Feedback in die PostgreSQL-`Feedback`-Tabelle. Nutzt `ON CONFLICT ("stepId")` statt `ON CONFLICT (id)`, damit wiederholte Klicks auf denselben Step das bestehende Feedback aktualisieren statt Duplikate zu erzeugen. Erstellt idempotent einen Unique Index `Feedback_stepId_unique`. |
| `export_feedback_csv()` | Exportiert alle Feedback-Daten als CSV. Löst per `LEFT JOIN LATERAL` die korrekte Assistenz-Antwort auf (Child-Step vom Typ `assistant_message`, da Feedback an `run`-Steps hängt, die selbst keinen Output haben). Ebenso wird die vorangehende User-Frage per LATERAL JOIN ermittelt. |

### `apps/chainlit/app.py` (+31 Zeilen)

| Änderung | Beschreibung |
|---|---|
| `@cl.on_feedback` Handler | Persistiert Feedback-Events (Helpful/Not helpful + Kommentar) über `upsert_feedback()` in PostgreSQL. Ohne diesen Handler zeigt Chainlit zwar die Buttons, speichert aber nichts. |
| `GET /export/feedback` | Authentifizierter Endpoint, liefert CSV-Download aller Feedback-Daten aller Nutzer. |
| Imports | `export_feedback_csv` und `upsert_feedback` aus `native_chat` importiert. |

## DB-Schema-Änderung

- **Unique Index** `Feedback_stepId_unique` auf `"Feedback"."stepId"` – verhindert doppelte Feedback-Einträge pro Step.
- Der Index wird beim ersten Aufruf von `upsert_feedback()` idempotent via `CREATE UNIQUE INDEX IF NOT EXISTS` angelegt.

## Datenmodell-Hintergrund

Chainlit hängt Feedback an **`run`-Steps** (den `on_message`-Wrapper), nicht an `assistant_message`-Steps.
`run`-Steps haben jedoch keinen eigenen Output – die eigentliche Antwort steckt in einem **Child-Step** vom Typ `assistant_message` mit `parentId = run.id`.

Die Export-Query löst dies via:
```sql
LEFT JOIN LATERAL (
    SELECT cs.output FROM "Step" cs
    WHERE cs."parentId" = s.id AND cs.type = 'assistant_message'
    ORDER BY cs."startTime" DESC LIMIT 1
) child ON true
```
und verwendet `COALESCE(child.output, s.output)` als Fallback.

## CSV-Spalten

| Spalte | Beschreibung |
|---|---|
| `username` | Benutzername (aus `User.identifier` via Thread) |
| `user_question` | Die Nutzerfrage (vorhergehender `user_message`-Step) |
| `assistant_answer` | Die Assistenz-Antwort (Child `assistant_message`-Step) |
| `feedback_value` | `1.0` = Helpful, `0.0` = Not helpful |
| `feedback_comment` | Optionaler Freitext-Kommentar |
| `answer_time` | Zeitstempel der Antwort (ISO 8601) |
| `thread_id` | UUID des Chat-Threads |
| `feedback_id` | UUID des Feedback-Eintrags |
| `step_id` | UUID des Steps, an den das Feedback gehängt wurde |

## Nutzung

### CSV-Export über Browser

```
http://localhost:8000/export/feedback
```

Erfordert Authentifizierung (Login-Cookie oder OAuth-Token). Liefert alle Feedback-Daten aller Nutzer.

### Ad-hoc-Abfrage über PostgreSQL

```bash
sudo docker exec gski-postgres psql -U chainlit -d chainlit -c '
SELECT u.identifier, f.value, f.comment, s."createdAt"
FROM "Feedback" f
JOIN "Step" s ON s.id = f."stepId"
JOIN "Thread" t ON t.id = s."threadId"
LEFT JOIN "User" u ON u.id = t."userId"
ORDER BY s."createdAt" DESC;
'
```
