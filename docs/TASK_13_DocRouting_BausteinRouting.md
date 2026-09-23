# TASK_13: Vorgelagertes Dokument- und Baustein-Routing

## Problemkontext

Das aktuelle Retrieval-System behandelt alle Fragen gleich: eine semantische Vektorsuche gegen den gesamten Qdrant-Index ohne Scope-Einschränkung. Das erzeugt zwei Klassen von Retrieval-Fehlern:

**Fehlerklasse D1 — Falsches Quelldokument:**  
Die Frage bezieht sich auf ein spezifisches BSI-Dokument, aber die Treffer stammen aus einem thematisch benachbarten anderen Dokument.

Beispiel: *„Welche Schritte umfasst die Basis-Absicherung nach BSI-Standard 200-2?"*  
→ Treffer aus Standard 200-3 (S. 12–13), obwohl die Basis-Absicherung ausschließlich in 200-2 beschrieben wird.

**Fehlerklasse D2 — Falscher Baustein (innerhalb Kompendium):**  
Die Frage bezieht sich auf ein bestimmtes IT-Grundschutz-Thema, aber semantisch ähnliche Bausteine anderer Schichten dominieren die Trefferliste.

Beispiel: *„Welche Arten von zentralen Speicherlösungen gibt es?"*  
→ OPS.2.3 (Dateiserver, Cloud) dominiert vor SYS.1.8 (Speicherlösungen), obwohl SYS.1.8 der primäre Baustein ist.

**Gemeinsame Ursache:**  
BSI-Dokumente und IT-Grundschutz-Bausteine teilen ein großes gemeinsames Vokabular. Dense-Retrieval-Scores unterscheiden sich zwischen dem richtigen und falschen Dokument oft nur im zweiten Dezimalnachkommastellen-Bereich (z. B. 0.702 vs. 0.700).

---

## Lösungsarchitektur: Vorgelagertes Query-Routing

Statt die Retrieval-Abfrage unverändert gegen den Gesamtindex zu senden, wird ihr eine **Routing-Schicht** vorgelagert, die Scope-Filter ableitet:

```
Nutzerfrage
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  Routing-Schicht (pre-retrieval)                    │
│                                                     │
│  Schicht 1: Regex-Router (deterministisch)          │
│    → explizite Nennung "200-2", "BSI 200-3" etc.   │
│    → harter standard_id-Filter                      │
│                                                     │
│  Schicht 2: Semantischer Dokumenten-Router          │
│    → Query-Embedding vs. Dokument-Profil-Embeddings │
│    → Soft-Filter wenn Score > Schwellenwert         │
│                                                     │
│  Schicht 3: Semantischer Baustein-Router            │
│    → Query-Embedding vs. baustein_beschreibung      │
│    → Scope auf 1–2 Bausteine (nur Kompendium)       │
└─────────────────────────────────────────────────────┘
    │
    ▼
Qdrant-Abfrage mit abgeleiteten Filtern
    │
    ▼
Retrieval-Ergebnis
```

Die Schichten sind unabhängig aktivierbar (Feature-Flags) und greifen nacheinander:
- Schicht 1 schlägt an → Schicht 2 und 3 werden übersprungen
- Schicht 2 schlägt an und ergibt Kompendium → Schicht 3 greift zusätzlich
- Keine Schicht schlägt an → Standard-Retrieval ohne Filter (Fallback)

---

## Schicht 1: Regex-Dokumenten-Router

### Funktion

Erkennt explizite Nennungen von BSI-Dokumenten im Fragetext und setzt einen harten `standard_id`-Filter.

### Implementierung

**Datei:** `apps/chainlit/rag_tool.py` — neue Funktion `detect_explicit_standard()`

```python
import re

_STANDARD_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:BSI[- ])?Standard[- ]?200[- ]?1\b", re.I), "standard_200_1"),
    (re.compile(r"\b(?:BSI[- ])?Standard[- ]?200[- ]?2\b", re.I), "standard_200_2"),
    (re.compile(r"\b(?:BSI[- ])?Standard[- ]?200[- ]?3\b", re.I), "standard_200_3"),
    (re.compile(r"\b(?:BSI[- ])?Standard[- ]?200[- ]?4\b", re.I), "standard_200_4"),
]

def detect_explicit_standard(query: str) -> str | None:
    """Erkennt explizite BSI-Standard-Nennung im Fragetext."""
    for pattern, standard_id in _STANDARD_PATTERNS:
        if pattern.search(query):
            return standard_id
    return None
```

### Grenzen

Greift ausschließlich bei expliziter Nennung. Ambige Fragen wie *„Wie führe ich eine Risikoanalyse durch?"* (ohne „200-3") werden nicht erkannt → Schicht 2 übernimmt.

---

## Schicht 2: Semantischer Dokumenten-Router

### Funktion

