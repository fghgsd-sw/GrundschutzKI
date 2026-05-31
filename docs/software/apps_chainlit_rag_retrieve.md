Was rag_retrieve ist
rag_retrieve ist kein Python-Funktionsname, sondern der Tool-Name, den das LLM im OpenAI-Function-Calling-Protokoll aufruft. Deklariert wird er als JSON-Schema in app.py:224-240:


TOOLS = [{
    "type": "function",
    "function": {
        "name": "rag_retrieve",
        "description": "Suche relevante Dokumente in der Wissensbasis.",
        "parameters": {... "query", "top_k" ...},
    },
}]

Diese TOOLS-Liste wird in llm.py:39-42 bei jedem POST /chat/completions als Feld tools mitgeschickt. Das LLM entscheidet dann selbst, ob es eine Tool-Antwort produziert – die kommt als tool_calls-Eintrag in der Response zurück (kein freier Text, sondern eine strukturierte Funktionsaufruf-Anweisung mit Argumenten wie {"query": "...", "top_k": 5}).

Wo der Tool-Call ausgeführt wird
Der eigentliche Code, der den Tool-Call bedient, sitzt in der Tool-Loop in app.py:2969-3046:

Prüfung des Namens (app.py:2971)
Argumente parsen, top_k clampen (app.py:2982-2989)
Cache-Lookup über Query+top_k-Signatur (app.py:2991-2993)
Echte Retrieval-Arbeit über retrieve(...) aus rag_tool.py:171 – importiert in app.py:48
Ergebnis als role: tool-Message zurück an die nächste /chat/completions-Runde anhängen (app.py:3033-3039)
Was retrieve() macht
In rag_tool.py:171-241:

Embedding der Anfrage via embed([query]) (geht über denselben LLM-Provider-Stack, siehe llm.py:60)
Vektor-Query an Qdrant (client.query_points auf QDRANT_COLLECTION)
Optionale Filter (source_scope, standard_id)
Trefferaufbereitung in RagResult-Objekte (Text + Score + Metadata)
Sequenz im Überblick

chainlit  ──POST /chat/completions {tools:[rag_retrieve]}──►  LLM
chainlit  ◄── tool_calls:[rag_retrieve(query=..., top_k=5)] ── LLM
chainlit ──►  retrieve()  ──►  embed()  ──►  Qdrant
chainlit ──POST /chat/completions {role:tool, content:context}─►  LLM
chainlit  ◄── finale Textantwort mit Zitaten ── LLM

Anschlusskontext
Aktuell ist rag_retrieve das einzige zugelassene Tool – andere Namen werden in app.py:2971-2980 explizit mit Unsupported tool zurückgewiesen.
Beim ersten Aufruf wird das LLM zudem über die System-Message in app.py:2929 ("Rufe zuerst das Tool rag_retrieve auf, bevor du antwortest.") und tool_choice="required" (siehe Backtrace deines Fehlers) zur Tool-Nutzung gezwungen – das ist auch der Grund, warum dein erster /chat/completions-Call überhaupt scheitert: die Tools-Definition ändert daran nichts, der Fehler stammt aus dem reinen LLM-Schritt davor.
Erweiterungsthema TASK_01_Qdrant-erweitern-für-Metadatensuche.md hängt direkt an dieser Funktion – dort würden weitere Filterparameter ins Tool-Schema aufgenommen.

rag_tool.py
in chainlit wird in der GUI unter "used rag_retrieve" die ursprüngliche Query - aber vereinfacht und die anzahl his angezeigt top_k. bei machen Fragen/Antworten  ist diese Anzeige des Tools mehrfach, iterativ?

Read app.py (lines 2901-2975)
Ja, mehrfach – und zwar gewollt
Die Tool-Schleife in app.py:2959-3048 ist eine agentische Schleife, die solange läuft, bis das LLM keine weiteren tool_calls mehr zurückgibt oder bis MAX_TOOL_CALL_ROUNDS erreicht ist (Default 12, siehe app.py:2952-2956 bzw. .env).

Wann zeigt Chainlit mehrere rag_retrieve-Steps?
Zwei voneinander unabhängige Mechanismen können das auslösen:

1. Mehrere Tool-Calls in einer Runde (app.py:2969)
Das LLM darf in einer Response gleich mehrere tool_calls zurückgeben (z. B. zwei Teilfragen parallel: „Passwort-Anforderungen" + „Webserver-Härtung"). Jeder erzeugt einen eigenen cl.Step(name="rag_retrieve", ...) in app.py:2994/2998.

2. Mehrere Runden (while-Schleife in app.py:2959)
Nachdem alle Tool-Ergebnisse als role: tool-Messages angehängt sind, geht in app.py:3048 ein erneuter /chat/completions-Call raus mit tool_choice="auto". Wenn das LLM jetzt findet, dass die Trefferlage nicht reicht, formuliert es eine neue, verfeinerte Query und ruft rag_retrieve ein weiteres Mal auf. Erst wenn es Tool-Calls weglässt und nur noch Text liefert, endet die Schleife und die Antwort wird ausgespielt.

