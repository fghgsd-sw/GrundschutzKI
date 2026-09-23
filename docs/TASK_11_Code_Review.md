# TASK_11: Qualitätssicherung KI-generierten Codes

## Kontext

Die Anwendung GrundschutzKI wurde überwiegend mit KI-Unterstützung (Claude Sonnet/Opus) entwickelt. KI-generierter Code kann systematische Fehlerklassen aufweisen, die sich von manuell geschriebenem Code unterscheiden: veraltete oder unsichere API-Nutzung, fehlende Input-Validierung an Systemgrenzen, unsichere Defaults sowie — bei naiver Überprüfung mit demselben Modell — Self-Review-Bias. Daher wird ein **dreistufiger, modell-unabhängiger** Ansatz verfolgt.

---

## Methodik: Drei komplementäre Prüfperspektiven

| Stufe | Werkzeug | Methode | Stärke |
|---|---|---|---|
| 1 | Bandit + pip-audit | Statische Analyse | Definierte Muster, CVE-Datenbank |
| 2 | Claude Code `/code-review ultra` | Multi-Agenten AI-Review | Semantische Logikfehler, Architektur |
| 3 | GitHub Copilot (GPT-4o) | Modell-unabhängige AI-Zweitmeinung | Unabhängige Perspektive |

---

## Stufe 1: Statische Sicherheitsanalyse

### 1.1 Installation

```bash
# Im Projekt-Virtualenv
pip install bandit pip-audit

# OpenSSF Scorecard (Go-Binary, einmalig)
# Linux:
curl -sSfL https://raw.githubusercontent.com/ossf/scorecard/main/install.sh | bash
# oder via GitHub CLI:
gh extension install ossf/scorecard
```

### 1.2 Bandit — Python SAST

Bandit (PyCQA) prüft Python-Quellcode auf Sicherheitsprobleme anhand von ~100 Testregeln, gegliedert nach OWASP-Kategorien. Ausgabe enthält Schweregrad (LOW/MEDIUM/HIGH), Konfidenz und CWE-Referenz.

```bash
# Gesamten App-Code prüfen, HTML-Report für Dokumentation
bandit -r apps/chainlit/ notebooks/ scripts/ \
    -f html -o docs/bandit_report.html \
    --severity-level medium \
    --confidence-level medium

# Kurzfassung im Terminal (nur HIGH + MEDIUM)
bandit -r apps/chainlit/ notebooks/ scripts/ \
    -ll -ii \
    --exclude apps/chainlit/.venv,notebooks/.venv
```

Flags:
- `-ll` / `-ii`: nur MEDIUM und höher für Severity / Confidence
- `--exclude`: Virtualenvs ausschließen

### 1.3 pip-audit — Dependency CVE-Check

pip-audit (OpenSSF / Google) gleicht alle installierten Pakete gegen die **OSV-Datenbank** (Open Source Vulnerabilities, openssf.org) und den **PyPI Advisory Database** ab.

```bash
# Abhängigkeiten aus dem Projekt-Virtualenv prüfen
cd apps/chainlit
pip-audit --requirement requirements.txt \
    --format json \
    --output docs/pip_audit_report.json

# Lesbare Terminalausgabe
pip-audit --requirement requirements.txt
```

Bekannte Schwachstellen werden mit CVE-ID, Paketname, betroffener Version und verfügbarem Fix ausgegeben.

### 1.4 OpenSSF Scorecard — Repository-Sicherheitspraktiken

Scorecard bewertet den Entwicklungsprozess selbst (nicht den Code): Branch Protection, Dependency Pinning, Secret Scanning, CI/CD-Signaturen, Vulnerability Disclosure Policy. Gibt Score 0–10 pro Kriterium.

```bash
# Benötigt GITHUB_AUTH_TOKEN
export GITHUB_AUTH_TOKEN=$(gh auth token)

scorecard --repo github.com/aihpi/pilotprojekt-GrundschutzKI \
    --format json \
    --output docs/scorecard_report.json

# Lesbarer Report
scorecard --repo github.com/aihpi/pilotprojekt-GrundschutzKI
```

Relevante Checks für dieses Projekt:
- `Branch-Protection` — Schutz von `main`/`feature`-Branches
- `Token-Permissions` — GITHUB_TOKEN-Berechtigungen in Actions
- `Dependency-Update-Tool` — Dependabot/Renovate konfiguriert?
- `Vulnerabilities` — bekannte CVEs im Repo

---

## Stufe 2: AI Code Review A — Claude Code (Multi-Agenten)