Vergleicht das Query-Embedding mit vorberechneten Embeddings von Dokument-Profiltexten. Das ähnlichste Dokument wird als Scope-Empfehlung zurückgegeben — sofern der Score einen Schwellenwert überschreitet.

### Dokument-Profile

Die Profile beschreiben den **Anwendungskontext** jedes Dokuments, nicht Stichworte. Entscheidend ist die inhaltliche Abgrenzung zwischen Dokumenten mit überlappender Terminologie.

```python
DOCUMENT_PROFILES: dict[str, str] = {
    "standard_200_1": (
        "BSI-Standard 200-1 behandelt Aufbau und Betrieb eines Informationssicherheits-"
        "Managementsystems (ISMS). Inhalte: Definition des ISMS und des Sicherheitsprozesses, "
        "Management-Prinzipien, Ressourcen und Mitarbeitereinbindung, Sicherheitsleitlinie, "
        "Informationssicherheitsbeauftragter, kontinuierlicher Verbesserungsprozess (PDCA), "
        "Kompatibilität mit ISO 27001 und ISO 27002, ISMS-Zertifizierung auf Basis "
        "IT-Grundschutz. Zuständig für Fragen zum Managementsystem, zur Sicherheitsorganisation "
        "und zu Rollen. Nicht zuständig für konkrete technische Maßnahmen, "
        "Risikoanalysemethodik oder Notfallplanung."
    ),
    "standard_200_2": (
        "BSI-Standard 200-2 beschreibt die IT-Grundschutz-Methodik zur Erstellung von "
        "Sicherheitskonzepten in Behörden und Unternehmen. Inhalte: Initiierung des "
        "Sicherheitsprozesses, drei Vorgehensweisen (Basis-Absicherung, Kern-Absicherung, "
        "Standard-Absicherung), Strukturanalyse, Schutzbedarfsfeststellung, Modellierung "
        "nach IT-Grundschutz, IT-Grundschutz-Check, Risikoanalyse als Bestandteil der "
        "Standard-Absicherung, Umsetzungsplanung. Primärquelle für Fragen zur Vorgehensweise "
        "bei der IT-Grundschutz-Einführung, zur Sicherheitskonzeption und zu Absicherungsarten. "
        "Risikoanalyse hier: integrierter Schritt im Sicherheitskonzept — nicht als "
        "eigenständige Methodik für erhöhten Schutzbedarf."
    ),
    "standard_200_3": (
        "BSI-Standard 200-3 beschreibt eine eigenständige Methodik zur Risikoanalyse "
        "auf Basis der elementaren Gefährdungen des IT-Grundschutzes. Anwendungsfall: "
        "Systeme und Prozesse mit erhöhtem oder hohem Schutzbedarf, die über den "
        "IT-Grundschutz-Check hinausgehen. Inhalte: Vorarbeiten zur Risikoanalyse, "
        "Ermittlung und Bewertung elementarer Gefährdungen, Gefährdungsübersicht, "
        "Risikoeinstufung (Risikoeinschätzung und Risikobewertung), "
        "Risikobehandlungsoptionen (Reduktion, Übernahme, Vermeidung, Transfer), "
        "Risiken unter Beobachtung, Konsolidierung des Sicherheitskonzepts, "
        "Risikoappetit, Bezug zu ISO/IEC 31000. Zuständig für tiefergehende "
        "Risikoanalyse-Methodik und Eintrittshäufigkeit-Schadensauswirkungs-Matrizen. "
        "Nicht zuständig für allgemeine Sicherheitskonzept-Erstellung oder BCM."
    ),
    "standard_200_4": (
        "BSI-Standard 200-4 behandelt Business Continuity Management (BCM) und "
        "Notfallmanagement für Behörden und Unternehmen. Inhalte: BCMS-Stufenmodell "
        "(Reaktiv-BCMS, Aufbau-BCMS, Standard-BCMS), Bewältigungsorganisation (BAO), "
        "Stabsarbeit, BIA-Vorfilter und Business-Impact-Analyse (BIA), Identifikation "
        "zeitkritischer Geschäftsprozesse, Wiederanlaufplanung, Notfallvorsorge, "
        "Krisenmanagement und Krisenkommunikation, Notfallübungen, BC-Beauftragter. "
        "Zuständig ausschließlich wenn Notfallmanagement, Betriebskontinuität, "
        "Wiederherstellung nach Schadensereignissen oder BCM den Fragekontext bilden. "
        "Nicht zuständig für ISMS-Aufbau, Sicherheitskonzept oder Risikoanalyse-Methodik."
    ),
    "kompendium": (
        "Das IT-Grundschutz-Kompendium (Edition 2023) enthält alle IT-Grundschutz-Bausteine "
        "mit konkreten Sicherheitsanforderungen. Struktur: Elementare Gefährdungen (G 0.1–G 0.47), "
        "Prozess-Bausteine (ISMS, ORP, CON, OPS, DER) und System-Bausteine (APP, SYS, IND, NET, INF). "
        "Beispiel-Bausteine: ORP.4 Identitäts- und Berechtigungsmanagement, OPS.1.1.3 "
        "Patch- und Änderungsmanagement, APP.3.1 Webanwendungen, SYS.1.1 Allgemeiner Server, "
        "SYS.1.8 Speicherlösungen, NET.3.2 Firewall, INF.2 Rechenzentrum. "
        "Anforderungen sind nach Schutzbedarfsstufe klassifiziert (Basis, Standard, Erhöht). "
        "Zuständig für Fragen zu konkreten Anforderungen, Maßnahmen, Gefährdungslagen "
        "und Umsetzungshinweisen für bestimmte IT-Systeme, Anwendungen oder Prozesse."
    ),
}
```

