from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

# Filter-Parameter (None oder "" zum Überspringen)
BAUSTEIN_ID = "OPS.2.3"      # None oder "" = alle Bausteine
BAUSTEIN_NAME_FILTER = ""  # Teilstring-Filter für baustein_name, z.B. "Sicherheitsmanagement"
STUFE = "basis"            # None oder "" = alle Stufen
TYPE = "anforderung"             # "anforderung", "rolle", "gefaehrdung", "baustein_beschreibung", etc. oder "" = alle
TITLE_FILTER = ""  # None oder "" = kein Titel-Filter
SHOW_TEXT = False#True      # True = Chunk-Text anzeigen, False = nur IDs und Titel

client = QdrantClient(host="localhost", port=6333)

# Konstruiere Filter-Bedingungen (nur wenn Wert gesetzt)
must_conditions = []
if BAUSTEIN_ID:
    must_conditions.append(FieldCondition(
        key="baustein_id",
        match=MatchValue(value=BAUSTEIN_ID),
    ))
if STUFE:
    must_conditions.append(FieldCondition(
        key="stufe",
        match=MatchValue(value=STUFE),
    ))
if TYPE:
    must_conditions.append(FieldCondition(
        key="type",
        match=MatchValue(value=TYPE),
    ))

# Scroll mit optionalen Filtern - durchlaufe ALLE Punkte
scroll_filter = Filter(must=must_conditions) if must_conditions else None

all_points = []
next_offset = None

while True:
    results = client.scroll(
        collection_name="gski_json_pdfs",
        scroll_filter=scroll_filter,
        limit=2000,  # Höheres Limit für weniger Iterations
        offset=next_offset,
        with_payload=True,
    )
    
    points, next_offset = results
    all_points.extend(points)
    
    if next_offset is None:
        break

# Filtere nach Teilstring in "titel" und "baustein_name" (client-seitig)
filtered = all_points

if TITLE_FILTER:
    filtered = [
        p for p in filtered 
        if TITLE_FILTER.lower() in p.payload.get("titel", "").lower()
    ]

if BAUSTEIN_NAME_FILTER:
    filtered = [
        p for p in filtered 
        if BAUSTEIN_NAME_FILTER.lower() in p.payload.get("baustein_name", "").lower()
    ]

# Sortierung nach anforderung_id (mit Default-Wert für fehlende Felder)
results_list = sorted(filtered, key=lambda x: x.payload.get("anforderung_id", ""))

print(f"\n{'='*60}")
print(f"Gefundene Ergebnisse: {len(results_list)} von {len(all_points)} insgesamt")
print(f"{'='*60}\n")

for p in results_list:
    anforderung_id = p.payload.get("anforderung_id", "N/A")
    titel = p.payload.get("titel", "N/A")
    print(f"{anforderung_id} -> {titel}")
    
    if SHOW_TEXT:
        text = p.payload.get("text", "")
        if text:
            print(f"  Text: {text[:500]}...")  # Erste 500 Zeichen
        print()  # Leerzeile zur Lesbarkeit

print(f"\n{'='*60}")
print(f"Total: {len(results_list)} Ergebnisse")
print(f"{'='*60}")
