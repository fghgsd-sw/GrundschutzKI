# TASK 02 – Modell-Fallback (IONOS + lokales SLM via Docker Model Runner)

Gute Nachricht vorweg: Du musst **nicht** den LiteLLM-Client austauschen. LiteLLM ist eine Abstraktion über OpenAI-kompatible APIs – und sowohl IONOS als auch Docker Model Runner *sind* OpenAI-kompatibel. Du musst also nur die **Routing-Variablen** (Base URL, API-Key, Modellname) auf den jeweiligen Anbieter umschalten.

## Wie die drei Anbieter angebunden werden

| Anbieter | Base URL | API-Key | Modellname (Beispiel) | Embeddings? |
|----------|----------|---------|----------------------|-------------|
| **1 – LiteLLM-Proxy** (aktuell) | `http://10.127.129.0:4000/v1` | `sk-…` aus deiner alten `.env` | `openai/gpt-oss-120b` | `openai/octen-embedding-8b` |
| **2 – IONOS AI Model Hub** | `https://openai.inference.de-txl.ionos.com/v1` | Bearer-Token aus IONOS Cloud Console | `openai/meta-llama/Llama-3.3-70B-Instruct` | `openai/BAAI/bge-m3` |
| **3 – Docker Model Runner** (lokal) | `http://localhost:12434/engines/v1` | beliebig (z. B. `not-needed`) | `openai/ai/llama3.2` o. ä. | **Limitierung**, s. u. |

Das Präfix `openai/` ist wichtig – damit weiß LiteLLM, dass es den OpenAI-Client benutzen soll und nicht versucht, einen Provider aus dem Modellnamen zu erraten.

**Wichtiger Hinweis zu Docker Model Runner und Embeddings:** Embedding-Modelle werden unter Docker Model Runner zwar unterstützt (z. B. `ai/mxbai-embed-large`, `ai/nomic-embed-text-v1.5`), aber nur, sofern du das passende Modell vorab gepullt hast. Falls dein lokaler Rechner für Embeddings zu schmal ist, kannst du Chat lokal laufen lassen und Embeddings beim Cloud-Anbieter belassen – darauf zielt die unten skizzierte separate Variable `EMBED_PROVIDER`.

## Vorgeschlagene Umsetzung

### 1. Eine zentrale Auflösungsfunktion in `settings.py`

```python
# apps/chainlit/settings.py – am Anfang ergänzen (nach _getenv-Definition)

LLM_PROVIDER = (_getenv("LLM_PROVIDER", "1") or "1").strip().lower()
EMBED_PROVIDER = (_getenv("EMBED_PROVIDER", LLM_PROVIDER) or LLM_PROVIDER).strip().lower()

# Aliase für bessere Lesbarkeit in der .env
_PROVIDER_ALIASES = {
    "1": "litellm", "litellm": "litellm", "proxy": "litellm",
    "2": "ionos",   "ionos":   "ionos",
    "3": "local",   "local":   "local",  "docker": "local",
}

def _resolve_provider(value: str) -> str:
    key = _PROVIDER_ALIASES.get(value)
    if not key:
        raise ValueError(f"LLM_PROVIDER='{value}' unbekannt. Erlaubt: 1|2|3 oder litellm|ionos|local")
    return key

def _provider_config(kind: str, provider: str) -> tuple[str | None, str | None, str | None]:
    """Liefert (base_url, api_key, model) für 'chat' oder 'embed'."""
    P = provider.upper()                  # LITELLM | IONOS | LOCAL
    K = kind.upper()                      # CHAT | EMBED
    return (
        _getenv(f"{P}_BASE_URL"),
        _getenv(f"{P}_API_KEY"),
        _getenv(f"{P}_{K}_MODEL"),
    )

_chat_provider  = _resolve_provider(LLM_PROVIDER)
_embed_provider = _resolve_provider(EMBED_PROVIDER)

LITELLM_BASE_URL, LITELLM_API_KEY, CHAT_MODEL = _provider_config("chat",  _chat_provider)
EMBED_BASE_URL,   EMBED_API_KEY,   EMBED_MODEL = _provider_config("embed", _embed_provider)

# Defaults beibehalten, falls Variable fehlt
CHAT_MODEL  = CHAT_MODEL  or "openai/gpt-4o-mini"
EMBED_MODEL = EMBED_MODEL or "openai/text-embedding-3-large"
FALLBACK_CHAT_MODEL = _getenv("FALLBACK_CHAT_MODEL")
```