### Implementierung

**Datei:** `apps/chainlit/rag_tool.py`

```python
# Modul-globale Cache-Tabelle (einmalig beim ersten Aufruf befüllt)
_profile_vectors: dict[str, list[float]] = {}

async def _ensure_profile_vectors() -> None:
    """Berechnet Dokument-Profil-Embeddings einmalig und cached sie."""
    if _profile_vectors:
        return
    keys = list(DOCUMENT_PROFILES.keys())
    texts = list(DOCUMENT_PROFILES.values())
    vectors = await embed(texts)
    _profile_vectors.update(zip(keys, vectors))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


async def detect_document_scope(
    query_vector: list[float],
    threshold: float = 0.82,
) -> str | None:
    """Semantisches Dokumenten-Routing via Profil-Embeddings.

    Gibt document_id zurück wenn Score > threshold, sonst None (kein Filter).
    """
    await _ensure_profile_vectors()
    best_id, best_score = None, 0.0
    second_score = 0.0
    for doc_id, profile_vec in _profile_vectors.items():
        score = _cosine_similarity(query_vector, profile_vec)
        if score > best_score:
            second_score = best_score
            best_score, best_id = score, doc_id
        elif score > second_score:
            second_score = score
    # Nur filtern wenn eindeutig: Top-1 klar vor Top-2
    if best_score > threshold and (best_score - second_score) > 0.02:
        return best_id
    return None
```

**Schwellenwert-Kalibrierung:**  
Der Threshold (0.82) und der Mindestabstand (0.02) sind empirische Parameter, die anhand der Testfälle (siehe unten) kalibriert werden müssen. Zu niedrig → falsche Filter; zu hoch → Routing greift zu selten.

---

## Schicht 3: Semantischer Baustein-Router (Blended Retrieval)

### Design-Entscheidung: Blended statt exklusiv

Schicht 1 und 2 setzen einen **exklusiven** `must`-Filter in Qdrant: nur Chunks aus dem erkannten Dokument kommen zurück. Das ist korrekt, weil die Nutzer bei expliziter Nennung oder klarer semantischer Zuordnung genau dieses Dokument meinen.

Schicht 3 darf **nicht** exklusiv filtern, weil Fragen auf Baustein-Ebene häufig baustein-übergreifend sind:

- *„Wie sichere ich meinen Webserver ab?"* → primär APP.3.2, aber auch NET.3.2 (Firewall), SYS.1.1 (Server) relevant
- Ein exklusiver `baustein_id`-Filter würde diese Treffer ausblenden, ohne dass der LLM davon wüsste (das Routing ist für den LLM transparent)

**Lösung:** Der Baustein-Router setzt intern `_routing_baustein_id` (nicht `baustein_id`). Eine zweite Qdrant-Abfrage holt gezielt Chunks aus dem erkannten Baustein und fügt sie in die Ergebnisliste ein — ohne Treffer aus der Hauptabfrage zu verdrängen.

### Funktion `detect_baustein_scope()`

Sucht in Qdrant ausschließlich auf `doc_type=baustein_beschreibung`-Chunks. Diese Chunks enthalten die BSI-Beschreibung, Abgrenzung und Modellierungshinweise jedes Bausteins — ohne manuelle Pflege einer separaten Profiltabelle.

```python
async def detect_baustein_scope(
    query_vector: list[float],
    threshold: float,
    top_n: int = 2,
) -> list[str]:
    """Finds relevant Bausteine via embedding search on description chunks (routing layer 3).

    Returns list of baustein_ids (empty when no clear match above threshold).
    """
    client = _get_client()
    response = client.query_points(
        collection_name=QDRANT_COLLECTION,
        query=query_vector,
        query_filter=Filter(must=[
            FieldCondition(key="doc_type", match=MatchValue(value="baustein_beschreibung")),
        ]),
        limit=top_n,
        score_threshold=threshold,
        with_payload=True,
    )
    bausteine: list[str] = []
    for point in (response.points or []):
        bid = (point.payload or {}).get("baustein_id")
        if isinstance(bid, str) and bid:
            bausteine.append(bid)
    return bausteine
```

