# Felix Handover – Chainlit Citation Stability (2026-03-01)

## Scope & Branch
- **Branch:** `14-feature-chainlit-ui-mit-rag-tool-integration-hinzufügen`
- **Primary objective:** stabilize citation UX in Chainlit (clickable in-text references, panel consistency, PDF preview reliability across follow-up turns and resumed chats).
- **Secondary objective:** remove redundant end-of-answer source list (CITATIONS_PANEL is canonical detail surface).

## Changed Files (tracked)
```text
apps/chainlit/.env.example
apps/chainlit/README.md
apps/chainlit/app.py
apps/chainlit/docker-compose.yml
apps/chainlit/rag_tool.py
system.md
```

### Diff summary
- `6 files changed, 226 insertions(+), 19 deletions(-)`

## What was fixed

### 1) Citation token normalization and mapping robustness (`apps/chainlit/app.py`)
Implemented broader normalization for source mentions so citation tags survive more output variants:
- Handles formats like `Quelle n: ... (S.x)` / `(Seite x)`
- Handles plain `Quelle n` mentions
- Added content-based fallback mapping (`_normalize_source_mentions_by_content(...)`) using title/page similarity when alias mapping is weak
- Extended `_desired_source_count` so plain `Quelle n` is counted and expected

Why this matters:
- Prior logic depended too heavily on one formatting variant and could miss or break links in deeper turns.

### 2) Retrieval call hardening to avoid no-tool drift (`apps/chainlit/app.py`)
Adjusted inference flow to increase probability of deterministic retrieval grounding:
- Initial model call switched from `tool_choice="auto"` to `tool_choice="required"`
- Added retry guard when first response still returns no `tool_calls`

Why this matters:
- Intermittent no-tool responses bypassed retrieval/citation pipeline and produced unstable follow-up behavior.

### 3) Dedup alias consistency (`apps/chainlit/app.py`)
When deduplicating by `(file,page)` source rows:
- Ensured `alias_by_index[idx]` is backfilled even if duplicate row is skipped.

Why this matters:
- Prevents index gaps and alias drift that can produce non-clickable or mismatched source tokens.

### 4) Resume-state persistence for citations (`apps/chainlit/app.py`)
Added explicit citation snapshot persistence on assistant messages and restoration on resume:
- Stored in assistant metadata:
  - `citation_panel_content`
  - `citation_source_rows`
- Added metadata coercion helper (`_coerce_step_metadata(...)`)
- `on_chat_resume` restores citation state into session from step metadata

Why this matters:
- Rendering state is now recoverable for future resumed chats without reconstructing from brittle text-only assumptions.

Important constraint applied:
- **No lazy migration for legacy chats** (as requested). Old threads created before this persistence change may still miss full render context.

### 5) Source file canonicalization from retrieval metadata (`apps/chainlit/rag_tool.py`)
Strengthened metadata → PDF mapping:
- Added `_canonical_pdf_from_text(...)`
- `extract_source_file(...)` now resolves non-`.pdf` identifiers (e.g. `standard_200_2`, `grundschutz`, `kompendium`) to canonical PDF names
- Inspects broader metadata keys (`source.document`, `source.title`, top-level `title`, etc.)

Why this matters:
- Qdrant metadata can be semantically correct but not in direct filename format; this maps those cases to real files for preview/opening.

### 6) Prompt behavior update (`system.md`)
Adjusted system behavior so assistant no longer appends separate trailing source list:
- Use in-text source markers and CITATIONS_PANEL as details surface
- Avoid redundant “Quellenliste/Quellenverzeichnis am Ende”

Why this matters:
- Reduces format noise and avoids conflicts with panel-driven citation UX.

## Also changed (config/docs, optional integration)
- `apps/chainlit/.env.example`: optional Langflow env vars
- `apps/chainlit/docker-compose.yml`: langflow service/dependency/volume scaffolding
- `apps/chainlit/README.md`: startup/config notes for Langflow

Status:
- These are not core to citation bugfixes, but are currently part of working tree modifications.

## Known limitations / caveats
1. **Legacy thread behavior:** chats created before metadata snapshot persistence may still show degraded citation resume behavior (intended tradeoff due to no lazy migration).
2. **Chainlit storage warning persists:** `Data Layer: No storage client configured` still appears; file upload/element persistence semantics may remain limited depending on runtime configuration.
3. **Intermittent model behavior remains possible:** required tool call + retry reduces, but cannot mathematically eliminate all LLM variance.

## Validation performed during session
- Repeated service restarts with Chainlit container running (`gski-chainlit` on port 8000).
- User-reported successful run with ~5 follow-up turns in active chat before old-thread concern was revisited.
- Logs repeatedly showed retrieval hits and follow-up action traces in successful runs.

## Recent command outputs (for reproducibility)

### Repo state
```bash
git branch --show-current
git status --short
```
Output:
```text
14-feature-chainlit-ui-mit-rag-tool-integration-hinzufügen
 M apps/chainlit/.env.example
 M apps/chainlit/README.md
 M apps/chainlit/app.py
 M apps/chainlit/docker-compose.yml
 M apps/chainlit/rag_tool.py
 M system.md
```

> Note: `.vscode/`, `copilot-instructions.md`, and `diagramm.md` were local untracked files and not part of the repo.

### Diff stats
```bash
git diff --stat
```
Output:
```text
 apps/chainlit/.env.example       |   6 ++
 apps/chainlit/README.md          |   9 +++
 apps/chainlit/app.py             | 156 +++++++++++++++++++++++++++++++++++++++---
 apps/chainlit/docker-compose.yml |  16 +++++
 apps/chainlit/rag_tool.py        |  53 +++++++++++---
 system.md                        |   5 +-
 6 files changed, 226 insertions(+), 19 deletions(-)
```

## Recommended commit split (optional but helpful)
1. **Citation stability core**
   - `apps/chainlit/app.py`
   - `apps/chainlit/rag_tool.py`
2. **Prompt behavior alignment**
   - `system.md`
3. **Langflow/config/docs scaffolding**
   - `apps/chainlit/.env.example`
   - `apps/chainlit/docker-compose.yml`
   - `apps/chainlit/README.md`

## Reviewer checklist for Felix
1. **Active chat path**
   - Ask a question with sources, then 5+ follow-ups.
   - Verify: in-text `Quelle n` remains clickable and maps to correct panel/PDF.
2. **Resume path (newly created thread only)**
   - Start new thread after this patch, ask sourced question, resume chat.
   - Verify: citation panel + PDF mappings still work post-resume.
3. **Legacy thread expectation**
   - Test one old chat from before patch.
   - Expect partial degradation is possible (no lazy migration).
4. **Source mapping edge cases**
   - Confirm metadata-only source identifiers (`standard_200_2`, `grundschutz`) resolve to real PDFs.
5. **Output format policy**
   - Verify no separate trailing “Quellenliste”; in-text markers + panel only.

## Rollback notes
- If citation regressions occur, first isolate whether regression is in:
  1) tool-call path (`required` + retry),
  2) alias normalization, or
  3) metadata→PDF canonicalization.
- Minimal rollback strategy:
  - keep `rag_tool.py` canonicalization (low risk, high value),
  - temporarily disable resume metadata restoration if it causes parsing issues,
  - revert `tool_choice="required"` only if model/provider incompatibility is proven.

## Suggested immediate next step
- Execute a short scripted regression matrix (active chat + resumed new chat + one legacy chat) and capture screenshots/log snippets for each pass/fail to anchor final merge decision.
