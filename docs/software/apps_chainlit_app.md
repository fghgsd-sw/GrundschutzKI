# Modul: `apps/chainlit/app.py`

**Pfad:** [apps/chainlit/app.py](../../apps/chainlit/app.py)
**Schicht:** Anwendungs- und Orchestrierungs-Layer der Chainlit-Anwendung
**Sprache:** Python 3.12, async

## Zweck

Implementiert den zentralen Einstiegspunkt der Chainlit-Anwendung. Das Modul orchestriert User-Interaktion, Session- und Chat-Verwaltung, Prompt- und Personalisierungslogik, Tool-Calling (inkl. Retrieval) sowie Quellen-/Citation-Rendering und Exportfunktionen. Es verbindet damit UI, LLM-Calls, Retrieval-Layer und Persistenz.

## Position im System

```
[Chainlit UI / FastAPI-Routes]
             │
             ▼
[apps/chainlit/app.py]
  - Auth / User-Kontext
  - Session-Lifecycle
  - Prompt- und Keyword-Management
  - Tool-Calling (rag_retrieve)
  - Citation/Sidebar-Aufbereitung
  - Export / History / Feedback
             │
      ┌──────┼─────────────────────────────────────┐
      │      │                                     │
      ▼      ▼                                     ▼
[llm.py] [rag_tool.py]                    [chat_history.py / native_chat.py]
  chat()   retrieve(), build_context(),     Session-Storage, Profile,
           format_citations()               Feedback, Exporte
             │
             ▼
          [Qdrant]
```

Die Datei wird zur **Laufzeit** pro Chat-Interaktion aufgerufen und hält transienten Sitzungszustand in `cl.user_session`.

## Externe Abhängigkeiten

| Quelle | Verwendung |
|--------|-----------|
| `chainlit` | Lifecycle-Hooks, UI-Elemente, Session-State, Auth-Integration |
| `fastapi` / `fastapi.responses` | API-Routen für Quellen/Citation-Auslieferung |
| `asyncpg` | Direkter Zugriff auf Step-Metadaten (Citation-Panel) |
| `llm.py` | Modellaufrufe (`chat`) und Nachrichten-Serialisierung |
| `rag_tool.py` | Retrieval, Kontextbau und Citation-Grundlagen |
| `chat_history.py` | Chat-Sessions, Nachrichtenpersistenz, Export |
| `native_chat.py` | Nutzerverwaltung, Feedback-Export, DB-Helfer |
| `user_profile.py` | Profil-/Keyword-Pflege und Personalisierung |
| `settings.py` | Laufzeitkonfiguration (DB, Retrieval, Limits, Prompt-Pfade) |

## Aufrufer / Laufzeit-Einstieg

| Einstiegspunkt | Art | Zweck |
|---------------|-----|-------|
| Chainlit Lifecycle (z. B. Chat-Start, Message-Events, Resume) | Event-basiert | Initialisiert Session, verarbeitet User-Nachrichten, baut Antworten inkl. Quellen |
| FastAPI-Route `/sources/pdf/{file_name}` | HTTP GET | Sichere Auslieferung erlaubter PDF-Quellen |
| FastAPI-Route `/sources/citations/{step_id}` | HTTP GET | Auslieferung von Citation-Panel-Inhalten pro Step |

## Kernverantwortungen

| Bereich | Inhalt |
|--------|--------|
| Session-Orchestrierung | Erzeugen/Laden von Chat-Sessions, Speichern von Nachrichten, Titelvergabe |
| Command-Handling | Slash-Commands wie `/history`, `/export`, `/keywords`, `/prompt` |
| Prompt-Management | Laden des System-Prompts, optionaler User-Custom-Prompt, Rebuild im Session-Kontext |
| Personalisierung | Keyword-Verwaltung, Aktivierung/Deaktivierung, Regenerierung aus Verlauf |
| Retrieval-Pipeline | Query-Varianten, Fused Retrieval, Fallback-Strategien, Antwortaufbereitung |
| Citation-Verarbeitung | Alias-Normalisierung, Quellenkatalog pro Session, klickbare Quellen im UI |
| Sicherheit bei Quellen | Whitelist-basierte PDF-Auflösung, Pfadvalidierung, Route-Reihenfolge vor Catch-All |