**Warum keine statische Profilтабelle für 111 Bausteine?**  
Die `baustein_beschreibung`-Chunks in Qdrant *sind* die Profiltabelle. Sie enthalten authoritative BSI-Texte zu Beschreibung, Abgrenzung und Modellierung — automatisch aktuell bei jedem Re-Index. Eine manuelle Pflege von 111 Profilen würde doppelte Arbeit erzeugen und zwangsläufig veralten.

**Einschränkung:** Schicht 3 läuft nur wenn kein `standard_id`-Filter aktiv ist (Layer 1/2 hat nicht angeschlagen). Nicht sinnvoll für Standard-200-x-Fragen.

---

## Integration: Routing-Orchestrierung in `retrieve()`

### Hilfsfunktion `_qdrant_query()`

Um mehrere Qdrant-Abfragen (Haupt + Supplement) sauber ausführen zu können, wurde die Qdrant-Suche in eine Hilfsfunktion ausgelagert:

```python
def _qdrant_query(
    vector: list[float],
    k: int,
    *,
    source_scope: str | None = None,
    standard_id: str | None = None,
    baustein_id: str | None = None,
    schicht_id: str | None = None,
    include_vectors: bool = False,
) -> list[Any]:
    """Execute a single Qdrant vector search with optional hard filters.

    All filters are combined as AND (must). Returns raw ScoredPoint objects
    so the caller can merge multiple result sets before converting to RagResult.
    """
    must: list[FieldCondition] = []
    if source_scope:
        must.append(FieldCondition(key="source_scope", match=MatchValue(value=source_scope)))
    if standard_id:
        must.append(FieldCondition(key="standard_id", match=MatchValue(value=standard_id)))
    if baustein_id:
        must.append(FieldCondition(key="baustein_id", match=MatchValue(value=baustein_id)))
    if schicht_id:
        must.append(FieldCondition(key="schicht_id", match=MatchValue(value=schicht_id)))
    response = _get_client().query_points(
        collection_name=QDRANT_COLLECTION,
        query=vector,
        limit=k,
        score_threshold=SCORE_THRESHOLD,
        with_payload=True,
        with_vectors=include_vectors,
        query_filter=Filter(must=must) if must else None,
    )
    return list(response.points or [])
```

### Routing in `retrieve()`

```python
    embed_query = (await _generate_hyde_query(query)) if HYDE_ENABLED else query
    vector = (await embed([embed_query]))[0]

    # _routing_baustein_id: Layer 3 hint for blended retrieval (never an exclusive filter)
    _routing_baustein_id: str | None = None

    if DOC_ROUTING_ENABLED and standard_id is None and baustein_id is None:
        detected_std = detect_explicit_standard(query)
        if detected_std:
            standard_id = detected_std                          # Layer 1: exklusiv
        else:
            detected_doc = await detect_document_scope(
                query_vector=vector,
                threshold=DOC_ROUTING_THRESHOLD,
                min_gap=DOC_ROUTING_GAP,
            )
            if detected_doc and detected_doc != "kompendium":
                standard_id = detected_doc                      # Layer 2: exklusiv
            elif BAUSTEIN_ROUTING_ENABLED:
                detected_bausteine = await detect_baustein_scope(
                    query_vector=vector,
                    threshold=BAUSTEIN_ROUTING_THRESHOLD,
                )
                if len(detected_bausteine) == 1:
                    _routing_baustein_id = detected_bausteine[0]  # Layer 3: blended hint
                elif len(detected_bausteine) > 1:
                    schichten = {bid.split(".")[0] for bid in detected_bausteine}
                    if len(schichten) == 1 and schicht_id is None:
                        schicht_id = schichten.pop()             # gleiche Schicht → schicht_id

    # Hauptabfrage (exklusiv für Layer 1/2 und LLM-gesetzte Filter)
    points = _qdrant_query(vector, k, source_scope=source_scope,
                           standard_id=standard_id, baustein_id=baustein_id,
                           schicht_id=schicht_id, include_vectors=include_vectors)

    # Fallback bei leerem Ergebnis (ältere Collections ohne neue Metadaten-Felder)
    if not points and (source_scope or standard_id):
        points = _qdrant_query(vector, k, include_vectors=include_vectors)

    # Blended Supplement für Layer 3:
    # Zweite gezielte Abfrage, Ergebnisse per ID deduplizieren, nach Score sortieren, auf k kürzen.
    if _routing_baustein_id and baustein_id is None:
        boost_k = max(k // 2, 3)
        boost_points = _qdrant_query(vector, boost_k, source_scope=source_scope,
                                     baustein_id=_routing_baustein_id,
                                     include_vectors=include_vectors)
        if boost_points:
            seen_ids = {p.id for p in points}
            new_points = [p for p in boost_points if p.id not in seen_ids]
            points = sorted(points + new_points, key=lambda p: p.score, reverse=True)[:k]
```

