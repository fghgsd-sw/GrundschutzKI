# Onboarding – Pilotprojekt GrundschutzKI

**Repository:** https://github.com/fghgsd-sw/GrundschutzKI

Willkommen im Team. Dieses Dokument führt dich Schritt für Schritt durch den ersten Tag im Projekt – vom Klonen des Repositories bis zu deiner ersten eigenen Code-Aufgabe. Es ist bewusst ausführlich gehalten und erklärt nicht nur **wie**, sondern auch **warum** etwas getan wird.

> Wenn dir ein Begriff begegnet, den du nicht kennst (z. B. „RAG", „Embedding", „Branch"), schau zuerst ins [Mini-Glossar](#mini-glossar) am Ende. Falls dort nichts steht, frag im Team-Chat – es gibt keine dummen Fragen in der ersten Woche.

---

## 0. Was ist dieses Projekt?

**GrundschutzKI** ist ein KI-Assistent (Chatbot), der Fragen zum **IT-Grundschutz-Kompendium des BSI** beantwortet. Technisch ist es ein **RAG-System** (Retrieval-Augmented Generation): Statt das Wissen ins Sprachmodell hineinzutrainieren, suchen wir bei jeder Frage zur Laufzeit die passenden Stellen aus dem Kompendium heraus und schicken sie zusammen mit der Frage an ein Sprachmodell (LLM).

Vereinfachte Pipeline:

```
Nutzerfrage
   │
   ▼
[Embedding der Frage]  ───▶  Qdrant (Vektor-Datenbank)  ──▶  Top-K passende Textabschnitte
   │
   └─────┬───────────────────────────────────────────────┘
         ▼
   [LLM (z. B. Llama 3.3, gpt-oss-120b)] ──▶ Antwort mit Quellenangaben
         ▼
   Anzeige in der Chainlit-Web-UI
```

Drei Komponenten, die du dir merken solltest:

| Komponente | Rolle | Wo zu finden |
|---|---|---|
| **Chainlit-App** | Web-UI + Chat-Logik | [apps/chainlit/](../apps/chainlit/) |
| **Qdrant** | Vektor-Datenbank, hält die eingelesenen Kompendium-Abschnitte | Docker-Container, kein Code-Verzeichnis |
| **Ingest** | Liest PDFs/JSONs, zerschneidet in Chunks, erzeugt Embeddings, schreibt in Qdrant | [apps/chainlit/ingest_docling.py](../apps/chainlit/ingest_docling.py) |

---

## 1. Wo läuft was – Anwendungsarchitektur

Eine zentrale Eigenheit dieses Projekts: **Daten und Anwendungs­logik liegen lokal, das Sprachmodell selbst wird remote angebunden.** Das spart Hardware (LLMs in der Größe von Llama-3.3-70B oder gpt-oss-120b laufen nicht auf einem Laptop) und behält gleichzeitig die Kontrolle über die Wissensbasis bei uns.

```
┌─────────────────────────────────────────────────────────────────────┐
│ Dein Laptop (Docker Compose)                                        │
│                                                                     │
│  ┌────────────────┐  ┌──────────────┐  ┌──────────┐  ┌───────────┐  │
│  │ Chainlit-App   │  │ Qdrant       │  │ Postgres │  │ Ingest    │  │
│  │ (Web-UI :8000) │◄─┤ (Vektor-DB)  │  │ (Users,  │  │ (einmal)  │  │
│  │ Python/FastAPI │  │ :6333        │  │  Chats)  │  │           │  │
│  └────────┬───────┘  └──────────────┘  └──────────┘  └─────┬─────┘  │
│           │                ▲                                │       │
│           │                │ (Embeddings + Texte schreiben) │       │
│           │                └────────────────────────────────┘       │
│           │                                                         │
│           │ HTTPS (LLM-Completion + Embedding)                      │
└───────────┼─────────────────────────────────────────────────────────┘
            │
            ▼
   ┌──────────────────────────────────────┐
   │ Cloud-LLM-Provider (extern)          │
   │                                      │
   │  ┌────────────────────────────────┐  │
   │  │ HPI AI Service Center          │  │
   │  │ api.aisc.hpi.de                │  │
   │  │ → gpt-oss-120b, octen-embed,   │  │
   │  │   llama-3-3-70b, granite-4-h   │  │
   │  └────────────────────────────────┘  │
   │  ┌────────────────────────────────┐  │
   │  │ IONOS AI Model Hub             │  │
   │  │ openai.inference…ionos.com     │  │
   │  │ → Llama-3.3-70B, BGE-M3, …     │  │
   │  └────────────────────────────────┘  │
   └──────────────────────────────────────┘

   Optional / Fallback:
   ┌──────────────────────────────────────┐
   │ Lokale Modelle via Ollama            │
   │ host.docker.internal:11434           │
   │ → llama-3.2 etc. (kleinere Modelle)  │
   └──────────────────────────────────────┘
```

### Lokal (Docker)

| Service | Container-Name | Port | Aufgabe |
|---|---|---|---|
| Chainlit-App | `gski-chainlit` | 8000 | Web-UI + Chat-Logik |
| Qdrant | `gski-qdrant` | 6333 | Vektor-DB |
| Postgres | `gski-postgres` | 5432 | Nutzer-Accounts, Chat-Historie |
| Ingest | `gski-ingest` | – | einmaliger Job, der Qdrant befüllt |

Alles unter [apps/chainlit/docker-compose.yml](../apps/chainlit/docker-compose.yml) konfiguriert.

### Remote (Cloud-LLM)

Welcher Provider aktiv ist, steuert `LLM_PROVIDER` in der `.env`:

| Wert | Provider | Endpoint | Wann |
|---|---|---|---|
| `1` | HPI AI Service Center | `https://api.aisc.hpi.de/v1` | Default für Entwicklung |
| `2` | IONOS AI Model Hub | `https://openai.inference.de-txl.ionos.com/v1` | Wenn HPI down / spezielle Modelle |
| `3` | Lokal (Ollama) | `http://host.docker.internal:11434/v1` | Offline-Tests mit kleinen Modellen |

**Wichtige Konsequenzen:**
- Du brauchst Internet-Zugang zum HPI- oder IONOS-Endpoint, sonst bleibt die App stumm.
- Daten (Kompendium, Standards, Fragen) liegen unter `data/` lokal und werden **nicht** an den LLM-Provider hochgeladen – nur die jeweils retrieveten Snippets gehen pro Anfrage als Kontext mit.
- Beim Wechsel des Providers musst du oft auch die Modell-IDs anpassen – jeder Provider listet die Modelle anders (siehe [docs/TASK_02_Modell_Fallback.md](TASK_02_Modell_Fallback.md)).

---

## 2. Voraussetzungen installieren

Bevor es losgeht, brauchst du auf deinem Rechner:

| Tool | Wofür | Installation |
|---|---|---|
| **Git** | Versionskontrolle | `sudo apt install git` (Linux) / [git-scm.com](https://git-scm.com) (Win/Mac) |
| **Docker + Docker Compose** | Container-Engine für Qdrant, Postgres, App | [docs.docker.com/get-docker](https://docs.docker.com/get-docker/) |
| **VS Code** | Code-Editor | [code.visualstudio.com](https://code.visualstudio.com) |
| **Python 3.12** | Skripte ausführen (außerhalb von Docker) | `sudo apt install python3.12 python3.12-venv` |

**VS Code Extensions empfohlen:**
- `Python` (Microsoft)
- `Docker` (Microsoft)
- `GitLens` (zeigt git-Historie inline)
- `Pylance` (Type-Checking)

Verifikation in einem Terminal:

```bash
git --version           # >= 2.30
docker --version        # >= 24
docker compose version  # >= 2.20
python3 --version       # 3.12.x
```

---

## 3. Repository klonen

Repository: **https://github.com/fghgsd-sw/GrundschutzKI**

Voraussetzung: Dein GitHub-Account muss vom Projektleiter als Mitwirkender hinzugefügt sein. Falls noch nicht geschehen, schick deinen GitHub-Usernamen rüber.

```bash
cd ~/Dokumente   # oder wohin du Projekte normalerweise legst
git clone https://github.com/fghgsd-sw/GrundschutzKI.git pilotprojekt-GrundschutzKI
cd pilotprojekt-GrundschutzKI
code .           # öffnet das Projekt in VS Code
```

**Was passiert dabei?**
- `git clone` lädt eine vollständige Kopie des Repositories inkl. aller Branches und der gesamten Historie herunter.
- `code .` startet VS Code im aktuellen Verzeichnis. Beim ersten Öffnen fragt VS Code evtl., ob du dem Workspace vertraust → ja.

> **SSH statt HTTPS** wird empfohlen, sobald du einen SSH-Key bei GitHub hinterlegt hast: `git clone git@github.com:fghgsd-sw/GrundschutzKI.git pilotprojekt-GrundschutzKI`. Spart dir das ständige Passwort-/PAT-Eintippen beim Push.

---

## 4. Eigenen Branch anlegen

Ein **Branch** ist eine parallele Entwicklungslinie. Du arbeitest **nie direkt auf `main`** – sondern in deinem eigenen Branch. Wenn du fertig bist, schlägst du deinen Branch per **Pull Request (PR)** zur Übernahme nach `main` vor.

**Warum?** So bleibt `main` immer in einem funktionierenden Zustand und alle Änderungen werden vor dem Merge geprüft.

Branch erstellen und in ihn wechseln:

```bash
git checkout main                         # falls du nicht schon auf main bist
git pull                                  # neuesten Stand holen
git checkout -b feat/<dein-name>/onboarding
# z. B. feat/anna/onboarding
```

**Namens-Konvention** in diesem Projekt:
- `feat/...` – neues Feature
- `fix/...` – Bugfix
- `docs/...` – nur Dokumentation
- `chore/...` – Aufräumarbeiten

Der Branch existiert vorerst nur lokal. Erst beim ersten `git push -u origin <branch>` landet er auf GitHub.

---

## 5. Repo-Struktur kennenlernen

Verschaffe dir einen Überblick. Nicht alles auf einmal verstehen – das ist normal:

```
pilotprojekt-GrundschutzKI/
├── apps/
│   └── chainlit/                   # die eigentliche Web-App + Ingest
│       ├── app.py                  # Chat-Hauptlogik, Tool-Loop
│       ├── llm.py                  # LLM-Aufrufe (Wrapper um LiteLLM)
│       ├── rag_tool.py             # Retrieval aus Qdrant
│       ├── ingest_docling.py       # Daten einlesen → Qdrant
│       ├── settings.py             # Konfiguration aus .env
│       ├── docker-compose.yml      # Container-Setup
│       └── .env.example            # Vorlage für deine .env
├── data/
│   ├── data_raw/                   # Original-PDFs (Kompendium, Standards)
│   ├── data_docling_json_ocr/      # vorverarbeitete JSON (für Ingest)
│   ├── data_preprocessed/          # strukturierte Daten (grundschutz.json)
│   ├── data_evaluation/            # Fragebogen-Datasets
│   └── results/                    # Eval-Ausgaben (CSV)
├── scripts/                        # CLI-Skripte (Eval, Ground-Truth-Regen)
├── notebooks/                      # Notebook-Helfer (litellm_client.py, .env)
├── docs/                           # Doku-Dateien (du liest gerade eine)
│   ├── software/                   # technische Modul-Dokus
│   └── TASK_*.md                   # offene Arbeitspakete
├── system.md                       # Produktions-System-Prompt
└── README.md
```

> **Lese-Reihenfolge zur Orientierung**: erst [README.md](../README.md), dann [docs/chainlit-app-dokumentation.md](chainlit-app-dokumentation.md), dann ein bis zwei Dateien aus [docs/software/](software/) (z. B. [apps_chainlit_rag_tool.md](software/apps_chainlit_rag_tool.md)).

---

## 6. `.env`-Dateien einrichten

Die Anwendung liest sensible Konfigurationen (API-Keys, Endpoints, DB-Zugänge) aus `.env`-Dateien, **die nie ins Repository eingecheckt werden** (stehen in `.gitignore`).

### Wo `.env`-Dateien hingehören

Es gibt **zwei** `.env`-Dateien, jede mit eigenem Zweck:

| Pfad | Wird gelesen von | Wozu |
|---|---|---|
| [apps/chainlit/.env](../apps/chainlit/.env) | Chainlit-Container (App + Ingest) | LLM-Routing, Qdrant, Auth, OAuth, SMTP |
| [notebooks/.env](../notebooks/.env) | Python-Skripte unter `scripts/` und `notebooks/` | LLM-Routing (gleiche Variablen, weil dieselben Endpoints) |

**Beide musst du anlegen.** Der Inhalt ist überwiegend identisch – am einfachsten kopieren.

### Vom Projektleiter bekommst du

Eine fertige `.env` mit echten API-Keys und Secrets wird dir **separat** zugeschickt (nicht über Git, nicht über öffentliche Kanäle). Pack sie an die beiden oben genannten Stellen:

```bash
# Wenn dir die Datei z. B. als gski.env zugeschickt wurde:
cp /pfad/zu/gski.env apps/chainlit/.env
cp /pfad/zu/gski.env notebooks/.env
```

### Falls du sie noch nicht hast

Zur Überbrückung kannst du dir aus dem Template eine eigene anlegen und die LLM-Keys leer lassen – dann läuft Ingest/UI nicht, aber du kannst zumindest die Struktur erkunden:

```bash
cp apps/chainlit/.env.example apps/chainlit/.env
cp apps/chainlit/.env.example notebooks/.env
# danach in beiden Dateien CHAINLIT_AUTH_SECRET setzen:
openssl rand -hex 16    # Ausgabe in CHAINLIT_AUTH_SECRET= eintragen
```

### Die wichtigsten Variablen im Überblick

```dotenv
LLM_PROVIDER=1                     # 1=HPI, 2=IONOS, 3=lokal Ollama
LITELLM_BASE_URL=https://api.aisc.hpi.de/v1
LITELLM_API_KEY=<vom-projektleiter>
LITELLM_CHAT_MODEL=openai/gpt-oss-120b
LITELLM_EMBED_MODEL=openai/octen-embedding-8b
QDRANT_COLLECTION=grundschutz
CHAINLIT_AUTH_SECRET=<eigenes-secret>
```

Erklärung der Provider-Logik und der LITELLM_*-Namens­konvention: siehe Abschnitt 1 oben.

---

## 7. Container bauen & starten

Das gesamte System läuft in Docker-Containern. Du brauchst **nicht** Python-Pakete lokal zu installieren, um die App zu starten.

```bash
cd apps/chainlit
docker compose up -d --build
```

**Was passiert hier?**
- `docker compose` liest die `docker-compose.yml` und startet alle dort definierten Services.
- `-d` heißt „detached" (im Hintergrund).
- `--build` baut die Images neu, falls das Dockerfile sich geändert hat – beim ersten Mal nötig.
- Die Services sind: **Postgres** (User-DB), **Qdrant** (Vektor-DB), **Ingest** (einmaliger Job), **Chainlit** (die App).

Status prüfen:

```bash
docker compose ps
```

Erwartet: alle Services laufen außer `ingest`, das einmal durchläuft und sich beendet.

**Logs anschauen** (wichtig für Fehlerdiagnose):

```bash
docker compose logs -f chainlit       # folgt den Live-Logs der App
docker compose logs ingest            # Ingest-Verlauf
```

`Strg+C` beendet `logs -f`, **stoppt aber nicht die Container**.

---

## 8. Den initialen Ingest verstehen

Beim ersten Start läuft der **Ingest-Job** automatisch:

1. Liest die Docling-JSON-Dateien aus `data/data_docling_json_ocr/`
2. Zerschneidet jeden Baustein des Kompendiums in semantische Sections (siehe [docs/notebooks-ingest-beschreibung.md](notebooks-ingest-beschreibung.md))
3. Erzeugt für jede Section ein **Embedding** (Vektor mit hunderten/tausenden Floats, der die Bedeutung des Textes kodiert)
4. Schreibt Text + Embedding + Metadaten in Qdrant unter der Collection `grundschutz`

Das dauert beim ersten Mal mehrere Minuten. Du kannst zuschauen mit:

```bash
docker compose logs -f ingest
```

**Verifikation**: Wenn der Ingest durch ist, sollten in Qdrant Punkte liegen:

```bash
curl http://localhost:6333/collections/grundschutz
# erwartet: JSON mit "points_count": <eine-Zahl-im-Tausender-Bereich>
```

> Falls die Collection schon existiert (z. B. weil du den Stack zum zweiten Mal startest), überspringt der Ingest seine Arbeit. Erzwingen mit `INGEST_RECREATE=true` in der `.env`.

---

## 9. App im Browser testen

```
http://localhost:8000
```

Login mit den Credentials aus deiner `.env` (Default: `admin` / `admin`).

Stelle eine Test-Frage, z. B.: *„Was ist der Unterschied zwischen Prozess- und Systembausteinen?"*

Wenn die App antwortet, mit Quellenverweisen in der Sidebar – herzlichen Glückwunsch, dein lokales Setup steht.

**Wenn etwas nicht funktioniert** – häufige Ursachen:

| Symptom | Ursache | Lösung |
|---|---|---|
| App lädt nicht | Container nicht gestartet | `docker compose ps`, `docker compose up -d` |
| „Connection refused" zum LLM | `LITELLM_BASE_URL` falsch / VPN nötig | Endpoint mit `curl` testen |
| Leere Antworten | Qdrant leer | Logs vom `ingest`-Service prüfen |
| `gpt-oss-120b not available` | Modell-ID stimmt nicht mit Provider-Katalog | siehe [docs/TASK_02_Modell_Fallback.md](TASK_02_Modell_Fallback.md) |

---

## 10. Zwei Wege zum RAG: Chainlit-GUI vs. Skripte

Bis hierhin hast du die **Chainlit-App** kennengelernt – das ist die Web-UI, mit der Endnutzer den Chatbot bedienen. Es gibt aber **einen zweiten Zugang** zum gleichen RAG-Stack, der für deine erste Aufgabe relevant ist: **Python-Skripte**.

| | Chainlit-App | Skripte (z. B. unter [scripts/](../scripts/)) |
|---|---|---|
| **Zweck** | Interaktive Nutzung: ein Nutzer stellt eine Frage, sieht die Antwort | Batch-Verarbeitung: viele Fragen automatisch durchlaufen, Ergebnisse als CSV |
| **UI** | Webseite unter http://localhost:8000 | Kommandozeile (CLI) |
| **Anfrage-Ursprung** | Tastatureingabe im Browser | Datei (CSV/JSON) als Eingabe |
| **Antwort-Senke** | Chat-Bubble + Sidebar mit Quellen | CSV-Datei mit Spalten pro Auswertung |
| **Typische Nutzung** | Demo, manuelles Testen, Endnutzer-Betrieb | Evaluation, Ground-Truth-Generierung, Massentests |
| **Beispiele im Repo** | [apps/chainlit/app.py](../apps/chainlit/app.py) | [scripts/run_evaluation.py](../scripts/run_evaluation.py), [scripts/regenerate_ground_truth_answers.py](../scripts/regenerate_ground_truth_answers.py) |

**Was beide gemeinsam haben:**
- Sie nutzen **dieselbe Qdrant-Collection** (z. B. `grundschutz`) für die Retrieval-Suche.
- Sie sprechen **denselben LLM-Endpoint** an (HPI oder IONOS, je nach `LLM_PROVIDER`).
- Sie verwenden **denselben System-Prompt** ([system.md](../system.md)), wenn produktions­konformes Verhalten gewünscht ist.

**Was sich unterscheidet:**
- Skripte können **parallel** viele Fragen verarbeiten (`asyncio.gather`), die App immer eine Frage zur Zeit.
- Skripte haben **kein Login**, sondern lesen ihre Konfiguration direkt aus `notebooks/.env`.
- Skripte können auf **das Tool-Calling im Chainlit-Flow verzichten** und Retrieval/LLM direkt orchestrieren – das macht sie einfacher zu lesen.

Für deine erste Aufgabe schreibst du ein **Skript** – nicht direkt für die Chainlit-App. Du baust nicht die UI um, sondern erstellst eine eigenständige Batch-Auswertung, die denselben RAG-Stack im Hintergrund nutzt.

---

## 11. Python-Virtualenv (`.venv`) für die Skripte

Während die **Chainlit-App komplett in Docker läuft** und du dort keine Python-Pakete lokal brauchst, ist das für **Skripte unter `scripts/` und `notebooks/` anders**: Die führst du direkt mit deinem System-Python aus, und sie brauchen viele Bibliotheken (litellm, ragas, qdrant-client, pandas, instructor, …). Damit diese Bibliotheken **isoliert vom System-Python** installiert werden – und damit verschiedene Projekte sich nicht in die Quere kommen – nutzen wir ein **virtuelles Environment** (`venv`).

### Was ein venv ist (kurz)

Ein venv ist ein Ordner (hier: `.venv/`), in dem eine eigene Python-Installation plus alle Pakete des Projekts liegen. Wenn das venv „aktiviert" ist, zeigt `python` und `pip` auf diese isolierte Umgebung, nicht auf dein System.

### venv anlegen

Im Projekt-Wurzelverzeichnis:

```bash
cd ~/Dokumente/pilotprojekt-GrundschutzKI    # falls noch nicht dort
python3.12 -m venv .venv
```

Das erzeugt das Verzeichnis `.venv/`. Es steht in `.gitignore` und wird nie ins Repo eingecheckt – jeder Entwickler baut sein eigenes.

### venv aktivieren

Manuell im Terminal:

```bash
source .venv/bin/activate
```

Du erkennst das aktive venv am `(.venv)`-Prefix im Shell-Prompt:

```
(.venv) geist@laptop:~/Dokumente/pilotprojekt-GrundschutzKI$
```

Deaktivieren mit `deactivate`.

### Abhängigkeiten installieren

Es gibt eine **minimale** [pyproject.toml](../pyproject.toml) (zur Zeit nur `lxml`, `pymupdf`). Die tatsächlichen Skript-Abhängigkeiten sind aktuell nicht zentral deklariert – installiere sie manuell:

```bash
# Basis aus pyproject.toml:
pip install -e .

# Skript-Abhängigkeiten:
pip install \
  litellm \
  ragas \
  instructor \
  qdrant-client \
  pandas \
  python-dotenv \
  nest-asyncio \
  datasets
```

> **Konsolidierungs-Hinweis**: Mittelfristig sollten diese Deps in `pyproject.toml` unter `[project.optional-dependencies]` als `scripts`/`eval`-Gruppe gepflegt werden – ein Aufräumthema für später.

### Verifikation

```bash
which python    # erwartet: …/pilotprojekt-GrundschutzKI/.venv/bin/python
python -c "import litellm, ragas, qdrant_client; print('ok')"
```

Wenn `ok` ausgegeben wird, sind die wichtigsten Skript-Bibliotheken da.

### VS Code: Auto-Aktivierung im Terminal

Damit VS Code automatisch das venv aktiviert, sobald du ein neues Terminal öffnest:

1. **Interpreter setzen** (einmalig pro Workspace):
   - Befehlspalette öffnen: `Strg+Shift+P` (Mac: `Cmd+Shift+P`)
   - Tippe: `Python: Select Interpreter`
   - Wähle: `./.venv/bin/python` (oft als „(.venv)" markiert)

   VS Code legt dabei eine `.vscode/settings.json` im Projekt an mit:
   ```json
   {
     "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python"
   }
   ```

2. **Auto-Activation prüfen** – ist Default an, aber zur Sicherheit:
   - Befehlspalette: `Preferences: Open Workspace Settings (JSON)`
   - Sicherstellen, dass folgender Eintrag vorhanden (oder nicht überschrieben) ist:
     ```json
     {
       "python.terminal.activateEnvironment": true
     }
     ```

3. **Testen**: Schließe alle Terminals, öffne ein neues über `Terminal → New Terminal` (oder `Strg+ö`). Du solltest direkt den `(.venv)`-Prefix sehen.

### Häufige Stolpersteine

| Symptom | Ursache | Lösung |
|---|---|---|
| `python: command not found` nach `source .venv/bin/activate` | venv wurde mit anderer Python-Version erzeugt | `rm -rf .venv && python3.12 -m venv .venv` |
| `ModuleNotFoundError: ragas` trotz Aktivierung | Deps in falschem venv installiert | `which pip` prüfen – muss auf `.venv/bin/pip` zeigen |
| VS Code-Terminal zeigt kein `(.venv)` | Interpreter nicht gesetzt oder Activation deaktiviert | Schritte 1–2 oben durchgehen, dann alle Terminals neu öffnen |
| `ImportError` beim Skript-Lauf trotz aktivem venv | Skript wurde mit `python3 …` statt `python …` gestartet, was am venv vorbei läuft | immer `python script.py` nutzen, nicht `python3 script.py` |

---

## 12. Deine erste Aufgabe: Multiple-Choice-Skript

### Ziel

Schreibe ein Python-Skript `scripts/answer_practitioner_questions.py`, das die 71 Fragen aus `data/data_evaluation/08_IT-GS-Praktiker-Pruefungsfragen.json` von verschiedenen RAG-Konfigurationen beantworten lässt. Pro Konfiguration ein Output-CSV mit:
- der Frage
- den Antwortoptionen (A, B, C, D)
- den vom LLM gewählten Buchstaben
- den korrekten Buchstaben (Ground Truth aus JSON)
- einem `correct: true/false`-Flag

### Warum das eine gute Einstiegsaufgabe ist

- Du nutzt **alle Bausteine** des RAG-Stacks: Retrieval, Embedding, LLM-Aufruf, Prompt-Engineering.
- Du arbeitest mit **existierenden Skripten als Vorlage** – kein Greenfield.
- Das Ergebnis ist **direkt nützlich** – die Evaluations-Suite bekommt ein neues Fragenset.
- Die Multiple-Choice-Struktur macht das **Auswerten trivial** (richtig / falsch, statt RAGAS-Semantik).

### Ausgangslage und Hinweise

**Eingabedaten** ansehen:

```bash
python3 -c "import json; d=json.load(open('data/data_evaluation/08_IT-GS-Praktiker-Pruefungsfragen.json')); print(json.dumps(d['questions'][0], indent=2, ensure_ascii=False))"
```

Eine Frage hat die Felder `id`, `question`, `options` (Liste mit `letter`/`text`), `correct` (Liste der korrekten Buchstaben).

**Vorlagen aus dem Repo**, die du studieren solltest:

| Datei | Was du dort lernen kannst |
|---|---|
| [scripts/run_evaluation.py](../scripts/run_evaluation.py) | wie der RAG-Pipeline-Aufruf strukturiert ist (Retrieval + LLM) |
| [scripts/regenerate_ground_truth_answers.py](../scripts/regenerate_ground_truth_answers.py) | wie eine CSV/JSON eingelesen, pro Zeile ein LLM-Call abgesetzt und das Resultat zurückgeschrieben wird |
| [notebooks/litellm_client.py](../notebooks/litellm_client.py) | wie man LLM-Aufrufe macht (Funktionen `chat_completion`, `get_embeddings`) |
| [apps/chainlit/rag_tool.py](../apps/chainlit/rag_tool.py) | wie aus Qdrant Kontext abgerufen wird |

**Grober Skelett-Aufbau** (bewusst lückenhaft – du sollst es ausbauen):

```python
"""Beantwortet IT-GS-Praktiker-Prüfungsfragen mit dem RAG-Stack.

Aufruf:
    python scripts/answer_practitioner_questions.py \\
        --llm openai/gpt-oss-120b \\
        --embedding-model openai/octen-embedding-8b \\
        --top-k 5 \\
        --output-name gpt-oss_practitioner
"""
import argparse, json, csv
from pathlib import Path
# ... weitere Imports (litellm_client, ...)

def build_prompt(question_text, options, contexts):
    # Aufgabe an das LLM formulieren: aus den Optionen die richtigen Buchstaben
    # zurückgeben, ausschließlich gestützt auf den Kontext.
    ...

def parse_llm_answer(text):
    # Aus der LLM-Antwort die gewählten Buchstaben extrahieren (A, B, …).
    # Tipp: regex auf einzelne Großbuchstaben in der Antwort.
    ...

def main():
    # 1. JSON laden, pro Frage:
    #    a) Frage embedden
    #    b) Qdrant-Treffer holen (top-k)
    #    c) LLM-Prompt bauen
    #    d) LLM aufrufen
    #    e) Antwort parsen → Buchstabenliste
    # 2. Output-CSV schreiben mit allen Spalten + correct-Flag
    ...
```

### Definition of Done

Dein Skript ist „fertig", wenn:

1. ✅ Es läuft fehlerfrei für alle 71 Fragen.
2. ✅ Es erzeugt eine CSV unter `data/results/<output-name>_practitioner.csv` mit den geforderten Spalten.
3. ✅ Der Erfolgsanteil (`correct=true`-Quote) wird am Ende auf der Konsole gedruckt.
4. ✅ Es hat ein `--help`, das Pflichtargumente sauber dokumentiert.
5. ✅ Du hast es mit **mindestens zwei** verschiedenen LLM-Konfigurationen laufen lassen und kannst die Ergebnisse vergleichen.

### Was du **noch nicht** machen sollst

- Keine RAGAS-Metriken – das ist Phase 2.
- Keine UI – ein CLI-Skript reicht.
- Kein Multi-Provider-Switching – nimm den Provider, den deine `.env` zeigt.

### Wann fragen?

- Wenn du nach 30 min nicht weißt, wo du anfangen sollst → kurzes Pair-Programming.
- Wenn dein Skript abstürzt mit `Cannot send a request, as the client has been closed` → siehe [vorherige Issues in `docs/`](.) (Hinweis: Concurrency reduzieren).
- Wenn die LLM-Antworten regelmäßig nicht parsebar sind → wir formulieren den Prompt gemeinsam um.

---

## 13. Workflow: Code ändern → committen → PR erstellen

Wenn du Code geändert hast und ihn ins Repository einbringen willst:

```bash
# 1. Was hast du geändert?
git status
git diff

# 2. Änderungen für den Commit vorbereiten
git add scripts/answer_practitioner_questions.py
# optional: weitere Dateien hinzufügen

# 3. Commit mit aussagekräftiger Nachricht
git commit -m "feat: Skript für IT-GS-Praktiker-Prüfungsfragen

Beantwortet die 71 MC-Fragen aus 08_IT-GS-Praktiker-Pruefungsfragen.json
über den RAG-Stack und vergleicht die Antwort mit dem Ground Truth.
Output: CSV unter data/results/<name>_practitioner.csv."

# 4. Branch zum ersten Mal pushen
git push -u origin feat/<dein-name>/practitioner-mc-skript

# 5. Auf GitHub einen Pull Request öffnen
# → "Compare & pull request"-Knopf nach dem Push erscheint automatisch
```

**Commit-Konvention**: Zeile 1 = kurze Zusammenfassung (max. 70 Zeichen), Präfix `feat:`/`fix:`/`docs:`/`chore:`. Leere Zeile, dann Details (warum, nicht was).

**Pull Request**: Beschreibe **was** du geändert hast, **warum** und **wie man es testet**. Reviewer nimmt die Änderung an oder bittet um Korrektur. Erst nach Approve wird gemergt.

---

## 14. Weiterführende Doku

| Datei | Inhalt |
|---|---|
| [docs/chainlit-app-dokumentation.md](chainlit-app-dokumentation.md) | Architektur-Überblick der Chat-App |
| [docs/notebooks-ingest-beschreibung.md](notebooks-ingest-beschreibung.md) | Wie der Ingest-Prozess funktioniert |
| [docs/software/](software/) | Detail-Doku zu einzelnen Code-Modulen |
| [docs/TASK_01_*.md](TASK_01_Qdrant-erweitern-für-Metadatensuche.md) | Offene Arbeitspakete – größere Aufgaben für später |
| [system.md](../system.md) | Der Produktions-System-Prompt – sehr lesenswert für das Format-Verständnis |

---

## Mini-Glossar

**RAG** *(Retrieval-Augmented Generation)*

Architektur, bei der ein LLM seine Antwort auf zur Laufzeit nachgeschlagenen Dokumenten stützt. Das Wissen liegt also nicht im Modell, sondern in einer externen Datenbank, die pro Anfrage angezapft wird.

---

**Embedding**

Numerische Repräsentation eines Textes als Vektor (Liste von Floats, oft 768–4096 Dimensionen). Texte mit ähnlicher Bedeutung haben ähnliche Vektoren – darüber funktioniert die semantische Suche.

---

**Vector DB**

Datenbank, die Vektoren speichert und nach Ähnlichkeit (z. B. Kosinus-Distanz) suchen kann. In diesem Projekt: **Qdrant**.

---

**Chunk**

Ein Textabschnitt aus einem größeren Dokument, der einzeln gespeichert und durchsuchbar ist. Im Grundschutz-Kompendium entspricht ein Chunk in der Regel einer Anforderung oder einem Baustein-Abschnitt.

---

**Top-K Retrieval**

Suche nach den K (z. B. 5) zur Frage ähnlichsten Chunks. K ist konfigurierbar über die Variable `TOP_K`.

---

**LLM** *(Large Language Model)*

Sprachmodell wie GPT, Llama, Mistral – generiert Text auf Basis eines Prompts. Wir nutzen Modelle wie `gpt-oss-120b`, `meta-llama/Llama-3.3-70B-Instruct` oder `granite-4-h-tiny`.

---

**Prompt**

Der Eingabetext für ein LLM – besteht meist aus System-Anweisung + Nutzerfrage + ggf. Kontext.

---

**System Prompt**

Anweisung an das LLM, wie es sich verhalten soll (Rolle, Stil, Format, Quellen­angaben). In diesem Projekt: [system.md](../system.md).

---

**Tool Call**

Mechanismus, mit dem das LLM strukturiert „Funktionen aufrufen" kann, statt nur Text zu generieren. In diesem Projekt heißt das Tool `rag_retrieve` – damit fordert das LLM Kontext zu einer eigenen Suchanfrage an.

---

**Branch**

Parallele Entwicklungslinie im Git-Repository. Du arbeitest immer in einem eigenen Branch, nie direkt auf `main`.

---

**Pull Request (PR)**

Vorschlag zur Übernahme deines Branches in `main`. Wird von einem anderen Teammitglied geprüft (Review), und erst nach Freigabe gemergt.

---

**Container**

Isolierte Umgebung mit eigener Software-Konfiguration. Wird via Docker gestartet und kann unabhängig vom Host-System gleiche Bedingungen reproduzieren.

---

**`.env`**

Datei mit Umgebungsvariablen (Konfiguration, Secrets). Wird **nie** ins Repository eingecheckt – steht in `.gitignore`.

---

**Concurrency**

Anzahl gleichzeitiger Aufrufe (z. B. an ein LLM). Zu hoch → Server schließt Verbindungen, httpx-Clients werfen Fehler. In den Eval-Skripten auf 2 begrenzt.

---

**Ingest**

Vorgang, bei dem Quelldokumente eingelesen, zerschnitten (Chunking) und in der Vector DB gespeichert werden. Geschieht einmal initial, später nur bei Änderungen am Datenbestand.

---

**venv** *(virtuelles Python-Environment)*

Isolierter Ordner mit einer eigenen Python-Installation und Paketen, damit Projekte sich nicht gegenseitig ihre Abhängigkeiten überschreiben. In diesem Projekt liegt es unter `.venv/` und wird durch `source .venv/bin/activate` aktiviert. VS Code erkennt es automatisch, sobald der Workspace-Interpreter darauf zeigt.

---

## Letzte Tipps

- **Lies fremden Code, bevor du eigenen schreibst.** 80 % der Antworten auf „wie macht man das hier?" stehen schon im Repo.
- **Kleine Commits, früh und oft.** Lieber zehn 5-Zeilen-Commits als einen 500-Zeilen-Brocken.
- **Frag früh.** Eine 5-min-Rückfrage ist günstiger als 3 h in die falsche Richtung.
- **Schreib mit, was du lernst.** Wenn du beim Onboarding über etwas stolperst, das hier nicht erklärt ist – ergänze es. Dein Nachfolger wird es dir danken.

Viel Erfolg!