## Wichtige Datenstrukturen im Modul

| Struktur | Zweck |
|---------|-------|
| `TOOLS` | Deklariert das LLM-Tool `rag_retrieve` (Parameter: `query`, `top_k`) |
| `CITATION_PANEL_CACHE` | In-Memory-Cache für gerenderte Citation-Panel-Inhalte je Step-ID |
| Session-Metadaten `source_catalog` | Stabile Zuordnung von Quellen zu IDs über den Chat-Verlauf |
| Citation-History | Historisierung von Quellenblöcken für Sidebar-Verlauf |

## Tool-Calling: `rag_retrieve`

`rag_retrieve` ist in `TOOLS` als Funktionsschema hinterlegt und dient als kontrollierte Schnittstelle für Retrieval-Aufrufe aus dem Modellfluss. Die konkrete Suche erfolgt über `rag_tool.retrieve(...)` bzw. den Fused-Workflow im Modul.



## Interne Funktionsgruppen (Auszug)

### Quellen- und Citation-Helfer

| Funktion | Zweck |
|----------|-------|
| `_allowed_source_pdf_names` / `_resolve_source_pdf_path` | Erlaubte PDF-Dateien bestimmen und Pfade sicher validieren |
| `_source_pdf_url` / `_citation_panel_url` | URL-Erzeugung für Quellen- und Citation-Endpunkte |
| `_load_citation_panel_content` / `_cache_citation_panel_content` | Laden/Cachen von Panel-Inhalten aus DB-Metadaten |
| `_inject_clickable_refs` u. verwandte Normalizer | Vereinheitlichung von Quellenreferenzen auf stabile Alias-Tokens |

### Source-Catalog-Management

| Funktion | Zweck |
|----------|-------|
| `_sanitize_source_catalog` | Validiert und normalisiert persistierte Catalog-Struktur |
| `_load_session_source_catalog` / `_persist_session_source_catalog` | Laden/Speichern des Catalogs je Chat-Session |
| `_register_source_in_catalog` | Registriert neue Quellen deterministisch und vergibt stabile IDs |
| `_prune_source_catalog` | Entfernt nicht mehr referenzierte Quellen |

### Retrieval-Orchestrierung

| Funktion | Zweck |
|----------|-------|
| `_build_query_variants` | Erzeugt Suchvarianten aus der Userfrage (z. B. Standard-/Keyword-Fokus) |
| `_retrieve_fused` | Führt mehrere Retrieval-Varianten aus und fusioniert Treffer |
| `_fuse_results` / `_merge_results` | Deduping und Ranking über mehrere Result-Sets |
| `_is_weak_retrieval` / `_is_strong_retrieval` | Heuristiken für Qualitätsbewertung der Trefferbasis |

### Chat- und Steuerbefehle

| Funktion | Zweck |
|----------|-------|
| `_handle_control_message` | Verarbeitet Slash-Commands inkl. History/Export/Keywords/Prompt |
| `_format_history_overview` / `_format_session_messages` | Aufbereitung gespeicherter Verläufe für UI-Ausgabe |
| `_build_personalization_prompt` | Erzeugt Prompt-Abschnitt aus aktiven Nutzerinteressen |

## Konfiguration (aus `settings.py`)

Das Modul nutzt u. a. folgende Settings:

| Setting | Wirkung |
|---------|---------|
| `DATABASE_URL`, `CHAT_DB_PATH` | Persistenz für Steps, Sessions und Metadaten |
| `SYSTEM_PROMPT_PATH` | Quelle des initialen System-Prompts |
| `TOP_K`, `MAX_TOP_K` | Retrieval-Grenzen je Anfrage |
| `MAX_SOURCE_LINKS` | Begrenzung der Quellenlinks in der Ausgabe |
| `DATA_RAW_DIR` | Basisverzeichnis für auslieferbare PDF-Quelldateien |
| `STARTER_QUESTIONS` | Initiale Vorschläge in der UI |
| `PROFILE_MIN_MESSAGES`, `PERSONALIZED_FOLLOWUPS_COUNT` | Schwellwerte/Umfang der Personalisierung |

