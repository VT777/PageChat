# PageChat

PageChat is a document-centered AI chat application. It combines document upload, parsing, folder-aware retrieval, citation previews, web search, and an LLM-driven tool loop so users can ask questions grounded in their own files.

This repository contains the PageChat backend and frontend:

- `backend/`: FastAPI application, SQLite persistence, document parsing, model provider settings, OCR routing, and agent tool execution.
- `frontend/`: Vue 3 + TypeScript application for chat, document management, settings, citations, and previews.

PageChat is currently an alpha project. APIs, database schema, and configuration may still change.

## Features

- Document library with folders, upload, parsing status, preview, and selection for chat.
- Chat with persistent conversation history and per-conversation document scope.
- LLM-driven tool loop for browsing documents, reading pages, searching within documents, and web search.
- Inline citations that can open document/page evidence.
- Configurable model providers, including OpenAI-compatible providers and DashScope-compatible providers.
- OCR/VLM routing for image-heavy documents.
- Optional AnySearch-powered web search.

## Requirements

- Python 3.11+
- Node.js 18+
- npm
- At least one configured LLM provider API key

## Quick Start

Clone the repository:

```bash
git clone https://github.com/VT777/PageChat.git
cd PageChat
```

Create backend environment:

```bash
cd backend
python -m venv venv
```

Activate it:

```bash
# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

Install backend dependencies:

```bash
pip install -r requirements.txt
```

Create backend configuration:

```bash
# Windows PowerShell
Copy-Item ..\.env.example .env

# macOS/Linux
cp ../.env.example .env
```

Edit `backend/.env` and set at least:

```env
JWT_SECRET=change-this-to-a-long-random-secret
MODEL_SETTINGS_SECRET=change-this-to-another-long-random-secret
LLM_API_KEY=your-provider-api-key
```

Start the backend:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

In another terminal, start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## Configuration

PageChat loads backend settings from `backend/.env`.

Common settings:

| Variable | Required | Description |
| --- | --- | --- |
| `APP_ENV` | No | Use `development` locally and `production` for deployments. |
| `JWT_SECRET` | Yes in production | Secret used to sign auth tokens. |
| `MODEL_SETTINGS_SECRET` | Yes | Secret used to encrypt stored model provider keys. |
| `LLM_API_KEY` | Yes for environment fallback | API key for the default OpenAI-compatible model route. |
| `LLM_BASE_URL` | No | OpenAI-compatible base URL. Defaults to DashScope compatible endpoint. |
| `LLM_MODEL` | No | Default fallback model name. |
| `ALLOW_ENV_MODEL_FALLBACK` | No | Set `true` only if you want environment model fallback instead of user-configured routes. |
| `OCR_API_KEY` | No | API key for environment OCR fallback. Prefer configuring OCR in the UI. |
| `OCR_BASE_URL` | No | OCR OpenAI-compatible base URL. |
| `OCR_MODEL` | No | OCR model name. |
| `ANYSEARCH_API_KEY` | No | API key for AnySearch web search. |
| `AGENT_RUNTIME_MODE` | No | Defaults to `flat_tool_loop`. |

For product-like use, configure model providers and OCR routes from the Settings dialog after signing in.

## Development Commands

Backend tests:

```bash
cd backend
python -m pytest
```

Frontend tests:

```bash
cd frontend
npm test
```

Frontend build:

```bash
cd frontend
npm run build
```

## Data and Secrets

Runtime data is written under `backend/data/` and is intentionally ignored by Git. Do not commit:

- `.env` files
- SQLite databases
- uploaded documents
- generated previews
- logs
- model provider API keys

## License

PageChat is released under the MIT License. See [LICENSE](LICENSE).
