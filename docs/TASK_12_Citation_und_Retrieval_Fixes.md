# TASK_12: Citation- und Retrieval-Fixes vor der Fach-Community-Evaluierung

## Kontext

Live-Debugging-Session am 2026-06-29, zwei Tage vor geplantem Start der Fach-Community-Evaluierung. Ausgangspunkt war der `baustein_id`-Filter für `rag_retrieve` (Fix für bausteinübergreifendes Zitations-Mischen, siehe Vorarbeit zu TASK_07), der in der Praxis mehrere bis dahin unentdeckte Folgefehler in der Zitations- und Retrieval-Pipeline sichtbar machte. Diese Doc fasst die in dieser Session gefundenen und behobenen Ursachen zusammen. Ergänzt TASK_07–TASK_10, ersetzt sie nicht.

## Gefundene und behobene Fehler

### 1. `rag_retrieve`-Parameter-Missbrauch durch das Modell (`app.py`)

- `query` wurde teils auf eine bloße Baustein-/Anforderungs-ID reduziert (z. B. `"ORP.4"` statt einer natürlichsprachlichen Anfrage) — für die Embedding-Suche wertlos. Fix: Tool-Beschreibung präzisiert + Code-Sicherheitsnetz (`_BARE_ID_QUERY_RE`), das in diesem Fall auf die Originalfrage zurückfällt.
- `baustein_id` wurde mit Anforderungs-Suffix übergeben (`"OPS.2.2.A1"` statt `"OPS.2.2"`) → 0 Treffer. Fix: `_BAUSTEIN_ID_ONLY_RE` strippt den Suffix.
- `baustein_id` wurde aus dem **Gesprächsverlauf** übernommen, obwohl die aktuelle Frage die ID nicht nennt (Kontext-Bleed von der vorherigen Frage). Fix: `baustein_id` wird nur akzeptiert, wenn sie wörtlich in der aktuellen Nutzernachricht steht.

### 2. Falsche Quellen-Zuordnung trotz korrektem Retrieval (`app.py`, `rag_tool.py`)

Mehrere unabhängige Ursachen führten dazu, dass bei Aufzählungen mehrerer Anforderungen eines Bausteins alle (oder die meisten) auf dieselbe, falsche Quelle zeigten (typischerweise die generische Beschreibung/Gefährdungslage oder eine andere reale, aber falsche Anforderung):

