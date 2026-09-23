# Security Review Report

**Datum:** 28.06.2026
**Scope:** Änderungen auf diesem Branch (Self-Registration, Lightweight Document Upload, Branding, Settings-Panel) — `apps/chainlit/app.py`, `native_chat.py`, `settings.py`, `upload_handler.py`, `public/custom.js`, `.chainlit/config.toml`, `scripts/query_qdrant.py`.

**Methodik:** 3-stufiger Review-Prozess — (1) Identifikation durch einen Analyse-Agenten mit Repository-Exploration, (2) unabhängige Validierung jedes Einzelfundes durch separate Agenten anhand definierter False-Positive-Filterkriterien, (3) Aufnahme nur bei Validierungs-Konfidenz ≥ 8/10.

---

## Zusammenfassung

Keine Befunde erreichten die für die Aufnahme erforderliche Konfidenzschwelle (≥ 8/10).

Drei Kandidaten-Befunde wurden in Phase 1 identifiziert und in Phase 2 unabhängig erneut bewertet; alle wurden als unzureichend konkret bzw. außerhalb des Geltungsbereichs der Filterkriterien ausgeschlossen:

| # | Kandidaten-Befund | Erstkonfidenz | Validierte Konfidenz | Ausschlussgrund |
|---|---|---|---|---|
| 1 | IDOR auf `/sources/upload/{session_id}/{file_name}` (fehlende Thread-Eigentümerprüfung) | 7/10 | **2/10** | Ausnutzung erfordert Kenntnis der UUID des Chainlit-Threads eines anderen Nutzers; UUIDs gelten laut Präzedenzfall als nicht erratbar, kein Offenlegungskanal für die UUID im geprüften Code vorhanden |
| 2 | CSV-/Formel-Injection über unbeschränkten Self-Registration-Benutzernamen, der in Admin-CSV-Exporten landet | 7/10 | **6/10** | Bestätigt unsanitisiert, aber Ausnutzung erfordert Admin-seitige Aktion (manueller Export + Öffnen in Tabellenkalkulation mit aktivierter Formel-Auto-Ausführung), was moderne Excel/LibreOffice-Versionen zunehmend standardmäßig blockieren |
| 3 | E-Mail-Verifizierungs-Token wird im Klartext geloggt (`[DEBUG]`-Prints) | 7/10 | **7/10** | Bestätigt real und unnötig, aber der Token schaltet lediglich ein `email_verified`-Boolean einer nicht-authentifizierten, ausstehenden Registrierung um — keine Login-/Authentifizierungs-/Account-Übernahme-Fähigkeit, was den Schweregrad unter die Berichtsschwelle senkt |

---

## Details der geprüften Kandidaten

### 1. IDOR auf Upload-PDF-Endpoint (gefiltert, Konfidenz 2/10)

**Datei:** `apps/chainlit/app.py` (Route `source_upload_pdf`, Helper `_resolve_upload_pdf_path`)

Die Route prüft nur `current_user is not None`, nicht ob der anfragende Nutzer tatsächlich Eigentümer des durch `session_id` referenzierten Threads ist. Theoretisch könnte ein beliebiger authentifizierter Nutzer das hochgeladene Dokument eines anderen Nutzers abrufen, wenn er dessen Thread-UUID kennt.

**Warum gefiltert:** Die Thread-ID ist eine UUID4 ohne erkennbaren Offenlegungskanal im Code (kein Admin-Panel mit Thread-Liste, keine Share-Links). Gilt damit als nicht praktisch ausnutzbar.

**Empfehlung trotzdem:** Eine zusätzliche Eigentümerprüfung (`SELECT "userId" FROM "Thread" WHERE id=$1`) wäre Defense-in-Depth und entspricht dem bereits in `export_all_chats` verwendeten Muster.

### 2. CSV-/Formel-Injection über Benutzername (gefiltert, Konfidenz 6/10)

**Datei:** `apps/chainlit/app.py` (`register_user`, nur `len(username) >= 3` geprüft); `apps/chainlit/native_chat.py` (`export_feedback_csv`, `export_all_chats_zip`)

Selbstregistrierte Nutzer können einen Benutzernamen mit Formel-Payload setzen (z. B. `=HYPERLINK(...)`), der unescaped in Admin-CSV-Exporte gelangt.

**Warum gefiltert:** Erfordert Admin-seitige Aktion (Export + Öffnen in Excel/LibreOffice mit aktivierter Formel-Ausführung); moderne Versionen blockieren das zunehmend standardmäßig.

**Empfehlung trotzdem:** Zeichen-Whitelist für Benutzernamen bei der Registrierung (z. B. `^[A-Za-z0-9_.-]{3,32}$`) und/oder führendes `'` vor Zellen, die mit `=`, `+`, `-`, `@` beginnen, in den CSV-Writern.