### Grundprinzip: Routing boosted, schließt nie aus

Alle Routing-Schichten erzeugen ausschließlich **additive Ergänzungsabfragen** (`_routing_standard_id`, `_routing_baustein_id`). Die Hauptabfrage läuft immer ungefiltert — keine Quelle wird durch Routing ausgeblendet.

Hintergrund: Viele IT-Grundschutz-Fragen betreffen mehrere Quellen gleichzeitig. *„Welche Management-Prinzipien muss ich beim Aufbau eines ISMS beachten?"* — BSI-Standard 200-1 (Managementtext) UND ISMS.1 im Kompendium (konkrete Anforderungen) sind beide richtige Fundstellen. Ein exklusiver Filter würde eine davon ausblenden.

Ausnahme: explizit vom LLM gesetzte Parameter (`standard_id`, `baustein_id`, `schicht_id` als Funktionsargumente) werden als harte Filter respektiert.

### Ablauf und Qdrant-Abfragen

| Situation | Qdrant-Abfragen | Ergebnis |
|---|---|---|
| Kein Routing aktiv | 1 (ungefiltert) | Standard-Retrieval |
| Layer 1 oder 2 findet Standard | 2 (ungefiltert + standard-Supplement) | Main + 200-x Boost |
| Layer 3 findet Baustein | 2 (ungefiltert + baustein-Supplement) | Main + Baustein Boost |
| Layer 1/2 + Layer 3 gleichzeitig | 3 (ungefiltert + std + baustein) | Main + beide Boosts |
| LLM setzt `baustein_id` explizit | 1 (exklusiv) | Gezieltes LLM-Retrieval |

Layer 3 läuft **immer parallel** zu Layer 1/2 — nicht als Fallback:

```python
# Layer 1 oder 2 → _routing_standard_id
# Layer 3 immer   → _routing_baustein_id (unabhängig von Layer 1/2)

points = _qdrant_query(vector, k, ...)              # Hauptabfrage: ungefiltert

if _routing_standard_id:
    new = _qdrant_query(vector, boost_k, standard_id=_routing_standard_id, ...)
    boost_all.extend(deduplicated new)

if _routing_baustein_id:
    new = _qdrant_query(vector, boost_k, baustein_id=_routing_baustein_id, ...)
    boost_all.extend(deduplicated new)

points = sorted(points + boost_all, ...)[:k]        # Re-rank, trim to k
```

**Kalibrierte Parameter (Stand 2026-07-13):**

| Parameter | Wert | Beobachtung |
|---|---|---|
| `DOC_ROUTING_THRESHOLD` | `0.70` | ISMS-Frage: 200-1 score=0.700 |
| `DOC_ROUTING_GAP` | `0.008` | ISMS-Frage: gap=0.009 → feuert |
| `BAUSTEIN_ROUTING_THRESHOLD` | `0.70` | noch nicht empirisch kalibriert |

---

## Konfiguration

Neue Einträge in `settings.py` und `.env`:

```bash
# TASK_13: Vorgelagertes Routing
DOC_ROUTING_ENABLED=true
BAUSTEIN_ROUTING_ENABLED=true
DOC_ROUTING_THRESHOLD=0.82       # Mindest-Score für Dokumenten-Router Schicht 2
BAUSTEIN_ROUTING_THRESHOLD=0.70  # Mindest-Score für Baustein-Router Schicht 3
```

Alle Flags defaulten auf `false` bis kalibriert.

---

## Zu ändernde Dateien

| Datei | Änderung |
|---|---|
| `apps/chainlit/rag_tool.py` | `detect_explicit_standard()`, `DOCUMENT_PROFILES`, `_ensure_profile_vectors()`, `detect_document_scope()`, `detect_baustein_scope()`, Integration in `retrieve()` |
| `apps/chainlit/settings.py` | `DOC_ROUTING_ENABLED`, `BAUSTEIN_ROUTING_ENABLED`, Schwellenwert-Parameter |
| `apps/chainlit/.env` / `.env.example` | Neue Flags ergänzen |

---

## Testfälle zur Kalibrierung

Vor Aktivierung (`DOC_ROUTING_ENABLED=true`) müssen die Schwellenwerte an folgenden Fällen kalibriert werden:

