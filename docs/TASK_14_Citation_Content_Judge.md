# TASK_14: Citation-Content-Judge & Repair-Runde

## Problem

Die bestehenden zwei Zitations-Phasen prüfen nur Struktur, nie Inhalt:

- **Phase 1** `_validate_citations()` ([app.py:1035](../apps/chainlit/app.py#L1035)): vergleicht BSI-IDs im Fließtext mit der zitierten Chunk-ID. Greift nicht bei Chunks ohne Anforderungs-/Baustein-ID (z. B. Standard-200-2-Abschnitte, Inhaltsverzeichnisse).
- **Phase 2** `_canonicalize_citations()` ([app.py:1368](../apps/chainlit/app.py#L1368)): repariert nur, *welcher* Alias verlinkt wird (Token-Overlap-Scoring). Prüft nie, ob die Behauptung inhaltlich im Chunk-Text steht.

**Beobachtetes Fehlerbild** (Live-Test, `Welche Schritte umfasst die Basis-Absicherung...`):

Retrieval traf `chunk_page_1` von `standard_200_2` — das Inhaltsverzeichnis des gesamten Dokuments (`header: null`, S. 1–7). Sein Text enthält Zeilen wie:

```
1.4  Anwendungsweise . . . . . . . . . . . . 9
9    Umsetzung der Sicherheitskonzeption ... 158
9.1  Sichtung der Untersuchungsergebnisse ... 158
9.2  Kosten- und Aufwandsschätzung ... 159
```

Das Modell hat die Kapitel-9-Titel korrekt als Antwortinhalt übernommen, aber als Quelle eine benachbarte ToC-Zeile ("1.4 Anwendungsweise, S.9") verlinkt, die mit der Aussage nichts zu tun hat. Weder Phase 1 (keine BSI-ID vorhanden) noch Phase 2 (beide Zeilen stammen aus demselben Chunk, Token-Overlap kann nicht zwischen ihnen unterscheiden) erkennen das — das Problem liegt eine Ebene tiefer: *Deckt der zitierte Text die Behauptung tatsächlich?*

## Architektur: Phase 3 — Content-Judge & Repair

Ansatzpunkt im bestehenden Ablauf, direkt vor der finalen Aktualisierung der Nachricht:

```
Antwort gestreamt (assistant_reply, sichtbar für Nutzer)
    ↓
Phase 1: _validate_citations()        [app.py:4490] – strukturell, ID-Match
Phase 2: _canonicalize_citations()    [app.py:4321/4383] – Alias-Zielrepair
    ↓
NEU – Phase 3: Content-Judge
    1. Extrahiere alle (Behauptung, zitierter Volltext)-Paare
    2. EIN Judge-Call: pro Paar supported=true/false + Begründung (JSON)
    3. Bei mind. einem false:
         Repair-Call (Original-Antwort + beanstandete Punkte + bereits
         abgerufener Kontext dieser Runde) → gezielte Überarbeitung
    4. Reparierte Antwort erneut durch Phase 1 + 2 (idempotent)
    ↓
assistant_reply.update()   [app.py:4497] – hier entsteht die Verzögerung (s. UX-Flow)
```

### Schritt 1: Paare extrahieren

```python
def _extract_claim_source_pairs(
    content: str,
    source_rows: list[tuple],
    alias_to_full_text: dict[str, str],
) -> list[dict]:
    """Zu jedem 'Quelle: ... (S.X)'-Span: zugehörige Zeile + voller Chunk-Text."""
    pairs = []
    for match in _CITATION_CANONICAL_RE.finditer(content):
        alias = match.group(0).strip("*_() ")
        line_start = content.rfind("\n", 0, match.start()) + 1
        claim = content[line_start:match.start()].strip(" -•\t")
        full_text = alias_to_full_text.get(alias)
        if claim and full_text:
            pairs.append({"alias": alias, "claim": claim, "chunk_text": full_text})
    return pairs
```

Wiederverwendet die vorhandene `_CITATION_CANONICAL_RE` und `alias_to_full_text` (bereits in Phase 2 aufgebaut) — keine neue Extraktionslogik nötig.

### Schritt 2: Gebündelter Judge-Call

Ein Call für die gesamte Antwort, nicht pro Bullet (Kosten/Latenz):

```python
async def _judge_citation_support(pairs: list[dict]) -> list[dict]:
    if not pairs:
        return []
    prompt = "Prüfe für jedes Paar, ob der Quelltext die Behauptung belegt.\n\n"
    for i, p in enumerate(pairs, 1):
        prompt += f"[{i}] Behauptung: {p['claim']}\nQuelltext: {p['chunk_text'][:600]}\n\n"
    prompt += 'Antworte NUR als JSON: [{"index":1,"supported":true,"grund":"..."}]'

    response = await chat([{"role": "user", "content": prompt}], model=CITATION_JUDGE_MODEL)
    try:
        verdicts = json.loads(response.choices[0].message.content or "[]")
    except json.JSONDecodeError:
        return []  # fail-open: bei Parse-Fehler nichts anfassen
    return [v for v in verdicts if not v.get("supported", True)]
```

### Schritt 3: Repair-Call (nur bei Treffern)

```python
async def _repair_flagged_claims(
    content: str, mismatches: list[dict], retrieved_context: str,
) -> str:
    prompt = (
        "Überarbeite AUSSCHLIESSLICH die folgenden beanstandeten Punkte der Antwort. "
        "Nutze ausschließlich den mitgelieferten Kontext — keine neuen Fakten. "
        "Wenn kein passender Beleg im Kontext existiert, kennzeichne den Punkt "
        "explizit als 'nicht eindeutig belegt' statt ihn kommentarlos zu entfernen.\n\n"
        f"Antwort:\n{content}\n\nBeanstandete Punkte:\n{mismatches}\n\n"
        f"Verfügbarer Kontext:\n{retrieved_context}"
    )
    response = await chat([{"role": "user", "content": prompt}], model=CHAT_MODEL)
    return response.choices[0].message.content or content
```

Kein neuer `rag_retrieve`-Call nötig — der Kontext dieser Runde liegt bereits im Session-State.

### Integration

```python
# Nach Phase 1 (app.py:4490ff), vor assistant_reply.update()/.send():
if CITATION_JUDGE_ENABLED and assistant_reply.content and source_rows_for_session:
    pairs = _extract_claim_source_pairs(assistant_reply.content, source_rows_for_session, alias_to_full_text)
    mismatches = await _judge_citation_support(pairs)
    if mismatches:
        assistant_reply.content = await _repair_flagged_claims(
            assistant_reply.content, mismatches, context,
        )
        assistant_reply.content = _canonicalize_citations(assistant_reply.content, source_rows_for_session, alias_to_full_text)
        assistant_reply.content = _validate_citations(assistant_reply.content, source_rows_for_session)
```

Neue Settings (analog zu bestehenden TASK-13-Flags, default `false` bis kalibriert):

```
CITATION_JUDGE_ENABLED=false
CITATION_JUDGE_MODEL=              # leer = CHAT_MODEL; günstigeres Modell möglich
```

## UX-Flow aus Nutzersicht

Wichtiger Unterschied zu Phase 1/2: Die sind reine Regex-Operationen (Mikrosekunden), Phase 3 braucht 1–2 echte LLM-Calls. Das ändert das Timing spürbar.

**Heute** (`app.py:4041-4499`): Antwort wird token-weise gestreamt (`stream_token`), danach wird die schon sichtbare Nachricht einmal lautlos mit `.update()` final poliert (Phase 1+2 sind so schnell, dass das nicht auffällt).

**Mit Phase 3** entsteht dazwischen eine neue, spürbare Lücke:

```
[Antwort erscheint token-weise, wie gewohnt]
        ↓
[Antwort steht vollständig da — sieht für den Nutzer "fertig" aus]
        ↓
   ⏳ 2-5s STILLE  ← NEUE LÜCKE: Judge-Call (+ ggf. Repair-Call) läuft
        ↓
[Text verändert sich unter den Augen des Nutzers]
```

Eine unangekündigte Stille von mehreren Sekunden nach einer scheinbar fertigen Antwort, gefolgt von sichtbarem Nachbearbeiten des Texts, wirkt wie ein Bug ("warum ändert sich die Antwort nachträglich?"). Das muss sichtbar gemacht werden, nicht lautlos wie bisher.

### Vorgeschlagener Ablauf

Die App zeigt Tool-Aufrufe bereits heute als eigenen, einklappbaren Step (siehe `rag_retrieve` in der UI: *"Avatar for rag_retrieve — Used rag_retrieve"*). Phase 3 nutzt dasselbe Muster:

**Fall A — keine Beanstandung** (Normalfall, erwartungsgemäß die Mehrheit):
1. Antwort streamt wie gewohnt.
2. Kurzer Step erscheint/verschwindet: *"Zitate werden geprüft…"* (< 1s, da nur der Judge-Call ohne Repair läuft) — für Transparenz, aber nicht aufdringlich.
3. Fertig. Kein sichtbarer Unterschied zu heute.

**Fall B — Beanstandung + erfolgreiche Reparatur:**
1. Antwort streamt wie gewohnt, wirkt vollständig.
2. Step erscheint: *"Zitate werden geprüft…"* → nach Judge-Ergebnis wechselt er zu *"X Angabe(n) werden korrigiert…"* (macht die zusätzliche Wartezeit für den Nutzer nachvollziehbar, statt stiller Hänger).
3. Nachricht wird mit der reparierten Fassung aktualisiert.
4. **Transparenz-Fußnote** unter der Antwort (klein, nicht aufdringlich): *"1 Angabe wurde vor der Anzeige automatisch korrigiert."* — wichtig für die wissenschaftliche Verwertbarkeit: Nutzer/Prüfer sehen, dass eine QS-Stufe gegriffen hat, statt den Eindruck zu haben, die Antwort sei unverändert seit dem Streaming.

**Fall C — Beanstandung, aber keine Reparatur möglich** (kein passender Beleg im abgerufenen Kontext):
1. Wie Fall B bis Schritt 2.
2. Der betroffene Punkt wird **nicht kommentarlos entfernt** (das hatte sich beim reinen Strip-on-Fail in Phase 1 bereits als schlechter erwiesen als eine falsche-aber-sichtbare Quelle), sondern explizit markiert: *"— [Punkt konnte nicht eindeutig belegt werden]"* direkt im Text, plus dieselbe Transparenz-Fußnote wie Fall B.
3. Nutzer sieht damit klar: hier fehlt eine gesicherte Quelle, statt entweder eine falsche Quelle oder eine stillschweigend verkürzte Antwort zu bekommen.

### Offene UX-Fragen für die Kalibrierung

1. Soll der Zwischen-Step (*"wird geprüft…"*) **immer** kurz aufblitzen (auch bei Fall A), oder nur bei tatsächlicher Reparatur sichtbar werden? Immer-Anzeige ist ehrlicher (kein Unterschied zwischen "schnell, weil OK" und "schnell, weil Judge übersprungen wurde"), kostet aber etwas UI-Ruhe.
2. Soll die Transparenz-Fußnote nur bei Korrektur erscheinen, oder grundsätzlich ("Diese Antwort wurde automatisch auf Zitat-Genauigkeit geprüft.") — Letzteres ist für die Thesis ggf. relevanter (durchgängig nachweisbare QS-Stufe), Ersteres ist unauffälliger im Alltag.
3. Bei Fall C: reicht eine reine Text-Markierung, oder sollte der Punkt zusätzlich visuell hervorgehoben werden (z. B. wie eine Warnung)?

## Risiken

- **Latenz**: +1 Call immer (Judge), +1 Call nur bei Treffer (Repair) — bei aktueller Fehlerquote ("viel zu viele Fehler", siehe Vorgespräch) wird der zweite Call vermutlich häufig feuern. Sollte in den ersten Testläufen gemessen werden, bevor produktiv geschaltet.
- **Judge kann sich selbst irren**: fail-open beibehalten (bei JSON-Parse-Fehlern/Unsicherheit nichts verändern), analog zum bestehenden Muster in Phase 2.
- **Repair-Qualität**: Ein LLM-Rewrite kann Bedeutung verschieben. Repair-Prompt schränkt daher explizit auf "nur mitgelieferter Kontext, keine neuen Fakten" ein.
- **Kein rekursives Nachbessern**: maximal 1 Repair-Versuch pro Antwort (analog `MAX_TOOL_CALL_ROUNDS`), sonst Kosten-/Latenz-Explosion bei hartnäckigen Fällen.

## Priorisierung

1. `CITATION_JUDGE_ENABLED=false` als Ausgangszustand, Judge-Call zunächst nur **loggen** (keine Rewrites), um Trefferquote/False-Positive-Rate an echten Logs zu kalibrieren, bevor der Repair-Pfad scharf geschaltet wird.
2. UX-Step (*"Zitate werden geprüft…"*) von Anfang an einbauen, auch während der reinen Logging-Phase — Latenz-Realismus früh sichtbar machen.
3. Repair-Pfad + Transparenz-Fußnote erst nach Kalibrierung aktivieren.