### 3. Verifizierungs-Token im Klartext geloggt (gefiltert, Konfidenz 7/10)

**Dateien:** `apps/chainlit/native_chat.py:213`; `apps/chainlit/app.py:2363, 2368`

Der einmalig gültige E-Mail-Verifizierungs-Token wird in drei `[DEBUG]`-Print-Statements im Klartext ausgegeben.

**Warum gefiltert:** Der Token schaltet ausschließlich `email_verified = TRUE` einer noch nicht abgeschlossenen Registrierung um — kein Login, keine Authentifizierung, keine Account-Übernahme möglich. Schweregrad bleibt unter der Berichtsschwelle.

**Empfehlung trotzdem:** Die drei Debug-Prints vor Produktivbetrieb entfernen oder hinter ein `DEBUG`-Flag stellen, da unnötige Offenlegung eines sicherheitsrelevanten Werts in Logs grundsätzlich vermieden werden sollte.

---

## Geprüft und als unbedenklich bestätigt

- Alle SQL-Statements in `native_chat.py` sind parametrisiert — keine SQL-Injection.
- Path Traversal in `_resolve_upload_pdf_path` / `_resolve_source_pdf_path` wird durch `resolve()` + `relative_to()`-Prüfungen verhindert.
- `verify_email`/`register_user`-HTML-Antworten verwenden korrekt `html.escape()` für nutzerkontrollierte Werte — keine Reflected XSS.
- `custom.js`-Ergänzungen verwenden ausschließlich `.value`/`.textContent`, nie `innerHTML` mit nicht-vertrauenswürdigen Daten.
- SMTP-Header-Injection wird durch Pythons `email.message`-Policy verhindert.
- Passwort-Hashing verwendet `bcrypt` mit Salt pro Passwort (`gensalt()`).
- `scripts/query_qdrant.py` ist ein lokales CLI-Tool mit typisierten Qdrant-Filterobjekten — nicht web-exponiert.

**Keine Befunde mit Schweregrad HIGH wurden in diesem Diff identifiziert.**

---

## Nachtrag: Security-Check auf `main`

**Datum:** 28.06.2026 15:47:14+02:00
**Durchgefuehrt von:** GitHub Copilot auf Basis von GPT-5.4
**Branch:** `main`
**Commit:** `8ae99a2`
**Scope:** Sicherheitsreview des aktuellen Stands auf `main` mit Fokus auf Authentifizierung, Secret-Handling, CSV-Export, Logging und Docker-Defaults
**Methodik:** Statische Code- und Konfigurationspruefung im Workspace mit gezielter Verifikation der betroffenen Codepfade
**Gepruefte Laufzeitkonfiguration:** `CHAT_MODEL=openai/openai/gpt-oss-120b` in `apps/chainlit/.env`

### Ergebnis

Der Stand auf `main` besteht den Security-Check nicht ohne Einschraenkung. Es wurden drei belastbare Befunde bestaetigt.

1. Kritisch: produktiver Admin-Fallback mit bekannten Default-Credentials.
	- `apps/chainlit/docker-compose.yml` setzt Fallbacks auf `change-me`, `admin`, `admin`.
	- `apps/chainlit/app.py` akzeptiert diese Werte direkt im Passwort-Login als Admin.
	- Risiko: Wenn Umgebungsvariablen fehlen oder falsch geladen werden, entsteht ein trivial nutzbarer Admin-Zugang.

2. Hoch: CSV-/Formel-Injection in Admin-Exporten.
	- `apps/chainlit/native_chat.py` schreibt `username`, `user_question` und `feedback_comment` unveraendert in CSV-Dateien.
	- Risiko: Inhalte mit fuehrendem `=`, `+`, `-` oder `@` koennen beim Oeffnen in Tabellenkalkulationen als Formel ausgewertet werden.

3. Mittel: E-Mail-Verifizierungs-Token werden im Klartext geloggt.
	- `apps/chainlit/app.py` loggt den Token und das Verifikationsergebnis ueber Debug-Prints.
	- Risiko: unnoetige Offenlegung eines sicherheitsrelevanten Werts in Logs.

### Einordnung

- Die lokale Datei `apps/chainlit/.env` enthaelt echte Secrets, Default-Credentials und SMTP-Zugangsdaten, ist laut Git-Status aber nicht versioniert und damit nach aktuellem Stand kein Secret-Leak auf `main`.
- Die dort enthaltenen Zugangsdaten und Tokens sollten trotzdem rotiert werden, weil sie lokal produktiv wirksam sind.

### Empfohlene Massnahmen

1. Admin-Fallback standardmaessig deaktivieren oder bei Default-Credentials den Start hart abbrechen.
2. CSV-Exportwerte vor Formel-Injection schuetzen, z. B. durch Prefixing mit `'` bei fuehrenden Sonderzeichen.
3. Verifizierungs-Tokens nicht mehr im Klartext loggen.