Claude Code's `/code-review ultra` startet mehrere parallele Prüfagenten auf dem Branch-Diff. Jeder Agent ist auf einen Bereich spezialisiert (Security, Architecture, Test Coverage etc.).

**Hinweis Self-Review-Bias:** Claude generierte Teile des Anwendungscodes. Der Review durch dasselbe Modell ist daher mit einer systematischen Einschränkung verbunden: das Modell könnte Muster bevorzugen, die seinem eigenen Generierungsstil entsprechen. Diese Einschränkung ist in der Arbeit transparent zu benennen (analog zum Self-Evaluation-Bias bei RAGAS, vgl. `eval_vorgehen.md` Abschnitt 5.1).

```
# Im Claude Code Terminal, auf dem feature-Branch:
/code-review ultra
```

Alternativ für einen bestehenden GitHub-PR:
```
/code-review ultra <PR-Nummer>
```

Ergebnis als Markdown-Report sichern: `docs/codereview_claude_ultra.md`

---

## Stufe 3: AI Code Review B — GitHub Copilot mit GPT-4o

Unabhängige Zweitmeinung durch ein anderes Modell. Copilot verwendet GPT-4o (OpenAI), was den Self-Review-Bias gegenüber Claude-generiertem Code ausschließt.

**Vorgehen:**

1. Branch auf GitHub pushen:
   ```bash
   git push origin feature/lightweight-upload
   ```

2. Pull Request erstellen (falls nicht vorhanden):
   ```bash
   gh pr create --title "Code Review Target" --body "Für AI Code Review"
   ```

3. In VS Code: Copilot Chat öffnen → Modell auf **GPT-4o** umstellen

4. Review anfordern:
   ```
   @workspace Führe ein Sicherheits-Review durch. 
   Fokus: OWASP Top 10, insbesondere Injection, 
   Broken Access Control, Security Misconfiguration. 
   Bewerte apps/chainlit/app.py, notebooks/litellm_client.py, 
   apps/chainlit/ingest.py
   ```

5. Alternativ: auf GitHub.com im PR-Tab → „Copilot" → „Review" anfordern

Ergebnis dokumentieren: `docs/codereview_copilot_gpt4o.md`

---

## Stufe 4: Synthese — Findings-Matrix

Alle Findings aus den drei Stufen in einer Matrix zusammenführen:

| ID | Kategorie (OWASP) | Schweregrad | Quelle | Status |
|---|---|---|---|---|
| F-01 | A03 Injection | HIGH | Bandit | offen / behoben |
| F-02 | A05 Misconfiguration | MEDIUM | Scorecard | offen / behoben |
| F-03 | A02 Crypto Failures | MEDIUM | Claude Ultra | offen / behoben |
| … | … | … | … | … |

Überschneidungen zwischen Quellen erhöhen die Konfidenz eines Findings. Nur von einer Quelle gemeldete Findings mit niedrigem Schweregrad können als False Positives eingestuft werden.

---

## Wissenschaftliche Einordnung

Die Kombination aus **regelbasierter statischer Analyse** (Bandit, pip-audit) und **semantischer AI-Review** (Claude, Copilot) entspricht dem Prinzip der mehrschichtigen Verteidigung (*Defense in Depth*) auf Ebene der Qualitätssicherung. Die drei Säulen sind methodisch komplementär:

- Statische Analyse findet **definierte Muster** zuverlässig und reproduzierbar (deterministisch)
- AI-Reviews erkennen **semantische Logikfehler** und Architekturprobleme, die regelbasierte Scanner übersehen
- Zwei verschiedene AI-Modelle reduzieren den **Self-Review-Bias** und erhöhen die Überdeckung

Die Nutzung von OpenSSF-Werkzeugen (pip-audit, Scorecard) verankert die Evaluation in einem **anerkannten Open-Source-Sicherheitsframework** (Linux Foundation / OpenSSF, gegründet 2020).

---

## Referenzen

- Bandit: [bandit.readthedocs.io](https://bandit.readthedocs.io)
- pip-audit: [pypi.org/project/pip-audit](https://pypi.org/project/pip-audit) — OpenSSF Alpha-Omega Projekt
- OpenSSF Scorecard: [securityscorecards.dev](https://securityscorecards.dev)
- OSV-Datenbank: [osv.dev](https://osv.dev)
- OWASP Top 10 (2021): [owasp.org/Top10](https://owasp.org/Top10)
- Pearce et al. (2022): *Asleep at the Keyboard? Assessing the Security of GitHub Copilot's Code Contributions* — empirische Studie zu Sicherheitslücken in KI-generiertem Code
- Sandoval et al. (2023): *Lost at C: A User Study on the Security Implications of Large Language Model Code Assistants*