Was du in der GUI siehst
Die „vereinfachte Query" ist das step.input = {"query": query, "top_k": top_k} aus app.py:2995/2999 – das ist exakt das Argument, das das LLM gewählt hat (nicht zwingend der Originaltext der Nutzerfrage). Bei Folge-Runden weicht die Query daher von der ursprünglichen ab – das ist das sichtbarste Zeichen dafür, dass es eine zweite/dritte Runde ist und nicht nur parallele Calls.

Cache verhindert doppelte echte Retrieval-Arbeit
In app.py:2991-2996 wird über die Signatur query+top_k gecached. Identische Tool-Calls innerhalb derselben Antwort schlagen also nicht zweimal auf Qdrant durch – der zweite Step zeigt im Output "cached": true. Wenn du in der GUI also mehrfach denselben Step mit identischer Query siehst, hat das LLM zwar doppelt aufgerufen, aber nur einmal wirklich gesucht.

Anschlusskontext
Wenn du die agentische Iteration unterbinden willst (z. B. für deterministischere Latenz), kannst du MAX_TOOL_CALL_ROUNDS=1 in der .env setzen – dann fließt nur eine einzige Retrieval-Welle ein, und das LLM muss in der zweiten Runde direkt antworten. Umgekehrt sind 3–4 Runden bei komplexen, mehrteiligen Grundschutz-Fragen oft hilfreich, weil das LLM die Recherche selbst aufteilt.

Tool vs. Funktion
Eine Funktion ist Code – ein lokales Stück Software, das aufgerufen wird, wenn ein anderer Code sie aufruft (z. B. retrieve() in rag_tool.py:171). Sie hat keine Selbstbeschreibung; wer sie nutzen will, muss ihren Signatur-Kontrakt aus dem Quellcode kennen.

Ein Tool im LLM-Sinn ist demgegenüber ein deklaratives Versprechen an das Modell: ein JSON-Schema mit Name, Zweck-Beschreibung in natürlicher Sprache und typisierten Parametern. Es ist gerade kein Code, sondern ein Vertrag über etwas, das der Host (hier Chainlit) für das LLM ausführen wird, wenn das LLM darum bittet. Siehe app.py:224-240 – das Tool-Schema enthält keine Logik, nur Metadaten.

Die Funktion ist also die Implementierung, das Tool die Schnittstellenbeschreibung im Modell-Kontext. Erst die Bindung zwischen beiden – im Dispatcher app.py:2969-3046 – schließt den Kreis.

Wie das LLM die Entscheidung trifft
Beim Aufruf bekommt das LLM drei Informationen:

Tool-Schemata im Request-Feld tools (llm.py:39-42) – inklusive der Beschreibung "Suche relevante Dokumente in der Wissensbasis."
System-Prompt (system.md + ggf. Instruktion „Rufe zuerst das Tool rag_retrieve auf" in app.py:2929)
Konversationsverlauf
Im Forward-Pass schätzt das Modell – analog zur normalen Token-Vorhersage – die Wahrscheinlichkeit, dass die nächste sinnvolle Aktion ein Tool-Aufruf statt eines normalen Texttokens ist. Trainiert wurde das durch Supervised Fine-Tuning auf Beispielen, in denen Tool-Aufrufe an passenden Stellen demonstriert wurden. Die Entscheidung ist also kein expliziter Regelmechanismus, sondern eine gelernte Verteilung über zwei Ausgabeformen:

freier Text (Antwort an den Nutzer), oder
strukturierter Tool-Call (Funktionsname + JSON-Argumente, oft in einem speziellen Antwort-Slot)
Drei Steuerhebel beeinflussen diese Wahl direkt:

Hebel	Wirkung
tool_choice="auto"	Modell wählt frei – die übliche Einstellung in der Folgerunde (app.py:3048)
tool_choice="required"	Modell muss ein Tool aufrufen – wird im Erst-Call genutzt (app.py:2913), um Halluzinationen ohne Retrieval zu unterbinden
tool_choice={"function":{"name":"…"}}	Konkretes Tool wird erzwungen (in diesem Projekt nicht verwendet)
Die formale Auswahl-Begründung – „warum dieses Tool, warum diese Query" – ist nicht direkt einsehbar; manche Modelle (Claude, o-Series) legen sie aber in einem expliziten Reasoning-Schritt offen.

Anschlusskontext
Diese Unterscheidung ist auch der Grund, warum das Tool-Schema sorgfältig formuliert werden muss: Die Beschreibungstexte im JSON-Schema sind funktionaler Bestandteil des Prompts und steuern direkt, wann das Modell zugreift. Eine vage Description wie „mache irgendwas" reduziert die Aufruf-Genauigkeit messbar – ein in der RAG-Literatur unter dem Stichwort tool description grounding diskutiertes Phänomen.