| Frage | Erwarteter Route | Erwarteter Filter |
|---|---|---|
| „Welche Schritte umfasst die Basis-Absicherung nach BSI-Standard 200-2?" | Schicht 1 (Regex) | `standard_id=standard_200_2` |
| „Wie führe ich eine Risikoanalyse im Rahmen des Sicherheitskonzepts durch?" | Schicht 2 (Semantik) | `standard_id=standard_200_2` |
| „Wie führe ich eine Risikoanalyse für erhöhten Schutzbedarf durch?" | Schicht 2 (Semantik) | `standard_id=standard_200_3` |
| „Wie plane ich ein Notfallkonzept?" | Schicht 2 (Semantik) | `standard_id=standard_200_4` |
| „Welche Arten von zentralen Speicherlösungen gibt es?" | Schicht 3 (Baustein) | `baustein_id=SYS.1.8` |
| „Welche Anforderungen stellt ORP.4 an Berechtigungsmanagement?" | kein Routing (Modell setzt baustein_id) | — |
| „Was sind die Kernaufgaben eines ISMS?" | Schicht 2 (Semantik) | `standard_id=standard_200_1` |

**Kritischer Testfall:** *„Risikoanalyse"* ohne Kontext darf keinen Filter setzen (zu ambig).

---

## Risiken und Grenzen

**Falsches Routing als aktive Verschlechterung:**  
Ein falscher Dokument-Filter sperrt alle korrekten Treffer aus — schlechter als kein Filter. Der Schwellenwert und die Mindestabstand-Bedingung in `detect_document_scope()` sind der zentrale Sicherheitsmechanismus. Im Zweifelsfall kein Filter (`None` zurückgeben).

**Multi-Baustein-Fragen:**  
Schicht 3 ist aktuell auf `baustein_id`-Filter ausgelegt (ein Baustein). Fragen, die mehrere Bausteine betreffen, werden nicht gefiltert (Fallback auf Standard-Retrieval). Multi-Baustein-Filter via `schicht_id` oder OR-Logik ist als TODO markiert.

**Kaltstart-Latenz:**  
`_ensure_profile_vectors()` berechnet beim ersten Aufruf 5 Embeddings (~50ms). Danach gecached. Kein messbarer Einfluss auf laufende Anfragen.

**Dokument-Profil-Pflege:**  
Die Profile müssen bei Änderungen am BSI-Dokumentenbestand (neue Standards, neue Kompendium-Edition) manuell aktualisiert werden.

---

## Implementierungsreihenfolge

1. **Schicht 1 (Regex)** — ~30 min, kein Risiko, sofortiger Nutzen für Standard-200-x-Fragen
2. **Profil-Definitionen** — ~1h, iterativ mit Testfällen schärfen
3. **Schicht 2 (Semantischer Dokument-Router)** — ~2h inkl. Schwellenwert-Kalibrierung
4. **Schicht 3 (Baustein-Router)** — ~2h, erfordert Validierung gegen SYS.1.8-Testfälle
5. **Integration + Feature-Flags** — ~1h
6. **RAGAS-Evaluation** gegen Testset (43 Komplex-Fragen) zum Nachweis der Verbesserung

---

## Nachtrag: Kopplung von HyDE und Routing (erkannt und behoben, Stand 2026-07-14)

### Beobachtung

Bei der Frage *„Was muss ich beim Aufbau eines ISMS beachten?"* lieferte das System weder den Kompendium-Baustein ISMS.1 noch die inhaltlich einschlägigen Abschnitte aus BSI-Standard 200-1 (Management-Prinzipien, Sicherheitsleitlinie, ISB, PDCA). Debug-Log-Auszug:

```
[DEBUG] HyDE generated: Beim Aufbau eines ISMS nach IT‑Grundschutz ist zunächst eine
        umfassende Schutzbedarfs‑ und Risikoanalyse der Zielobjekte...
[ROUTING] layer2_scores: standard_200_1=0.6756 gap=0.0092 threshold=0.63 min_gap=0.008
[ROUTING] layer2_semantic → boost standard_id=standard_200_1
```

Der Layer-2-Schwellenwert wurde nur knapp überschritten, und die anschließend geboostete Trefferliste aus `standard_200_1` bestand aus methodiknahen Abschnitten (S.12, S.30, S.40) statt der ISMS-Kernabschnitte. Zusätzlich verschärft durch `BAUSTEIN_ROUTING_ENABLED=false` zum Testzeitpunkt, wodurch ISMS.1 aus dem Kompendium gar nicht erst gesucht wurde.

### Ursache

`retrieve()` berechnete einen einzigen Such-Vektor aus dem HyDE-generierten Text und verwendete ihn für drei unterschiedliche Zwecke: Hauptretrieval, Layer-2-Dokumenten-Matching und Layer-3-Baustein-Matching. HyDE ist ein stochastischer LLM-Sample-Prozess, der den Suchtext stilistisch an Dokument-Chunks angleichen soll — nicht dafür ausgelegt, Themen korrekt zu klassifizieren. Bei thematisch unspezifischen Fragen ohne Fachterminologie (typisch für Laien-Nutzer) ist die HyDE-Ausgabe am stärksten streuungsanfällig, weil wenig Kontext zur Verankerung vorhanden ist — im Beispiel driftete der generierte Text von „ISMS-Aufbau" (200-1-Vokabular) zu „Schutzbedarfs-/Risikoanalyse" (200-2/200-3-Vokabular).

