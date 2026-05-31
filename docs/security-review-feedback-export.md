# Security Review: `test/merge-feedback-into-citation`

**Datum:** 2026-05-08
**Branch:** `test/merge-feedback-into-citation`
**Basis:** Merge von `feature/feedback-export` in `chainlit-citation-sidebar-fix`
**Reviewer:** Claude Code (claude-sonnet-4-6)

---

## Überprüfte Dateien

- `apps/chainlit/app.py`
- `apps/chainlit/native_chat.py`
- `apps/chainlit/chat_history.py`
- `apps/chainlit/user_profile.py`
- `apps/chainlit/rag_tool.py`
- `apps/chainlit/public/custom.js`
- `apps/chainlit/public/custom.css`
- `apps/chainlit/Dockerfile`

---

## Zusammenfassung

Es wurden vier Kandidaten-Findings identifiziert und anschließend durch unabhängige False-Positive-Analysen bewertet. **Kein Finding hat den Schwellenwert von 8/10 Konfidenz** für eine Aufnahme in den Bericht überschritten.

---

## Findings (alle herausgefiltert)

### Kandidat 1 — CSV-Formel-Injektion · `native_chat.py` (neue Funktion `export_feedback_csv`)

- **Kategorie:** CSV Injection
- **Initiale Konfidenz:** 0,90
- **Filter-Ergebnis:** Muster bestätigt, Konfidenz nach Analyse auf **7/10** herabgestuft
- **Begründung für Herausfilterung:**
  `csv.DictWriter` mit `QUOTE_MINIMAL` maskiert keine führenden Formel-Zeichen (`=`, `+`, `-`, `@`). Felder wie `user_question`, `assistant_answer` und `feedback_comment` enthalten benutzerkontrollierte Inhalte, die bei Öffnen der CSV-Datei in Excel oder LibreOffice Calc Formeln ausführen könnten.

  Der Endpunkt `/export/feedback` ist jedoch ausschließlich für Administratoren zugänglich (Authentifizierung + Admin-Rollenprüfung). Aktuelle Versionen von Excel und LibreOffice zeigen bei extern geladenen Dateien eine Schutzansicht und warnen vor der Ausführung von Formeln. Der Angriffspfad setzt voraus, dass ein authentifizierter Nutzer gezielt eine Payload einschleust und der Administrator anschließend aktiv eine Sicherheitswarnung seiner Tabellenkalkulation ignoriert — eine mehrstufige Kette, die unterhalb des Schwellenwerts von ≥ 8 bleibt.

  **Empfehlung (kein Blocker):** Als Defense-in-Depth-Maßnahme sollten führende Formel-Zeichen beim CSV-Schreiben durch einen vorangestellten Tabulator oder einfaches Anführungszeichen neutralisiert werden.

---

### Kandidat 2 — Datenexposition aller Nutzer über `/export/all-chats` · `app.py`

- **Kategorie:** Fehlerhafte Zugriffskontrolle (Broken Access Control)
- **Initiale Konfidenz:** 0,85
- **Filter-Ergebnis:** Realer Bug, Konfidenz für diesen Review **6/10**
- **Begründung für Herausfilterung:**
  Dieser Endpunkt existiert bereits vor dem PR. Der Review-Scope umfasst ausschließlich neu eingeführte Schwachstellen. Der neue `/export/feedback`-Endpunkt dieses PRs implementiert die Admin-Prüfung korrekt. Der Kontrast macht die Lücke im älteren Endpunkt sichtbarer, aber der PR hat sie nicht eingeführt.

  **Hinweis:** Der bestehende `/export/all-chats`-Endpunkt sollte separat untersucht werden. `current_user.id` ist im passwortbasierten Auth-Pfad `None`, weshalb `export_all_chats_zip()` ohne Nutzerfilter alle Threads aller Nutzer zurückgibt.

---

### Kandidat 3 — Admin-Rolle in benutzerkontrolliertem JSON-Metadatenfeld · `app.py`

- **Kategorie:** Rechteausweitung (Privilege Escalation)
- **Initiale Konfidenz:** 0,72 (bereits vor Filterung unter Schwellenwert)
- **Filter-Ergebnis:** FALSE POSITIVE, **4/10**
- **Begründung für Herausfilterung:**
  Es gibt keinen anwendungsseitigen Pfad, über den ein Nutzer `"role": "admin"` in `User.metadata` schreiben könnte. Der Registrierungspfad setzt Metadaten hartkodiert auf `'{"provider": "local"}'`. Eine Ausnutzung würde direkten Datenbankschreibzugriff erfordern, was bereits einer vollständigen Kompromittierung entspricht. Es handelt sich um ein Designproblem, nicht um einen konkreten Exploit.

---

### Kandidat 4 — Path Traversal über `/export <session_id>` · `app.py`

- **Kategorie:** Pfad-Traversal (Path Traversal)
- **Initiale Konfidenz:** 0,60 (bereits vor Filterung unter Schwellenwert)
- **Filter-Ergebnis:** FALSE POSITIVE, **2/10**
- **Begründung für Herausfilterung:**
  Session-IDs in der SQLite-Datenbank sind ausnahmslos Chainlit-generierte UUIDs (nur Hex-Zeichen und Bindestriche). Jede Eingabe mit `../` oder einem Pfad-Separator findet keinen Datenbankeintrag, sodass die Funktion vor dem eigentlichen Dateischreiben abbricht. Eine Ausnutzung ist in der Praxis nicht möglich.

---

## Gesamtbewertung

**Es wurden keine hochkonfidenten (≥ 8/10) Schwachstellen gefunden, die durch diesen PR neu eingeführt wurden.**

Der neue `@cl.on_feedback`-Handler und der `/export/feedback`-Endpunkt folgen dem etablierten Autorisierungsmuster korrekt (Authentifizierungsprüfung + Admin-Rollenprüfung). Alle Datenbankzugriffe in `upsert_feedback` sowie in der erweiterten `upsert_user_profile`-Funktion verwenden durchgängig parametrisierte Queries. Die neuen Keyword- und Custom-Prompt-Features speichern und lesen Daten sicher.

---

## Offene Punkte (kein Blocker, separat adressieren)

| Priorität | Thema | Datei |
|-----------|-------|-------|
| Niedrig | CSV-Formel-Zeichen neutralisieren (`=`, `+`, `-`, `@`) als Defense-in-Depth | `native_chat.py` |
| Mittel | Admin-Prüfung für `/export/all-chats` nachrüsten oder `current_user.identifier` statt `.id` zur Nutzerfilterung verwenden | `app.py` |
