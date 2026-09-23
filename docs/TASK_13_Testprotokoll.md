# TASK_13 — Testprotokoll: Routing nach HyDE-Entkopplung

Manuelles Test-Checkliste zur Überprüfung des Fixes aus dem „Nachtrag: Kopplung von HyDE und Routing" in
[TASK_13_DocRouting_BausteinRouting.md](TASK_13_DocRouting_BausteinRouting.md). Ergebnisse hier eintragen,
relevante Befunde anschließend in die „Kalibrierte Parameter"-Tabelle bzw. den Nachtrag-Abschnitt übernehmen.

## Test-Konfiguration

```
HYDE_ENABLED=true
DOC_ROUTING_ENABLED=true
BAUSTEIN_ROUTING_ENABLED=true    # für diesen Testlauf testweise aktiviert (bisher false)
DOC_ROUTING_THRESHOLD=0.63
DOC_ROUTING_GAP=0.008
BAUSTEIN_ROUTING_THRESHOLD=0.70  # noch nicht kalibriert — dieser Testlauf dient auch der Kalibrierung
```

Datum des Testlaufs: _____________
Getestete Modell-Config (LLM/Embedding): _____________

## Anleitung

Für jede Frage im Chat stellen, danach aus den Server-Logs kopieren:
- `[DEBUG] HyDE generated: ...`
- `[ROUTING] layer1_regex` / `[ROUTING] layer2_scores` / `[ROUTING] layer2_semantic`
- `[ROUTING] layer3_baustein`
- `[ROUTING] blend_standard` / `[ROUTING] blend_baustein`

und in die Tabelle eintragen.

## Testfälle

| # | Frage | Erwarteter Scope | layer2: best/score/gap | layer3: bausteine | Boost angewendet? | Plausibel? | Notiz |
|---|---|---|---|---|---|---|---|
| 1 | „Welche Schritte umfasst die Basis-Absicherung nach BSI-Standard 200-2?" | Layer 1 → `standard_200_2` | — (Regex) | | | | |
| 2 | „Wie führe ich eine Risikoanalyse im Rahmen des Sicherheitskonzepts durch?" | Layer 2 → `standard_200_2` | | | | | |
| 3 | „Wie führe ich eine Risikoanalyse für erhöhten Schutzbedarf durch?" | Layer 2 → `standard_200_3` | | | | | |
| 4 | „Wie plane ich ein Notfallkonzept?" | Layer 2 → `standard_200_4` | | | | | |
| 5 | „Welche Arten von zentralen Speicherlösungen gibt es?" | Layer 3 → `baustein_id=SYS.1.8` | | | | | |
| 6 | „Welche Anforderungen stellt ORP.4 an Berechtigungsmanagement?" | Kein Routing (LLM setzt `baustein_id` selbst) | | | | | |
| 7 | „Was sind die Kernaufgaben eines ISMS?" | Layer 2 → `standard_200_1` | | | | | |
| 8 | „Was muss ich beim Aufbau eines ISMS beachten?" (Regressionsfall aus dem Nachtrag) | Layer 2 → `standard_200_1` **und** Layer 3 → `ISMS.1` | | | | | |
| 9 | „Risikoanalyse" (ohne Kontext — kritischer Fall) | Kein Filter (zu ambig, darf nicht feuern) | | | | | |
| 10 | „Wie muss ich die Softwareentwicklung in meiner Behörde organisieren, wenn wir selbst ein Fachverfahren entwickeln wollen?" (CON.8-vs-APP.7-Fall, siehe Nachtrag 2026-07-17) | Layer 3 → `CON.8` **und/oder** `APP.7` (beide fachlich einschlägig, blended — kein Exklusivfall) | | | | | |

## Auswertung

- Treffer auf erwarteten Scope: __ / 10
- Neue Fehlklassifikationen (Layer 2/3 feuert auf falschen Scope)?
- Fall 8 (ISMS-Aufbau) im Vergleich zum im Nachtrag dokumentierten Vorher-Zustand verbessert? (ISMS.1 jetzt vertreten? 200-1-Boost jetzt inhaltlich passend?)
- Fall 10 (CON.8/APP.7): Findet Layer 3 mindestens einen der beiden Bausteine? Beide? Falls keiner anschlägt, ist das ein starkes Signal, `BAUSTEIN_ROUTING_THRESHOLD` zu senken.
- `BAUSTEIN_ROUTING_THRESHOLD=0.70`: zu hoch/zu niedrig/passend, basierend auf Fall 5, 8 und 10?
- Empfehlung: `BAUSTEIN_ROUTING_ENABLED` dauerhaft auf `true` setzen?