- **`_extract_citation`** (`rag_tool.py`) nutzte für Kompendium-Chunks die Konstante `"grundschutz.json"` statt der individuellen Anforderungs-ID als In-Context-Hinweis ans Modell — neue gemeinsame Funktion `resolve_section_title()` behebt das (jetzt von `app.py` und `rag_tool.py` gemeinsam genutzt).
- **Dot/Space-Normalisierungsfehler** in `_canonicalize_citations`: die extrahierte BSI-ID behielt Punkte, der normalisierte Abschnittstitel nicht — Substring-Vergleich schlug dadurch immer fehl, das stärkste Unterscheidungsmerkmal war faktisch deaktiviert.
- **Fehlende Rückwärtssuche**: Wenn das Zitat selbst keine spezifische Anforderungs-ID trägt, aber die vorangehende Zeile damit beginnt (z. B. `"ORP.4.A4 Aufgabenverteilung..."`), wird diese jetzt zur Disambiguierung herangezogen.
- **Dedup-Key-Kollision** beim Sammeln der Quellen: mehrere unterschiedliche Anforderungen auf derselben PDF-Seite wurden zu einem Eintrag zusammengeführt (Key war `(Datei, Seite)`, jetzt `(Datei, Seite, Abschnittstitel)`).
- **Reihenfolge-Bug**: Die Filterung auf „tatsächlich zitierte" Aliase lief vor der Korrektur-Logik und verwarf dadurch alle Kandidaten außer dem einen (falschen), bevor er korrigiert werden konnte — Korrekturlauf wird jetzt vorgezogen.
- **Anzeige-Cap (`MAX_SOURCE_LINKS`) limitierte auch den Korrekturkandidatenpool**: Bei mehr als 8 aggregierten Treffern (mehrere Tool-Runden) fielen niedriger bewertete, aber tatsächlich zitierte Anforderungen aus dem Korrekturpool. Jetzt entkoppelt: `canon_rows` (ungekappt) für die Korrektur, `source_rows` (gekappt) nur für die Anzeige.
- **Exakte, aber inhaltlich falsche ID-Zitate** (Modell nennt real existierende Anforderung, die aber nicht zur Aussage passt, z. B. `SYS.1.8.A26` für A22-Inhalt): IDF-gewichteter Wortabgleich zwischen Bullet-Text und vollem Chunk-Text der Kandidaten ergänzt die reine ID/Seiten-Logik. Einfache Wortzählung scheiterte zunächst an bausteinweiter BSI-Standardsprache (z. B. „nicht benötigte ... deaktivieren" in mehreren Anforderungen) — Gewichtung mit `1/Häufigkeit über alle Kandidaten` unterdrückt generische Begriffe und bevorzugt thema-spezifische.
- **IDF-Verzerrung durch große, fachfremde Kandidatenpools**: Bei mehreren Tool-Runden sammeln sich schnell 20–30 Kandidaten aus völlig anderen Bausteinen an; die Seltenheits-Gewichtung über den kompletten Pool verzerrte, welche Wörter als „aussagekräftig" galten. Fix: Seltenheits-Vergleich nur noch über die 8 Kandidaten mit der höchsten rohen Wortüberlappung zur jeweiligen Aussage.
- **Bausteinübergreifende Falschzitate ohne jedes strukturelle Signal** (Modell zitiert dieselbe falsche ID für Inhalte aus mehreren völlig anderen Bausteinen): Inhaltsabgleich darf jetzt auch ganz ohne Seiten-/ID-Übereinstimmung gewinnen, wenn die Wortüberlappung eine Mindestschwelle übersteigt — mit eigenem Regressionstest gegen Fehlalarme auf unzusammenhängende Prosa.

### 3. Prompt-Klarheit (`system.md`)

- Explizite Regel: `baustein_id` nur bei wörtlicher ID-Nennung im Fragetext setzen, nicht bei Titel-/Themen-Erkennung.
- Explizite Regel: bei Aufzählung mehrerer Einzelanforderungen muss jede ihre eigene passende Quelle nennen, nicht die Bausteinbeschreibung als Sammelquelle.
- „Zusammenfassungen statt langer Listen": Anweisung präzisiert, dass weiterhin ein kurzer Aussagesatz pro Punkt nötig ist (nicht nur der Anforderungstitel), und dass bewusst nur ~5 Punkte gewählt werden sollen — **nicht erschöpfend sein wollen** ist jetzt explizit gewünschtes Verhalten, nicht Notlösung.

### 4. Retrieval-Recall (`.env`, Tool-Beschreibung)

`MAX_TOP_K` von 8 auf 16 erhöht (`.env`, `.env.example`), Tool-Beschreibung für `top_k` ergänzt: bei breiten Aufzählungsfragen („Welche Anforderungen...") einen höheren Wert anfordern. Mildert das in TASK_10 beschriebene Dense-Retrieval-Recall-Problem, löst es aber nicht — siehe dort.

## Bewusst nicht behoben (verwiesen auf bestehende Docs)

- **Inhalts-Validierung von Sonderfällen, die auch mit IDF-Gewichtung nicht auflösbar sind** (z. B. wenn die korrekte Anforderung gar nicht im Retrieval-Kandidatenpool war) → TASK_09 (LLM-as-Judge), bewusst zurückgestellt.
- **Dense-Retrieval-Recall-Lücken** (richtige Anforderung trotz exakter Terminologie nicht in Top-K) → TASK_10 (Hybrid Retrieval), drei dokumentierte Praxisbeispiele, Aufwand ca. 2–4 Personentage, zurückgestellt für nach der Evaluierung.

## Abbruchkriterium erreicht: Modell-seitige Titel-/Inhalts-Halluzination

Letzter beobachteter Fall (2026-06-29, Frage zu APP.3.2 mit >5 Anforderungen): Das Modell vergab in seiner eigenen Antwort **falsche oder erfundene Titel zu Anforderungs-IDs** — z. B. „APP.3.2.A2 Netzwerksegmentierung" (real: „Schutz der Webserver-Dateien") und vertauschte A4/A5 („A5 Protokollierung" statt „A4 Protokollierung"/„A5 Authentisierung"). Verifiziert gegen die echten Titel in Qdrant.

Das ist **keine Zitations-Routing-Frage mehr**, sondern Halluzination/Verwechslung in der Antwortgenerierung selbst — keine Nachbearbeitung der Zitate kann das beheben, da es keine korrekte Quelle gibt, auf die korrigiert werden könnte. An diesem Punkt wurde bewusst entschieden, **das Patchen des Canonicalizers zu beenden** (Aufwand/Nutzen-Verhältnis bei dieser Fehlerklasse ungünstig, Risiko weiterer Regressionen bei verbleibender Zeit bis zur Evaluierung zu hoch) und stattdessen:

- Risiko in `chainlit.md` unter „Bekannte Einschränkungen" explizit benannt (sehr breite Aufzählungsfragen als höheres Risiko gekennzeichnet, konkretere Teilfragen empfohlen).
- Keine weitere Code-Änderung an `_canonicalize_citations` für diese Fehlerklasse.

**Für eine spätere, eigenständige Untersuchung** (nach der Evaluierung): stärkere Grounding-Anweisung in `system.md` (Titel UND Inhalt müssen wörtlich aus dem Kontext stammen) oder Wegfall der ID-Wiederholung im Bullet-Präfix, um Verwechslungen im Lesefluss zu vermeiden — beide nicht umgesetzt, siehe Diskussion in dieser Session.

## Nutzerkommunikation

`chainlit.md` (in-App-Hinweise) um Abschnitt „Bekannte Einschränkungen" ergänzt — Quellenangaben-Präzision und Suchtreffer-Genauigkeit als bewusst benannte, positiv gerahmte Evaluierungsgegenstände statt verschwiegener Mängel.