Wird derselbe, potenziell fehlgeleitete Vektor auch dem Routing zugrunde gelegt, wird ein Fehler der HyDE-Stufe nicht korrigiert, sondern unmittelbar in die Scope-Entscheidung fortgepflanzt — obwohl das Routing gerade zur Absicherung gegen die Fehlerklassen D1/D2 eingeführt wurde. HyDE und Routing verfolgen also inkompatible Ziele (Stil-Angleichung für Retrieval vs. Themen-Klassifikation), teilten sich aber dieselbe Eingaberepräsentation.

### Fix

`retrieve()` berechnet für Layer 2/3 jetzt einen eigenen, von HyDE unabhängigen `routing_vector` aus der rohen Nutzerfrage — unabhängig vom Zustand von `HYDE_ENABLED`. Der HyDE-Vektor bleibt ausschließlich für die eigentliche Chunk-Suche (Haupt- und Boost-Abfragen in `_qdrant_query`) zuständig. Layer 1 (Regex) war von diesem Problem nicht betroffen, da es direkt auf dem Fragetext arbeitet, nicht auf dessen Embedding.

`HYDE_ENABLED` und `DOC_ROUTING_ENABLED`/`BAUSTEIN_ROUTING_ENABLED` sind dadurch orthogonale Stellschrauben geworden: Scope-Erkennung und Retrieval-Qualität lassen sich unabhängig voneinander variieren, kombinieren und evaluieren, statt sich über einen gemeinsamen Vektor gegenseitig zu beeinflussen.

### Offene Folgefragen (dokumentiert, nicht umgesetzt)

