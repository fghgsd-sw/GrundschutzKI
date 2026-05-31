# Modul: `apps/chainlit/llm.py`

**Pfad:** [apps/chainlit/llm.py](../../apps/chainlit/llm.py)
**Schicht:** Provider-Abstraktion zwischen Anwendung und LLM-/Embedding-Backend
**Sprache:** Python 3.12, async

## Zweck

Bündelt sämtliche Aufrufe an externe LLM- und Embedding-Endpoints in **eine schmale Fassade** über [LiteLLM](https://github.com/BerriAI/litellm). Stellt drei Aufrufformen bereit – nicht-streamendes Chat-Completion mit optionaler Tool-Übergabe, streamendes Chat-Completion und Batch-Embedding – und kapselt darüber das Provider-Routing (LiteLLM-Proxy, IONOS AI Model Hub, lokales Ollama), das per `LLM_PROVIDER`/`EMBED_PROVIDER` in der `.env` umgeschaltet wird. Die übrige Anwendung kennt **keine** Provider-Details, sondern ruft nur `chat`/`stream_chat`/`embed`.

## Position im System

```
[apps/chainlit/app.py]              [apps/chainlit/llm.py]                [apps/chainlit/settings.py]
  on_message() ──chat(messages,    ─▶ payload zusammenbauen   ◀── CHAT_MODEL, LITELLM_BASE_URL,
                tools, tool_choice)   _client_args() einsetzen      LITELLM_API_KEY (auflösbar
                                      │                              je nach LLM_PROVIDER)
                                      ▼
[apps/chainlit/rag_tool.py]         litellm.acompletion(...)     ──HTTPS──▶  LiteLLM-Proxy
  retrieve() ──embed([query])    ─▶  litellm.aembedding(...)     ──HTTPS──▶  / IONOS / Ollama
                                      │
                                      ▼
                                 Response-Objekt mit
                                 .choices[0].message
                                 (.tool_calls)
```

Die Datei ist **zustandslos** – kein Modul-Singleton, keine Caches. Jeder Aufruf liest die zur Importzeit aufgelösten Settings und übergibt sie an LiteLLM.

## Externe Abhängigkeiten

| Quelle | Verwendung |
|--------|-----------|
| `litellm` | `acompletion`, `aembedding` – OpenAI-kompatibler Client mit Provider-Prefix-Routing |
| `settings` | Aufgelöste Provider-Konstanten (`CHAT_MODEL`, `EMBED_MODEL`, `*_BASE_URL`, `*_API_KEY`) |
| LLM-/Embedding-Endpoint (HTTP) | Externer Service je nach Provider-Wahl |

## Aufrufer

| Aufrufer | Importierte Funktionen | Zweck |
|----------|------------------------|-------|
| [apps/chainlit/app.py](../../apps/chainlit/app.py) | `chat`, `stream_chat`, `message_to_dict` | Haupt-Pipeline der Tool-Loop, Streaming-Antworten, Konvertierung von Response-Messages für die Konversations­historie |
| [apps/chainlit/rag_tool.py](../../apps/chainlit/rag_tool.py) | `embed` | Query-Embedding vor der Vektorsuche, identisch zum Ingest-Pfad |

## Funktionen

### Öffentliche API

| Funktion | Signatur (gekürzt) | Zweck |
|----------|-------------------|-------|
| `chat` | `(messages, tools=None, tool_choice="auto", model=None) -> ModelResponse` | Nicht-streamendes Chat-Completion. Tools werden nur aufgenommen, wenn übergeben; `tool_choice` nur bei vorhandenen Tools. Optionaler `model`-Override (genutzt für Mehr-Modell-Strategien, sonst Default `CHAT_MODEL`). |
| `stream_chat` | `(messages, tools=None, tool_choice=None) -> AsyncIterator` | Streamende Variante. Verwendet immer `CHAT_MODEL` (kein Override), setzt `stream=True`. Wird in der Code-Basis genutzt, sobald `STREAMING_ENABLED=true`. |
| `embed` | `(texts: list[str]) -> list[list[float]]` | Batch-Embedding über das per `EMBED_PROVIDER` gewählte Backend. Sortiert die Antwort deterministisch nach `index`, damit die Reihenfolge der Eingaben erhalten bleibt. |
| `message_to_dict` | `(message: Any) -> dict[str, Any]` | Wandelt eine LiteLLM-Response-Message (Objekt mit `role`, `content`, `tool_calls`) in das **dict-Format**, das `messages`-Listen für Folge-Calls erwarten. Bewahrt `tool_calls` mit `id`, `type`, `function.name`, `function.arguments` – essenziell für die Tool-Loop in `app.py`. |

### Interne Helfer (`_private`)

| Funktion | Zweck |
|----------|-------|
| `_client_args` | Liefert das Dictionary `{api_base, api_key}` für den jeweiligen Aufruf. `embed=True` schaltet auf `EMBED_BASE_URL`/`EMBED_API_KEY` um. Leere Werte werden **weggelassen** statt mit `None` gesetzt – wichtig, damit LiteLLM bei nicht-gesetztem Key nicht eine leere Auth-Header sendet. |

## Modul-Zustand

Keiner. Die Datei hält keine Caches, keine Clients, keine Token-Counter. Sämtliche Konfiguration wird beim Import von `settings` aufgelöst und ist während der Prozesslaufzeit fix.

## Konfiguration

Aus [apps/chainlit/settings.py](../../apps/chainlit/settings.py) werden gelesen:

| Setting | Bedeutung |
|---------|-----------|
| `CHAT_MODEL` | LiteLLM-Modellbezeichner für Completions (z. B. `openai/openai/gpt-oss-120b` für IONOS). Aufgelöst je nach `LLM_PROVIDER`. |
| `LITELLM_BASE_URL` | API-Endpunkt für Completions (effektiv: Endpoint des **gewählten** Providers – der Name ist historisch). |
| `LITELLM_API_KEY` | Auth-Token für Completions. |
| `EMBED_MODEL` | LiteLLM-Modellbezeichner für Embeddings (z. B. `openai/BAAI/bge-m3` bei IONOS). |
| `EMBED_BASE_URL` | API-Endpunkt für Embeddings (kann via `EMBED_PROVIDER` separat geroutet werden). |
| `EMBED_API_KEY` | Auth-Token für Embeddings. |

Welche `<PROVIDER>_*`-Variablen aus der `.env` letztlich in diesen Konstanten landen, entscheidet die Auflösung in [settings.py:60-82](../../apps/chainlit/settings.py#L60-L82). Aus Sicht von `llm.py` ist das transparent.

## Verhaltens­hinweise und Edge-Cases

- **`tool_choice` nur bei `tools`**: `chat` hängt `tool_choice` nur an, wenn auch `tools` gesetzt sind ([llm.py:39-42](../../apps/chainlit/llm.py#L39-L42)). Verhindert Provider-Fehler („`tool_choice` requires `tools`"), die manche OpenAI-kompatiblen Backends auslösen.
- **Provider-Prefix-Konvention**: Modellnamen folgen dem LiteLLM-Schema `<litellm-provider>/<model-id>`. Bei Anbietern mit hierarchischen Modell-IDs (IONOS, OpenRouter) ergibt sich daraus **doppelter Prefix**, z. B. `openai/openai/gpt-oss-120b` – der erste `openai/` ist das LiteLLM-Provider-Tag, der zweite Teil ist die echte IONOS-Modell-ID.
- **Streaming-Default abweichend**: `stream_chat` setzt **kein** `tool_choice` als Default (`None`), während `chat` `auto` vorgibt. Beim Streaming bleibt das Tool-Verhalten also dem Modell überlassen, sofern der Caller nichts erzwingt.
- **`embed`-Sortierung**: Die LiteLLM-Antwort enthält `data[].index` zur Zuordnung – die Sortierung in [llm.py:67](../../apps/chainlit/llm.py#L67) ist defensiv, weil manche Backends die Reihenfolge nicht garantieren.
- **`message_to_dict` ist verlustfrei für Tool-Calls**: Andere LiteLLM-Felder (z. B. `function_call`, `tool_call_id`, `name`) werden **nicht** übernommen. Aktuell ausreichend, weil das Projekt nur das moderne `tool_calls`-Format nutzt.
- **Kein Retry / kein Backoff**: Fehler aus LiteLLM (z. B. `BadRequestError: invalid-model-id`) propagieren ungebremst in den Aufrufer. Robustheit ist in [TASK_02_Modell_Fallback.md](../TASK_02_Modell_Fallback.md) als Anschluss­arbeit vorgesehen.

## Bekannte Einschränkungen

- **Kein expliziter Timeout** – LiteLLM-Default greift. Bei langsamen Modellen kann das im Chainlit-Handler zu UI-Hängen führen.
- **Keine Beobachtbarkeit** – weder Tokens, Latenz noch Kosten werden geloggt. Diagnose passiert ausschließlich über LiteLLM-eigene Callbacks (nicht aktiviert) oder Stack-Traces im Container-Log.
- **`stream_chat` ohne `model`-Override** – die Signatur kennt im Gegensatz zu `chat` kein optionales `model`-Argument; eine Mehr-Modell-Strategie würde im Streaming-Pfad anziehende Erweiterung erfordern.
- **Implizite Annahme: gleicher Provider für Chat und Tools** – wenn das eingesetzte Modell Tool-Use nicht unterstützt (z. B. einige offene Modelle hinter `LOCAL_PROVIDER`), schlägt `chat(..., tools=...)` fehl. Es gibt keinen automatischen Fallback auf Tool-freies Prompting.