So bleibt das **bisherige Verhalten der Codebase identisch** – `CHAT_MODEL`, `EMBED_MODEL`, `LITELLM_BASE_URL`, `LITELLM_API_KEY` werden weiterhin aus dem Modul exportiert, nur ihre Quelle ändert sich.

### 2. Embedding-Aufruf einen eigenen Endpoint geben

In [apps/chainlit/llm.py](../apps/chainlit/llm.py) ist `embed()` heute hartverdrahtet auf dieselben Credentials wie Chat. Damit Chat-/Embed-Mix funktioniert, einen schmalen Patch:

```python
# apps/chainlit/llm.py

from settings import (
    CHAT_MODEL, EMBED_MODEL,
    LITELLM_API_KEY, LITELLM_BASE_URL,
    EMBED_API_KEY, EMBED_BASE_URL,        # NEU
)

def _client_args(*, embed: bool = False) -> dict[str, Any]:
    base_url = EMBED_BASE_URL if embed else LITELLM_BASE_URL
    api_key  = EMBED_API_KEY  if embed else LITELLM_API_KEY
    args: dict[str, Any] = {}
    if base_url: args["api_base"] = base_url
    if api_key:  args["api_key"]  = api_key
    return args

async def embed(texts: list[str]) -> list[list[float]]:
    response = await litellm.aembedding(
        model=EMBED_MODEL,
        input=texts,
        encoding_format="float",
        **_client_args(embed=True),
    )
    return [item["embedding"] for item in response["data"]]
```

`chat()` und `stream_chat()` rufen wie bisher `_client_args()` ohne Argument auf.

### 3. `.env.example` so strukturieren, dass nur eine Variable umgeschaltet wird

```env
# ───────────────────────────────────────────────────────────
# LLM-Routing (nur EINEN Wert hier setzen)
#   1 oder "litellm"  →  LiteLLM-Proxy (Default)
#   2 oder "ionos"    →  IONOS AI Model Hub
#   3 oder "local"    →  Docker Model Runner lokal
LLM_PROVIDER=1
# Optional: Embeddings separat routen (sonst gleich LLM_PROVIDER)
# EMBED_PROVIDER=2
# ───────────────────────────────────────────────────────────

# === 1 · LiteLLM-Proxy =====================================
LITELLM_BASE_URL=http://10.127.129.0:4000/v1
LITELLM_API_KEY=sk-***
LITELLM_CHAT_MODEL=openai/gpt-oss-120b
LITELLM_EMBED_MODEL=openai/octen-embedding-8b

# === 2 · IONOS AI Model Hub ================================
IONOS_BASE_URL=https://openai.inference.de-txl.ionos.com/v1
IONOS_API_KEY=                                # Bearer-Token aus IONOS Cloud
IONOS_CHAT_MODEL=openai/meta-llama/Llama-3.3-70B-Instruct
IONOS_EMBED_MODEL=openai/BAAI/bge-m3

# === 3 · Docker Model Runner (lokal) =======================
LOCAL_BASE_URL=http://localhost:12434/engines/v1
LOCAL_API_KEY=not-needed
LOCAL_CHAT_MODEL=openai/ai/llama3.2
LOCAL_EMBED_MODEL=openai/ai/mxbai-embed-large
```

Das Muster ist symmetrisch: `<PROVIDER>_BASE_URL` / `<PROVIDER>_API_KEY` / `<PROVIDER>_CHAT_MODEL` / `<PROVIDER>_EMBED_MODEL`. Wer einen weiteren Anbieter hinzufügen will, ergänzt nur einen Alias in `_PROVIDER_ALIASES`.

## Vorbereitung der lokalen Variante (Option 3)

Docker Model Runner ist in **Docker Desktop ≥ 4.40** als Beta enthalten, in Docker Engine über das Plugin `docker-model-plugin`. Aktivierung und Modell-Pull:

```bash
# Einmalig aktivieren (Docker Desktop):
# Settings → Features in development → "Enable Docker Model Runner"

# Modelle pullen
docker model pull ai/llama3.2
docker model pull ai/mxbai-embed-large

# Endpoint freigeben (Default: 12434)
# Settings → Beta → "Enable host-side TCP support"

# Test:
curl http://localhost:12434/engines/v1/models | jq
```

## Vorbereitung IONOS (Option 2)

1. Im **IONOS Cloud Panel** → AI Model Hub → API-Token erzeugen.
2. Endpoint und Modellliste prüfen – die genauen Modellnamen ändern sich; die obigen sind Beispiele aus der IONOS-Doku.
3. Bei IONOS ist der Modellname **ohne** das `openai/`-Präfix angegeben; LiteLLM braucht das Präfix, damit es nicht versucht, einen anderen Provider zu raten. Also `openai/<modellname>`.