- **Layer 2 als LLM-Klassifikation statt Embedding-Schwellenwert:** Die fünf `DOCUMENT_PROFILES`-Texte sind bereits als Klassifikationskriterien formuliert und ließen sich direkt als Prompt für eine LLM-Klassifikation nutzen — bei geringem Mehraufwand (kurzer Prompt, 5 Kategorien). Vorteil gegenüber dem aktuellen Schwellenwert-Verfahren: mehrere gleichzeitig relevante Dokumente können in einem Klassifikationsschritt zurückgegeben werden (z. B. „Aufbau ISMS" → `standard_200_1` **und** `ISMS.1` statt Winner-take-all).
- **Layer 3 bleibt bewusst embedding-basiert:** Bei 111 Bausteinen wäre eine vollständige Liste (ID, Titel, Kurzbeschreibung) im LLM-Prompt pro Anfrage mit mehreren tausend zusätzlichen Tokens verbunden und würde das ursprüngliche Ziel dieser Schicht — keine manuell gepflegte Profiltabelle — konterkarieren. Die bestehende Embedding-Suche gegen `baustein_beschreibung`-Chunks bleibt hier die wartungsärmere Lösung.
- **Boost-Mechanismus vs. sichtbarer Routing-Hinweis:** Diskutierte Alternative zum aktuellen, für das antwortende LLM unsichtbaren Chunk-Blending: Das Routing-Ergebnis wird als Metadatum im Tool-Ergebnis zurückgegeben, und das LLM entscheidet selbst (im Rahmen der bestehenden Aufruf-Obergrenze für `rag_retrieve`), ob ein zweiter, gezielt gefilterter Retrieval-Aufruf nötig ist, wenn die erste Trefferliste einen vom Router genannten Aspekt erkennbar unterrepräsentiert. Noch nicht implementiert.

---

## Nachtrag: Layer 1 zurück auf exklusiven Filter (Stand 2026-07-17)

**Befund:** Bei „Welche Schritte umfasst die Basis-Absicherung nach BSI-Standard 200-2?" feuerte Layer 1 korrekt (`layer1_regex`), trotzdem waren nur 6 von 12 finalen Treffern tatsächlich `standard_200_2`. Ursache: Der ursprüngliche Merge-Schritt (`sorted(points + boost_all)[:k]`) lässt Boost-Treffer nur nach Rohscore mit dem ungefilterten Hauptpool konkurrieren — fachfremde, aber generisch hoch scorende Treffer aus anderen Standards konnten die exklusiv gefilterten Boost-Treffer beim finalen Zuschnitt verdrängen. Das Prinzip „Routing schließt nie aus" galt damit nur für die Hauptabfrage, nicht für die gemeinsame Endauswahl.

**Fix:** Layer 1 (explizite, wörtliche Standard-Nennung) filtert die Hauptabfrage jetzt wieder **exklusiv** — wie im ursprünglichen Architekturentwurf oben vorgesehen (Schicht 1 → harter Filter), bevor der spätere Umbau auf „additiv statt exklusiv" das auf alle drei Schichten vereinheitlicht hatte. Begründung für die Sonderrolle von Layer 1: Eine wörtliche Nennung wie „BSI-Standard 200-2" ist im Gegensatz zu Layer 2 (Schwellenwert-Match) und Layer 3 (mögliche Mehrfach-Relevanz mehrerer Bausteine) nicht mehrdeutig — es gibt keinen Grund, hier zu hedgen. Layer 2/3 bleiben additiv/blended.

---

## Nachtrag: Warum `baustein_id` bei Themenfragen nicht vom LLM gesetzt werden sollte — Beleg CON.8/APP.7 (Stand 2026-07-17)

### Ausgangsfrage

Sollte die system.md-Regel gelockert werden, nach der das LLM `baustein_id` nur bei **wörtlicher** ID-Nennung setzen darf — nicht bei reiner Themenbeschreibung? Konkreter Testfall: *„Wie muss ich die Softwareentwicklung in meiner Behörde organisieren, wenn wir selbst ein Fachverfahren entwickeln wollen?"* — hier wäre `CON.8 Software-Entwicklung` der naheliegende Treffer, ohne dass „CON.8" im Text vorkommt.

### Prüfung anhand des Quelltexts

Ein Abgleich der Baustein-Titelliste allein reicht nicht aus, um diese Frage zu beantworten — er zeigt nicht, wie stark sich die *Inhalte* zweier ähnlich betitelter Bausteine überschneiden. Daher wurde der Rohtext (`data/data_raw/XML_Kompendium_2023.xml`) direkt herangezogen und die Einleitungen von `CON.8 Software-Entwicklung` und `APP.7 Entwicklung von Individualsoftware` verglichen:

> **CON.8:** „...Software-Lösungen, die auf ihre individuellen Anforderungen hin angepasst sind... (Individual-)Software kann durch die Institution selbst oder von einem Dritten entwickelt werden..."
>
> **APP.7:** „...Softwarelösungen, die auf die individuellen Bedürfnisse der Institutionen zugeschnitten sind... Individualsoftware kann auch vollständig neu von der Institution selbst oder von Dritten entwickelt werden... individuell angepasste Fachanwendungen..."

Die beiden Einleitungstexte sind nahezu deckungsgleich formuliert. Der fachliche Unterschied ist real, aber fein: **CON.8** behandelt den Entwicklungs*prozess* (Vorgehen, sichere SDLC, Anforderungsmanagement) als Konzept-Baustein der Schicht CON; **APP.7** behandelt die daraus entstehende Individualsoftware im *Betrieb* als Anwendungs-Baustein der Schicht APP. Bei der Testfrage sind **beide** Bausteine fachlich einschlägig, nicht nur einer.

### Schlussfolgerung

Dieser Befund spricht **gegen** eine Lockerung der system.md-Regel und **für** die bestehende Architekturentscheidung, Themenfragen ausschließlich über den additiven, nicht-exklusiven Layer-3-Router zu lösen:

1. Ein vom LLM aus reiner Themenerkennung gesetztes `baustein_id` ist ein **exklusiver** Hard-Filter. Da CON.8 und APP.7 hier gleichermaßen relevant sind, würde die LLM-Wahl eines der beiden Bausteine den jeweils anderen unbegründet ausblenden — unabhängig davon, ob die Wahl fachlich „richtig" war.
2. Layer 3 (`detect_baustein_scope()`) ist für genau diesen Fall gebaut: additiver Boost statt Exklusivfilter, mit `top_n=2` können CON.8 **und** APP.7 gleichzeitig einfließen, ohne dass einer der beiden verdrängt wird.
3. Das CON.x/APP.x-Muster (Konzept-Baustein und zugehöriger System-/Anwendungs-Baustein zum selben Sachverhalt, mit stark überlappendem Vokabular) ist im Kompendium kein Einzelfall — vermutlich zeigt sich dasselbe Muster bei `CON.10 Entwicklung von Webanwendungen` vs. `APP.3.1 Webanwendungen`. Das bestätigt strukturell, warum Layer 3 grundsätzlich mehrere Bausteine zurückgeben können muss, statt auf einen einzelnen Treffer zu optimieren.

**Konsequenz für die Umsetzung:** Nicht system.md wurde geändert. Stattdessen wurde die Testfrage als Fall 10 in [TASK_13_Testprotokoll.md](TASK_13_Testprotokoll.md) aufgenommen — zum Zeitpunkt dieses Nachtrags stand `BAUSTEIN_ROUTING_ENABLED=false` in der `.env`, wodurch Layer 3 für diesen Fall gar nicht erst lief. Das ist die eigentliche, noch zu behebende Ursache des schwachen Treffers, nicht die system.md-Formulierung.
