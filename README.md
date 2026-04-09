<p align="center">
  <img src="00_aisc/img/logo_aisc_bmftr.jpg" alt="AISC / BMFTR">
  <br>
  <img src="00_aisc/img/logo_fghgsd_60.png" alt="FGHGsD">
</p>

# IT-Grundschutz-KI

Entwicklung des Chat Bots GSKI, der die Erarbeitung von Sicherheitskonzepten gemäß den BSI-Standards als zuverlässiger Wissensträger unterstützt. Fragen dazu beantwortet er ebenso richtig wie vollständig und durch Quellenangaben sorgt er für Transparenz und Wissenstransfer.

## Features

- **Concise Answers with Source Citations**: Instead of lengthy text responses, the chatbot provides precise jump links into the original IT-Grundschutz documents. Source passages are displayed side-by-side in the browser, ensuring transparency and allowing users to verify answers directly against the original material.
- **Guided Topic Exploration via Follow-up Questions**: The chatbot leverages the structure of the IT-Grundschutz to suggest relevant follow-up questions. Logical and hierarchical relationships between modules (Bausteine) and methods are reflected in the suggestions, helping users navigate complex topics systematically.
- **User-Controlled Role and Topic Focus**: Answers are tailored to the user's role (e.g. IT security officer, department head, IT operations) and to topics from previous conversations. This personalization is fully transparent and configurable via the settings panel.
- **User Feedback**: Thumbs up/down feedback on answers, persisted to PostgreSQL with CSV export for evaluation.
- **Chat History & Export**: Full conversation persistence with OpenAI-format JSON/JSONL export.
- **Docker Compose Deployment**: One-command setup with Chainlit, PostgreSQL, Qdrant, and auto-ingestion.

## Setup and Installation

### Prerequisites

- Docker and Docker Compose
- A running LLM endpoint compatible with the OpenAI API (e.g. [LiteLLM](https://github.com/BerriAI/litellm), [Ollama](https://ollama.com/))
- An embedding model accessible via the same endpoint

The LLM endpoint is configured via `LITELLM_BASE_URL` in the `.env` file. This works with any OpenAI-compatible API, including Ollama (e.g. `LITELLM_BASE_URL=http://localhost:11434/v1`).

### Authentication

Two authentication methods are supported:

- **GitHub OAuth** (recommended): Configure `OAUTH_GITHUB_CLIENT_ID` and `OAUTH_GITHUB_CLIENT_SECRET` in `.env` for single sign-on via GitHub.
- **Password login**: Set `CHAINLIT_AUTH_USERNAME` and `CHAINLIT_AUTH_PASSWORD` in `.env` for local admin access. Additional users can self-register via the built-in registration form.

### Quick Start

1. Clone the repository:
   ```bash
   git clone https://github.com/aihpi/pilotprojekt-GrundschutzKI.git
   cd pilotprojekt-GrundschutzKI
   ```

2. Configure and start the Chainlit app:
   ```bash
   cd apps/chainlit
   cp .env.example .env
   # Edit .env: set LITELLM_BASE_URL, LITELLM_API_KEY, CHAT_MODEL, EMBED_MODEL
   docker compose up -d --build
   ```

3. Access the application:
   - Chat UI: `http://localhost:8000`

For detailed configuration options, ingestion workflows, environment variables, and troubleshooting, see the [Chainlit app README](apps/chainlit/README.md).

## User Guide

### Getting Started

1. Open the chat UI at `http://localhost:8000` and log in with the credentials configured in `.env` (`CHAINLIT_AUTH_USERNAME` / `CHAINLIT_AUTH_PASSWORD`).
2. Select a role profile in the settings sidebar to receive answers tailored to your perspective (e.g. IT security officer, IT operations, management).
3. Ask questions about IT-Grundschutz — the system retrieves relevant passages and generates answers with source citations.

### Key Interactions

- **Source citations**: Click on source references (e.g. "Quelle 1: ...") to open the corresponding PDF at the cited page.
- **Follow-up questions**: Suggested follow-up questions appear as clickable buttons below each answer.
- **Feedback**: Use the thumbs up/down buttons to rate answer quality. Optionally add a comment.
- **Chat commands**: Type `/help` in the chat for available slash commands (history, export, keywords, prompt customization).

### Administration

- **Feedback export**: Administrators can download all user feedback as CSV at `/export/feedback` (requires admin login).
- **Chat export**: Use `/export all` in the chat or the sidebar export button for OpenAI-format JSONL export.

For the full user and administration guide, see the [Chainlit app README](apps/chainlit/README.md).


## Limitations

- **Prototype / Vibe-Coded**: This application was developed using AI-assisted "vibe coding" and **must be hardened and security-reviewed before any production deployment**.
- **Local models**: Local LLMs can be used via [Ollama](https://ollama.com/) by pointing `LITELLM_BASE_URL` in the `.env` file to the Ollama endpoint (e.g. `http://localhost:11434/v1`). Adjust `CHAT_MODEL` and `EMBED_MODEL` accordingly.


## References

- [AI Service Centre Berlin Brandenburg (KI-Servicezentrum)](https://hpi.de/ki-servicezentrum/)
- [fghgsd.de](https://fghgsd.de)

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).

---

## Acknowledgements
<img src="00_aisc/img/logo_bmftr_de.png" alt="drawing" style="width:170px;"/>

The [AI Service Centre Berlin Brandenburg](http://hpi.de/kisz) is funded by the [Federal Ministry of Research, Technology and Space](https://www.bmbf.de/) under the funding code 01IS22092.