## Empfohlene Reihenfolge zum Umsetzen

1. **Backup**: `cp apps/chainlit/.env apps/chainlit/.env.backup`
2. **`settings.py` patchen** und Provider-Auflösung ergänzen
3. **`llm.py` patchen**: Embeddings über `_client_args(embed=True)` laufen lassen
4. **`.env.example` neu fassen** wie oben
5. **`.env` befüllen** – alle drei Blöcke ausfüllen (auch wenn nur einer aktiv ist), `LLM_PROVIDER=2` für IONOS-Test setzen
6. **Smoke-Test** mit einer einzelnen Chat-Frage in der Chainlit-Oberfläche
7. **Notebook-Ebene**: Wenn du die Evaluations-Notebooks parallel bedienen willst, kann [notebooks/litellm_client.py](../notebooks/litellm_client.py) dieselbe Auflösungslogik nutzen (gleicher Code-Block, andere `.env`).

---

## Umsetzung (durchgeführt)

Hier eine kompakte Übersicht der Änderungen:

### Was angepasst wurde

| Datei | Änderung |
|-------|----------|
| [apps/chainlit/settings.py](../apps/chainlit/settings.py) | Neuer Block (Zeilen 24–87): `LLM_PROVIDER` + `EMBED_PROVIDER` mit Aliasen, `_resolve_provider`, `_provider_config`. Legacy-Variablen `LITELLM_BASE_URL`/`LITELLM_API_KEY`/`CHAT_MODEL`/`EMBED_MODEL` werden weiterhin exportiert (Quelle ist nun der gewählte Provider). Neu: `EMBED_BASE_URL`, `EMBED_API_KEY`. |
| [apps/chainlit/llm.py](../apps/chainlit/llm.py) | `_client_args()` akzeptiert `embed=True` und liefert dann die Embed-spezifischen Credentials. `embed()` ruft `_client_args(embed=True)` auf. |
| [apps/chainlit/.env.example](../apps/chainlit/.env.example) | `LLM_PROVIDER`-Schalter + drei symmetrische Provider-Blöcke (1 LiteLLM, 2 IONOS, 3 Local). |

### Verifikationsergebnisse

- **Provider 1** (Default, mit alter `.env`-Struktur): funktioniert dank Legacy-Fallback, ohne dass die `apps/chainlit/.env` angepasst werden muss.
- **Provider 2** (IONOS): URL, Key, Modellnamen werden korrekt aus `IONOS_*` gelesen.
- **Provider 3** (Local): URL, Key, Modellname werden aus `LOCAL_*` gelesen.
- **Mix-Modus** `LLM_PROVIDER=3` + `EMBED_PROVIDER=2`: Chat geht an Docker Model Runner, Embeddings an IONOS – beides parallel.

### Was jetzt zu tun ist

1. In **`apps/chainlit/.env`** den neuen Block für `LLM_PROVIDER` und die drei Provider-Blöcke ergänzen. Vorlage ist [apps/chainlit/.env.example](../apps/chainlit/.env.example). Bestehende `LITELLM_*`-Einträge dürfen unverändert bleiben (Legacy-Fallback greift bei `LLM_PROVIDER=1`).
2. **Provider testen**, z. B. der Reihe nach `LLM_PROVIDER=2`, `LLM_PROVIDER=3` setzen und Chainlit starten.
3. **Bei Provider 3** vorher Modelle pullen:
   ```bash
   docker model pull ai/llama3.2
   docker model pull ai/mxbai-embed-large
   ```
   und in Docker Desktop unter *Settings → Features in development → „Enable Docker Model Runner"* und *„Enable host-side TCP support"* aktivieren.

Falls beim Umstellen auf IONOS ein exakter Modellname benötigt wird: in der IONOS-Cloud-Konsole listet *AI Model Hub → Models* die unterstützten Bezeichnungen – diese dann mit `openai/`-Präfix als `IONOS_CHAT_MODEL` und `IONOS_EMBED_MODEL` eintragen.

---

## Re-Ingest absichern: Snapshot + parallele Collection

Beim Wechsel des Embedding-Modells (z. B. von `octen-embedding-8b`, 4096 Dim. auf `bge-m3`, 1024 Dim.) muss die Qdrant-Collection neu aufgebaut werden. Damit die bestehende Collection im Notfall wiederherstellbar bleibt **und** ein Rollback ohne erneuten Ingest möglich ist, werden zwei Schutzschichten kombiniert.

