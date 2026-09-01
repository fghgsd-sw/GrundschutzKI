# Grundschutz-KI

Grundschutz-KI beantwortet Ihre Fragen zur Informationssicherheit auf Basis des IT-Grundschutz-Kompendiums, der 200-n Standards des BSI und des von Ihnen ggf. zusätzlich mitgegebenen Kontexts. Jede Antwort wird mit den zugrunde liegenden Fundstellen belegt.

Grundschutz-KI erstellt zudem Anschlussfragen, die Ihnen  zusätzliche Perspektiven auf Ihr Thema liefern sollen.

*Bewerten Sie, wie gut das Ganze für Sie funktioniert.*


---

## Hinweise zur Evaluation und zum Datenschutz

Grundschutz-KI wird im Rahmen einer Masterarbeit gemeinsam mit Fachanwenderinnen und Fachanwendern evaluiert. Ziel ist es, herauszufinden, wie gut ein auf Retrieval-Augmented Generation basierendes System Fragen zum IT-Grundschutz beantworten kann — und wo es noch an seine Grenzen stößt. Mit Ihrer Registrierung stimmen Sie der Teilnahme an dieser Evaluierung zu.

**Zeitraum:** bis zum 25. September 2026. Ausgewertet werden ausschließlich die Daten, die Sie aktiv als Feedback geben — über 👍/👎 mit Kommentar sowie das Feedback-Formular —, und zwar anonymisiert.

**Was wir uns von Ihnen wünschen:** Nutzen Sie Grundschutz-KI für Fragen aus Ihrem Arbeitsalltag und bewerten Sie Antworten aktiv. Am Ende Ihrer Teilnahme freuen wir uns zusätzlich über das kurze Feedback-Formular (Menüpunkt „Feedback").

Chatverläufe werden gespeichert und für die benutzerspezifische Beantwortung verwendet; Sie können sie jederzeit selbst löschen. **Hochgeladene Dateien** werden nicht dauerhaft gespeichert, sondern nach Sitzungsende automatisch gelöscht. Bitte verwenden Sie dennoch keine schutzbedürftigen Echtdaten für den Test der Anwendung. Nach Abschluss der Evaluierung wird das System zurückgesetzt und alle personenbezogenen Daten werden gelöscht.

**Bei Fragen zur Evaluation** wenden Sie sich gerne an [kontakt@fghgsd.de](mailto:kontakt@fghgsd.de).

---

## Hinweise zur Anwendung

### Bekannte Einschränkungen

Grundschutz-KI befindet sich in der Evaluierungsphase. Folgende Punkte sind uns bekannt und bewusst Gegenstand der Evaluierung — Ihr Feedback dazu ist besonders wertvoll:

- **Quellenangaben passen nicht immer zur Aussage:** Das ist kein seltenes Randphänomen, sondern ein bekannter, häufigerer Schwachpunkt, den wir aktiv untersuchen. Typische Ursache: Das Modell zitiert dieselbe Fundstelle wiederholt für mehrere, auch inhaltlich unterschiedliche Aussagen weiter — als eine Art „Sammelquelle" —, obwohl sie nur einen Teil davon tatsächlich belegt. Das kommt insbesondere bei Antworten mit mehreren Aufzählungspunkten vor. Ein Blick auf die verlinkte PDF-Seite zeigt, ob die Fundstelle wirklich zur jeweiligen Einzelaussage passt.
- **Sehr breite Aufzählungsfragen** (z. B. „Welche Anforderungen stellt Baustein X insgesamt?"): Hier tritt das Sammelquellen-Problem von oben besonders häufig auf, da viele Einzelanforderungen gleichzeitig abgedeckt werden sollen. Konkretere Teilfragen (z. B. zu einem einzelnen Aspekt) liefern erfahrungsgemäß zuverlässigere Ergebnisse als eine vollständige Auflistung in einer Antwort.

**Wir sind hier konkret auf Ihre Mitarbeit angewiesen:** Diese Fehler automatisiert zu erkennen ist nur begrenzt möglich — am wertvollsten ist Ihre Rückmeldung, wenn Sie eine unpassende Fundstelle bemerken. Melden Sie das bitte über 👎 mit kurzem Kommentar, möglichst mit Angabe, **welcher konkrete Aufzählungspunkt bzw. welche Aussage** betroffen ist. Nur so lassen sich diese Fälle den jeweiligen Fragen zuordnen und gezielt nachvollziehen.

**Vielen Dank an dieser Stelle schon einmal für Ihre Mitwirkung.🥇**

---

### Grundfunktionen

- **Frage stellen** — Text in das Eingabefeld unten schreiben und mit Enter oder dem Senden-Button abschicken.
- **Prompt bearbeiten** — eigene, bereits gesendete Fragen lassen sich nachträglich anpassen (Bearbeiten-Symbol an der eigenen Nachricht); die Antwort wird daraufhin neu generiert.
- **Folgefrage klicken** — am Ende jeder Antwort werden passende Anschlussfragen vorgeschlagen; ein Klick darauf stellt die Frage direkt.
- **Anschlussfragen neu generieren** — über die Schaltfläche „Anschlussfragen neu vorschlagen" unter einer Antwort lassen sich alternative Folgefragen erzeugen, falls die vorgeschlagenen nicht passen.
- **Neuer Chat** — über „Neuer Chat" in der linken Seitenleiste wird eine frische Sitzung ohne bisherigen Verlauf gestartet.
- **Chat-Verlauf löschen** — einzelne Unterhaltungen lassen sich über das Kontextmenü in der linken Seitenleiste löschen.

### Feedback

Jede Antwort kann über **👍 Daumen hoch** oder **👎 Daumen runter** bewertet werden. Dabei ist die Eingabe einer **Bemerkung obligatorisch**.

- Die Bemerkung sollte sich auf den **konkreten Inhalt der bewerteten Antwort** beziehen
- Für **allgemeine Anmerkungen zur Funktionalität** der Anwendung (z. B. zur Bedienung, zu Personalisierung oder Datei-Upload) oder eine **rollenbezogene Gesamteinschätzung** nutzen Sie bitte das separate **Feedback-Formular** — erreichbar über den Menüpunkt **„Feedback"** neben „Readme" am oberen Bildschirmrand.

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
- Das hochgeladene Dokument bleibt für die **gesamte Sitzung** im Modell-Kontext — auch wenn spätere Fragen keinen Bezug dazu haben. Für allgemeine IT-Grundschutz-Fragen ohne Dokumentbezug empfiehlt sich ein **neuer Chat**.
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
