# Technologische Grundlagen – Pilotprojekt GrundschutzKI

Dieses Dokument erklärt die fünf Kerntechnologien des Projekts: **LLM, RAG, Vektordatenbank, Docker und Git** – jeweils kompakt und direkt bezogen auf das, was du im Projekt siehst.

---

## 1. Large Language Model (LLM)

> 📺 **Erklärvideo:** [Große Sprachmodelle kurz erklärt (~ 8 min)](https://youtu.be/LPZh9BOjkQs?si=hs2CEG-p8jPTAzgF)

Ein **LLM** (Large Language Model) ist ein Sprachmodell, das auf riesigen Textmengen trainiert wurde und daraus lernt, wahrscheinliche Fortsetzungen eines Textes zu berechnen. Bekannte Beispiele: GPT-4, Llama 3, Mistral.

**Wie funktioniert das konkret?** Ein LLM sagt immer nur das *nächste Wort* (genauer: das nächste Token) vorher – auf Basis des bisherigen Textes und gelernter Gewichte. Dabei wird keine Regel explizit programmiert, sondern aus Milliarden von Textbeispielen statistisch gelernt, welche Fortsetzung wie wahrscheinlich ist.

Besonders deutlich wird das am Beispiel des Wortes „Bank": Der Kontext entscheidet, welche Bedeutung wahrscheinlich ist:
- „Sie saßen am Ufer der …" → hohes Gewicht für *Bank* im Sinne von Flussufer
- „Er überwies Geld auf sein Konto bei der …" → hohes Gewicht für *Bank* im Sinne von Geldinstitut

Das Modell hat keine explizite Regel für Wortbedeutungen – es hat gelernt, welche Wörter in welchem Kontext typischerweise folgen. Dieses Prinzip, Token für Token angewendet, erzeugt kohärente Texte, Schlussfolgerungen und Antworten.

**Wichtig zu verstehen:** Ein LLM hat kein Gedächtnis und kein Internet. Es beantwortet Fragen ausschließlich aus dem, was ihm beim Training begegnet ist – plus dem Text, der ihm gerade als Eingabe (Prompt) übergeben wird. Große Modelle wie GPT-4 kennen den IT-Grundschutz durchaus aus ihren Trainingsdaten. Dennoch setzt GrundschutzKI auf RAG (→ Abschnitt 2): weil parametrisches Wissen unzuverlässig ist (das Modell kann Anforderungen verwechseln, paraphrasieren oder halluzinieren), weil wir eine konkrete Edition (2023) zitierbar machen wollen, und weil die Wissensbasis so lokal kontrolliert und aktualisierbar bleibt.

---

## 2. RAG – Retrieval-Augmented Generation

> 📺 **Erklärvideo:** [What is Retrieval-Augmented Generation? (IBM, ~8 min)](https://youtu.be/UabBYexBD4k?si=9bc0nPlNpt-VBlWw)

**RAG** löst das Problem, dass LLMs nur das kennen, was sie gelernt haben. Statt das Kompendium ins Modell zu trainieren (teuer, schwer aktualisierbar), wird es zur Laufzeit als Kontext mitgegeben.

**Ablauf bei jeder Nutzerfrage:**

```
Nutzerfrage
    │
    ▼
[1] Embedding der Frage  →  Qdrant (Vektorsuche)  →  Top-K Textabschnitte
                                                           │
    ┌──────────────────────────────────────────────────────┘
    │
    ▼
[2] Prompt = System-Prompt + Kontext-Abschnitte + Frage
    │
    ▼
[3] LLM generiert Antwort mit Quellenangaben
```

**Drei Schlüsselkonzepte:**

- **Chunk**: Das Kompendium ist in ~3.000 kleine Textabschnitte (Chunks) zerlegt. Jeder Chunk entspricht z. B. einer Anforderung wie `APP.3.2.A5` oder einem Bausteinabschnitt.
- **Embedding**: Jeder Chunk wird in einen hochdimensionalen Zahlenvektor umgewandelt, der seine inhaltliche Bedeutung kodiert. Ähnliche Texte → ähnliche Vektoren.
- **Top-K Retrieval**: Die K Chunks mit dem höchsten semantischen Ähnlichkeitswert zur Frage werden dem LLM als Kontext übergeben.

**Im Projekt:** Die Retrieval-Logik liegt in [apps/chainlit/rag_tool.py](../apps/chainlit/rag_tool.py). Der Parameter `TOP_K=8` in der `.env` steuert, wie viele Chunks abgerufen werden. Der Score-Schwellwert `SCORE_THRESHOLD=0.3` filtert thematisch unpassende Ergebnisse heraus. Die Quellenangaben in der Antwort (z. B. `Quelle: APP.3.2.A5`) basieren auf den Metadaten der retrievierten Chunks.

---

## 3. Vektordatenbank – Qdrant

> 📺 **Erklärvideo:** [What is a Vector Database? (IBM, ~7 min)](https://youtu.be/gl1r1XV0SLw?si=SbDCcaJjX9yha8mM)

Eine **Vektordatenbank** speichert keine Zeilen und Spalten wie eine SQL-Datenbank, sondern hochdimensionale Vektoren (Embeddings) zusammen mit den dazugehörigen Texten und Metadaten. Die zentrale Suchoperation ist nicht `WHERE text = '...'`, sondern *„Finde die K Vektoren, die diesem Anfragevektor am ähnlichsten sind"* (Nearest-Neighbor-Suche).

**Warum nicht einfach Volltextsuche?**
Volltextsuche findet Wörter – Vektorsuche findet *Bedeutung*. Fragt man nach „Wie schütze ich Passwörter auf einem Webserver?", findet Vektorsuche auch Chunks, die das Wort „Passwort" nicht enthalten, aber inhaltlich passen (z. B. Chunks über Authentisierung, Hashing, Zugriffsschutz).

**Im Projekt:**

```
Qdrant läuft als Docker-Container: gski-qdrant (Port 6333)
Collection: grundschutz_bge_m3
Embedding-Modell: BAAI/bge-m3 (1024 Dimensionen)
Punktzahl (Score): Kosinus-Ähnlichkeit zwischen Anfrage- und Chunk-Vektor
```

Daten prüfen mit dem enthaltenen Skript:

```bash
# Struktur der Collection anzeigen
python scripts/query_qdrant.py structure

# Alle Anforderungen eines Bausteins anzeigen
python scripts/query_qdrant.py filter --where baustein_id=APP.3.2 --show-text

# Keyword-Suche über Chunk-Texte
python scripts/query_qdrant.py search --text "Notfallkonzept"
```

Der Ingest-Prozess (einmaliger Job beim ersten `docker compose up`) liest das Kompendium, zerlegt es in Chunks, erzeugt Embeddings und schreibt alles in Qdrant. Details: [apps/chainlit/ingest.py](../apps/chainlit/ingest.py).

Die gespeicherten Chunks und Collections lassen sich direkt im Browser erkunden: [http://localhost:6333/dashboard](http://localhost:6333/dashboard)

---

## 4. Docker

**Docker** verpackt eine Anwendung mit all ihren Abhängigkeiten (Python-Pakete, Konfigurationen, Umgebungsvariablen) in einen **Container** – ein isoliertes, portables Laufzeitpaket. Egal ob dein Laptop Ubuntu oder macOS hat: Der Container läuft identisch. **Docker Compose** startet mehrere Container gemeinsam und definiert, wie sie miteinander kommunizieren.

**Im Projekt laufen vier Container:**

| Container | Aufgabe | Port |
|---|---|---|
| `gski-chainlit` | Web-App + Chat-Logik | 8000 |
| `gski-qdrant` | Vektordatenbank | 6333 |
| `gski-postgres` | Nutzer-Accounts, Chat-Historie | 5432 |
| `gski-ingest` | Befüllt Qdrant (läuft einmalig) | – |

Konfiguriert in [apps/chainlit/docker-compose.yml](../apps/chainlit/docker-compose.yml).

**Wichtigste Befehle aus `apps/chainlit/`:**

```bash
# Alle Container starten (im Hintergrund, Images bauen falls nötig)
sudo docker compose up -d --build

# Status prüfen
sudo docker compose ps

# Live-Logs der App anzeigen (Strg+C beendet nur die Anzeige, nicht den Container)
sudo docker compose logs -f chainlit

# Einen Container neu starten (z. B. nach Code-Änderungen – .py-Dateien sind eingehängt)
sudo docker compose restart chainlit

# Alle Container stoppen
sudo docker compose down
```

**Code-Änderungen** an `.py`-Dateien sind per Volume-Mount sofort im Container sichtbar – ein `restart chainlit` reicht. Änderungen an der `.env` oder dem `Dockerfile` erfordern `up -d` (bzw. `--build`).

**Web-Oberflächen im Browser:**

| URL | Dienst | Zweck |
|---|---|---|
| http://localhost:8000 | Chainlit | Chat-UI (Login: admin / admin) |
| http://localhost:6333/dashboard | Qdrant | Vektordatenbank – Collections, Chunks, Suche |

---

## 5. Git – Versionskontrolle

**Git** ist das Werkzeug, mit dem Änderungen am Code nachvollziehbar gespeichert und zwischen Teammitgliedern ausgetauscht werden. Jede Änderung wird in einem **Commit** festgehalten – mit Autor, Zeitstempel und Beschreibung. Ein **Branch** ist ein paralleler Entwicklungsstrang, sodass mehrere Personen gleichzeitig arbeiten können, ohne sich in die Quere zu kommen.

**Im Projekt:** Du arbeitest nie direkt auf `main`, sondern auf deinem eigenen Feature-Branch. Wenn du fertig bist, öffnest du einen **Pull Request** auf GitHub, der von anderen geprüft und dann in `main` gemergt wird.

**Typischer Arbeitsablauf – Schritt für Schritt:**

```bash
# 1. Auf den aktuellen Stand von main wechseln
git checkout main
git pull                          # Neuesten Stand vom Server holen ("Update")

# 2. Eigenen Branch anlegen und wechseln
git checkout -b feat/dein-name/meine-aenderung
# checkout -b = Branch erstellen UND sofort hineinwechseln
# Namenskonvention: feat/... · fix/... · docs/... · chore/...

# --- Jetzt Änderungen vornehmen ---

# 3. Geänderte Dateien für den nächsten Commit vormerken ("stagen")
git add apps/chainlit/app.py      # einzelne Datei
git add apps/chainlit/            # ganzes Verzeichnis
# Niemals: git add .  (kann versehentlich .env oder große Dateien mitaufnehmen)

# 4. Commit erstellen – eine atomare, beschriebene Änderungseinheit
git commit -m "feat: Quellenvalidierung per CITATION_VALIDATION Flag"
# Erste Zeile: Typ + kurze Beschreibung (was und warum, nicht wie)

# 5. Branch auf GitHub hochladen ("pushen")
git push -u origin feat/dein-name/meine-aenderung
# -u origin: verknüpft den lokalen Branch mit dem Remote – danach reicht git push

# 6. Branch aktuell halten (wenn andere in main committen)
git pull origin main --rebase
```

**Den eigenen Branch aktualisieren** (wenn `main` sich weiterentwickelt hat):

```bash
git checkout main
git pull
git checkout feat/dein-name/meine-aenderung
git merge main               # oder: git rebase main
```

**Nützliche Statusbefehle:**

```bash
git status          # Welche Dateien sind geändert / gestaged?
git log --oneline   # Commit-Historie (kompakt)
git diff            # Was hat sich seit dem letzten Commit geändert?
```

**Was gehört nicht ins Repository?**
- `.env`-Dateien (API-Keys, Passwörter) – stehen in `.gitignore`
- Große Binärdateien (PDFs, Modellgewichte) – liegen unter `data/` (ebenfalls `.gitignore`)
- Generierte Artefakte (`.pyc`, `__pycache__`, `.venv`)

---

*Weiterführend: Das Onboarding-Dokument ([docs/gski-onboarding.pdf](gski-onboarding.pdf)) führt durch den ersten Projekttag und erklärt die Gesamtarchitektur. Für tiefere Einblicke in einzelne Module: [docs/software/](software/).*
