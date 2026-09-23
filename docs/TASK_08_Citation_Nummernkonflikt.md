# TASK_08: Citation-Nummernkonflikt bei mehreren Tool-Calls

## Problem

Bei mehreren aufeinanderfolgenden `rag_retrieve`-Tool-Calls nummeriert `format_citations()` jede Antwort neu ab "Quelle 1". Der LLM sieht z.B.:

- Tool-Call 1: `Quelle 1: 1.2 Zielsetzung (S.7-8)`
- Tool-Call 4: `Quelle 1: Kapitel 6 Basis-Absicherung (S.95)`

Er generiert die Antwort aus dem richtigen Chunk (Call 4), schreibt aber "Quelle 1" — das Alias-System matcht dann gegen das zuerst etablierte "Quelle 1" aus Call 1 → falsche Fundstelle im Citation-Chip.

## Ursache

Die Nummerierung ist nicht notwendig für die Funktionalität — sie dient nur als kurzes Token. Der eigentliche Alias (Abschnittstitel + Seite) ist eindeutig und bleibt über Tool-Calls hinweg stabil.

## Fix: Nummerierung entfernen, Abschnittstitel als direkten Alias verwenden

### 1. `rag_tool.py` — `format_citations()`

**Vorher:**
```python
lines.append(f"[{idx}] {title}, S. {page_label} → Alias: Quelle {idx}: {title} (S.{page_label})")
```

**Nachher:** Index weglassen, nur Abschnittstitel + Seite ausgeben:
```python
lines.append(f"{title} (S.{page_label})")
```

Das Format, das der LLM im Text verwenden soll, lautet dann:
```
Kapitel 6 Basis-Absicherung (S.95-96)
```
statt:
```
Quelle 3: Kapitel 6 Basis-Absicherung (S.95-96)
```

### 2. `system.md` — Format-Anweisung

**Vorher:**
```
Quellenformat im Fließtext (verbindlich):
- Verwende ausschließlich dieses Format: `Quelle <Nummer>: <Abschnittstitel> (S.<Start>-<Ende>)`
```

**Nachher:**
```
Quellenformat im Fließtext (verbindlich):
- Verwende ausschließlich dieses Format: `<Abschnittstitel> (S.<Start>-<Ende>)`
- Beispiel: `Kapitel 6 Basis-Absicherung (S.95-96)`
- KEINE Nummerierung ("Quelle N:") verwenden
```

### 3. `app.py` — Regex-Pattern anpassen

Mehrere Stellen mit `Quelle\s*\d+\s*:` müssen auf das neue Format umgestellt werden:

```python
# Vorher — matched "Quelle 3: Abschnitt (S.95)"
r"Quelle\s*\d+\s*:[^\n]{1,260}?\((?:S\.?|Seite)\s*[^)\n]+\)"

# Nachher — matched "Abschnitt (S.95)"
r"[^\n]{1,260}?\((?:S\.?|Seite)\s*[^)\n]+\)"
```

Betroffene Stellen in `app.py` (via `grep -n "Quelle\\\\s\*\\\\d"`):
- Canonicalization-Regex (~Zeile 1255)
- Alias-Extraktion aus LLM-Antwort
- `_align_aliases_to_source_ids()`

### 4. `_build_inline_pdf_elements()` — `cl.Pdf(name=...)` 

Der `name` des `cl.Pdf`-Elements muss dem neuen Alias-Format entsprechen:

```python
# Vorher
cl.Pdf(name=f"Quelle {source_id}: {title} (S.{page})", ...)

# Nachher
cl.Pdf(name=f"{title} (S.{page})", ...)
```

## Risiken

- Die Regex-Anpassungen in `app.py` sind komplex — das neue Pattern ist weniger spezifisch und könnte mehr false positives erzeugen
- Der LLM muss den Abschnittstitel exakt so wiedergeben wie in `format_citations()` — ohne Nummer-Anker ist die Trefferquote ggf. geringer
- Alle bestehenden gespeicherten Chatverläufe mit altem Alias-Format werden nicht mehr korrekt dargestellt

## Teststrategie

1. `format_citations()` anpassen + System-Prompt ändern
2. Manuelle Tests: Wird der Alias korrekt im Text übernommen?
3. Wird das `cl.Pdf`-Element korrekt gematcht und öffnet die Sidebar?
4. Regression: Funktioniert die Citation-Pipeline für Standardfragen noch?