| Maßnahme | Aufwand | Wozu gut? |
|----------|---------|-----------|
| **Snapshot der alten Collection** | ~5 Sekunden | Atomarer Wiederherstellungspunkt im Disaster-Fall |
| **Neue Collection daneben anlegen** (`grundschutz_bge_m3`) | minimal mehr Storage | A/B-Tests, sofortiger Rollback durch eine einzige `.env`-Variable |

### 1. Snapshot der bestehenden Collection ziehen

```bash
# Snapshot anstoßen
curl -X POST "http://localhost:6333/collections/grundschutz/snapshots" | jq

# Snapshot-Liste anzeigen
curl -s http://localhost:6333/collections/grundschutz/snapshots | jq

# Datei aus dem Volume herauskopieren (außerhalb von Docker sichern)
mkdir -p ./backups/qdrant
SNAP=$(curl -s http://localhost:6333/collections/grundschutz/snapshots | jq -r '.result[-1].name')
curl -s "http://localhost:6333/collections/grundschutz/snapshots/${SNAP}" \
     -o "./backups/qdrant/${SNAP}"
ls -lh ./backups/qdrant/
```

Das Snapshot-File ist typischerweise ~50 MB groß und liegt damit außerhalb des Docker-Volumes als Versicherung bereit.

### 2. Neue Collection parallel aufbauen (Variante A: `.env`-gesteuert)

In [apps/chainlit/.env](../apps/chainlit/.env) den Collection-Namen umschalten:

```env
QDRANT_COLLECTION=grundschutz_bge_m3
```

`docker-compose.yml` reicht den Wert über `env_file: .env` bzw. die `${QDRANT_COLLECTION:-grundschutz}`-Substitution sowohl an den `ingest`- als auch an den `chainlit`-Service durch. Damit:

- Ingest schreibt in `grundschutz_bge_m3`.
- Chainlit liest aus `grundschutz_bge_m3`.
- Die alte Collection `grundschutz` bleibt unangetastet.

Re-Ingest auslösen:

```bash
cd apps/chainlit
INGEST_RECREATE=true docker compose up -d --build
docker compose logs -f ingest
```

### 3. Verifizieren, dass beide Collections existieren

```bash
curl -s http://localhost:6333/collections | jq '.result.collections[].name'
# Erwartet:
# "grundschutz"            ← alte Collection, unverändert
# "grundschutz_bge_m3"     ← neue Collection
```

Vektor-Konfiguration im Detail vergleichen:

```bash
for col in grundschutz grundschutz_bge_m3; do
  echo "=== $col ==="
  curl -s "http://localhost:6333/collections/${col}" \
    | jq '.result | {points: .points_count, dim: .config.params.vectors.size}'
done
# Erwartet:
# grundschutz         → { "points": ~2500, "dim": 4096 }
# grundschutz_bge_m3  → { "points": ~2500, "dim": 1024 }
```

### 4. Rollback in einem Schritt

Falls die Antworten gegen `grundschutz_bge_m3` nicht überzeugen, in [apps/chainlit/.env](../apps/chainlit/.env) zurückschalten:

```env
QDRANT_COLLECTION=grundschutz
```

```bash
docker compose restart chainlit
```

**Wichtig:** Damit Chainlit Queries auf die alte 4096-Dim-Collection schicken kann, muss auch das aktive Embedding-Modell wieder 4096-Dim-Vektoren erzeugen (d. h. der LiteLLM-Pfad muss verfügbar sein). Solange der LiteLLM-Proxy nicht erreichbar ist, dient die alte Collection effektiv nur als „Cold Backup".

### 5. Alte Collection aufräumen (später, wenn neue stabil läuft)

```bash
curl -X DELETE http://localhost:6333/collections/grundschutz
```

Das Snapshot-File aus Schritt 1 bleibt als finale Versicherung erhalten.

### Wiederherstellung im Notfall

Falls der Snapshot zurückgespielt werden muss:

```bash
# 1. Snapshot in den Container zurückkopieren
docker cp ./backups/qdrant/grundschutz-<timestamp>.snapshot \
          gski-qdrant:/qdrant/snapshots/

# 2. Restore-API aufrufen
curl -X PUT \
  -H "Content-Type: application/json" \
  "http://localhost:6333/collections/grundschutz/snapshots/recover" \
  -d '{"location": "file:///qdrant/snapshots/grundschutz-<timestamp>.snapshot"}'
```