## Verhaltenshinweise und Edge-Cases

- Quellenzugriffe sind auf bekannte PDF-Dateinamen beschränkt; Pfad-Traversal wird explizit abgefangen.
- Citation-Aliasse werden mehrfach normalisiert, um robuste Klickbarkeit im Chainlit-Frontend sicherzustellen.
- Retrieval wird über Query-Varianten und Fusion stabilisiert; Debug-Logs helfen beim Tuning der Ranking-Qualität.
- Bei fehlender oder inkonsistenter Metadatenstruktur greifen Sanitizer/Fallbacks, um Laufzeitfehler in älteren Sessions zu vermeiden.

## Bekannte Einschränkungen

- Das Modul ist sehr umfangreich und bündelt viele Verantwortlichkeiten (Orchestrierung, Formatierung, Retrieval-Heuristiken, Commands). Eine weitere Modularisierung würde Wartbarkeit und Testbarkeit verbessern.
- Einige Heuristiken (Alias-Matching, Query-Varianten) sind domänenspezifisch und regelbasiert; Änderungen an Datenqualität oder Prompting können Nachjustierung erfordern.
- Ein Teil der Diagnostik erfolgt über `print`-basierte Debug-Logs statt zentralisiertem strukturiertem Logging.

## Lösungsvorschlag Refactoring (Skizze)

Ziel: `app.py` als schlanke Wiring-Schicht behalten und fachliche Logik in klar abgegrenzte Module verschieben.

### 1) Zielzuschnitt

- **API/Lifecycle-Schicht**: nur Chainlit-/FastAPI-Einstiegspunkte und Route-Registrierung.
- **Chat-Orchestrierung**: Ablauf `User-Message -> Retrieval/LLM -> Antwort -> Persistenz` in einem `ChatService`.
- **Command-Handler**: Slash-Commands pro Befehl in separaten Handlern (`history`, `export`, `keywords`, `prompt`).
- **Citation-Service**: Alias-Normalisierung, Link-Injection, History-Panel und Cache-Handling.
- **Source-Catalog-Modul**: Laden/Sanitizen/Registrieren/Prunen der Source-IDs mit typisierten Datenobjekten.
- **Retrieval-Orchestrator**: Query-Varianten, Fusion, Heuristiken (`weak/strong`), Fallback-Strategien.
- **Prompt/Personalisierung**: Prompt-Building und Keyword-Logik getrennt vom Chat-Flow.

### 2) Mögliche Ordnerstruktur

```text
apps/chainlit/
  app.py                      # nur Bootstrap + Wiring
  api/
    routes_sources.py         # /sources/pdf, /sources/citations
    lifecycle.py              # on_message, on_chat_start, on_chat_resume
  services/
    chat_service.py
    citation_service.py
    prompt_service.py
    personalization_service.py
    retrieval_orchestrator.py
  commands/
    dispatcher.py
    history.py
    export.py
    keywords.py
    prompt.py
  domain/
    source_catalog.py
    models.py
```

### 3) Inkrementelle Umsetzung in 3 Schritten

1. **Commands extrahieren**: `_handle_control_message` auf Dispatcher + einzelne Handler aufteilen.
2. **Citation + Source-Catalog extrahieren**: reine Hilfsfunktionen in Services/Domain verschieben, `app.py` ruft nur noch APIs auf.
3. **Retrieval-/Prompt-Orchestrierung extrahieren**: `_retrieve_fused`, Variantenbau und Prompt-Personalisierung in eigene Services auslagern.

### 4) Sofortnutzen

- Weniger Seiteneffekte im Hauptmodul.
- Höhere Testbarkeit (Unit-Tests für Services ohne Chainlit-Context).
- Bessere Änderbarkeit bei Retrieval- oder Citation-Logik ohne Eingriff in UI-Lifecycle-Code.
