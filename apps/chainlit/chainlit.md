# Grundschutz-KI

Grundschutz-KI beantwortet Fragen zur Informationssicherheit auf Basis des IT-Grundschutz-Kompendiums und der 200-n Standards des BSI. Jede Antwort wird mit den zugrunde liegenden Fundstellen belegt.

---

## Hinweise zum Datenschutz

Sie stimmen mit Ihrer Registrierung der Teilnahme an einer Evaluierung der Anwendung Grundschutz-KI zu. Im Evaluierungszeitraum vom 01. bis 22.07.2026 werden nur solche Daten ausgewertet, die Sie aktiv als Feedback (Thumbs up/down + Kommentar) geben. Die Auswertung erfolgt anonymisiert.

Chatverläufe werden in der Anwendung gespeichert und für die benutzerspezifische Beantwortung verwendet. Sie können Chatverläufe jederzeit selbständig löschen. Nach Abschluss der Evaluierungsphase wird das System zurückgesetzt und alle benutzerbezogenen Daten werden gelöscht.

---

## Hinweise zur Anwendung

### Grundfunktionen

- **Frage stellen** — Text in das Eingabefeld unten schreiben und mit Enter oder dem Senden-Button abschicken.
- **Prompt bearbeiten** — eigene, bereits gesendete Fragen lassen sich nachträglich anpassen (Bearbeiten-Symbol an der eigenen Nachricht); die Antwort wird daraufhin neu generiert.
- **Folgefrage klicken** — am Ende jeder Antwort werden passende Anschlussfragen vorgeschlagen; ein Klick darauf stellt die Frage direkt.
- **Neuer Chat** — über „Neuer Chat" in der linken Seitenleiste wird eine frische Sitzung ohne bisherigen Verlauf gestartet.
- **Chat-Verlauf löschen** — einzelne Unterhaltungen lassen sich über das Kontextmenü in der linken Seitenleiste löschen.

### Feedback

Jede Antwort kann über **👍 Daumen hoch** oder **👎 Daumen runter** bewertet werden. Dabei ist die Eingabe einer **Bemerkung obligatorisch**.

- Die Bemerkung kann sich auf den **konkreten Inhalt der bewerteten Antwort** beziehen
- Es sind aber auch **allgemeine Anmerkungen zur Funktionalität** der Anwendung möglich (z. B. zur Bedienung, zu Personalisierung oder Datei-Upload)
- **Wichtig:** Übergreifende, nicht auf eine einzelne Antwort bezogene Anmerkungen können **nur auf diesem Weg** mitgeteilt werden — es gibt keinen separaten Feedback-Kanal. Kennzeichnen Sie solche Kommentare am Anfang kurz mit **„Gesamtbewertung:"** oder **„Übergreifend:"**, damit sie bei der Auswertung als allgemeines Feedback erkennbar sind.

### Personalisierung ⚙️ 

Grundschutz-KI kann Antworten an Ihre Rolle und bisherigen Interessen anpassen. Dazu werden aus Ihrem Chatverlauf wiederkehrende Themen (Schlüsselwörter) erkannt, z. B. „Webserver-Authentifizierung" oder „Risikoanalyse".

**Funktionsweise:**
- Ergänzt passende Antworten um eine kurze Sektion **„Bezug zu Ihren Interessen"**
- Passt einen Teil der vorgeschlagenen **Anschlussfragen** an Ihre bisherigen Themen an
- Sie beeinflusst **nicht** die Auswahl der abgerufenen Quellen — die Suche nach passenden Fundstellen erfolgt unabhängig von Ihren Schlüsselwörtern, ausschließlich anhand der gestellten Frage
- Sie können die Personalisierung jederzeit über die **Einstellungen (⚙️ Zahnrad-Symbol)** deaktivieren und die gespeicherten Schlüsselwörter einsehen, bearbeiten oder löschen.

---

### Datei-Upload 📎

Diese Funktion stellt einen Workaround für zusätzlichen Kontext dar. Perspektivisch ist hier eine Schnittstelle zu einem ISMS-Tool vorgesehen, aus dem der organisationsspezifische Kontext zur Fragestellung ergänzt wird.

**Funktionsweise:**
- Hochgeladene Dokumente werden vollständig als Text in den Chat-Kontext der aktuellen Sitzung geladen — **nicht** über die Wissensdatenbank durchsucht (kein RAG-Retrieval für eigene Dokumente)
- In den Antworten wird ausschließlich auf die IT-Grundschutz-Dokumente verwiesen, **nicht** auf Stellen in den hochgeladenen Dokumenten
- Der Kontext gilt nur für die laufende Sitzung und wird nicht dauerhaft gespeichert
- Hochgeladene Dateien werden nach Ende der Sitzung gelöscht
- große Dokumente werden gekürzt (Hinweis im Text: „[... Dokument gekürzt ...]"), um das Kontextfenster der Sprachmodelle nicht zu überlasten

**Unterstützte Dateiformate und Grenzwerte:**
- Unterstützte Formate: **PDF** (mit eingebettem Text), **TXT**, **Markdown (.md)**, **CSV**
- Maximal **5 Dateien pro Upload, je bis 2 MB** Dateigröße
- Beschränkung großer Dokumente auf **100.000 Zeichen** 

**Beispiele für Anwendungsfälle mit zusätzlichem Kontext:**
- **Datensicherungskonzept** hochladen, dann fragen: *„Berücksichtigt dieser Entwurf eines Datensicherungskonzeptes alle Anforderungen und Empfehlungen des IT-Grundschutzes?"*
- Liste der **Kern- und Unterstützungsprozesse** hochladen, dann fragen: *„Welche Bausteine muss ich für den sicheren Betrieb meiner Kernprozesse berücksichtigen?"*
- CSV einer **Risikoanalyse** hochladen, dann fragen: *"Welche Maßnahmen sollten priorisiert umgesetzt werden?"*

**Wichtiger Hinweis:**
- Laden Sie keine Dokumente mit vertraulichen Informationen hoch.
- Verwenden Sie stattdessen z.B. das Arbeitsbeispiel RECPLAST GmbH des BSI: 
[Beschreibung der RECPLAST GmbH](https://www.bsi.bund.de/SharedDocs/Downloads/DE/BSI/Grundschutz/Hilfsmittel/Recplast/Beschreibung_Recplast.pdf?__blob=publicationFile&v=1)

**Feedback zur Funktion und zu möglichen weiteren Anwendungsfällen ist willkommen. Vielen Dank für Ihre Teilnahme an der Evaluation!** 🥇🏆 ❤️

---

Bei Fragen oder Problemen mit der Grundschutz-KI wenden Sie sich gerne an [kontakt@fghgsd.de](mailto:kontakt@fghgsd.de)
