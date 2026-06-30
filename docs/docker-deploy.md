# PageChat Docker Deployment

This guide describes the local Docker Compose deployment for PageChat.

## Requirements

- Windows, macOS, or Linux
- Docker Desktop with Docker Compose v2
- At least one model provider API key for real chat usage
- OCR/VLM model configuration if you need scanned or image-based document parsing

## Quick Start on Windows

Double-click:

```text
start-pagechat-docker.bat
```

The script will:

1. Check that Docker is installed and running.
2. Create `.env` from `.env.example` if it does not exist.
3. Run `docker compose up -d --build`.
4. Open PageChat in the browser.

Default URL:

```text
http://localhost:8080
```

## Quick Start from a Terminal

```bash
cp .env.example .env
docker compose up -d --build
```

Open:

```text
http://localhost:8080
```

Backend health check:

```text
http://localhost:8080/health
```

## Configuration

The Docker launcher creates `.env` from `.env.example` when needed. PageChat can start without a model provider key; configure model providers, OCR/VLM, and web search in the application settings after login.

Set `PAGECHAT_HTTP_PORT` in `.env` if port `8080` is already in use.

## Data Persistence

Docker Compose stores runtime data in named volumes:

- `pagechat-data`: SQLite database, uploaded files, indexes, previews, and caches
- `pagechat-logs`: backend logs

Stopping containers does not remove these volumes:

```bash
docker compose down
```

To delete all runtime data, run:

```bash
docker compose down -v
```

## Logs

Windows:

```text
logs-pagechat-docker.bat
```

Terminal:

```bash
docker compose logs -f
```

Backend only:

```bash
docker compose logs -f pagechat-backend
```

## Stop

Windows:

```text
stop-pagechat-docker.bat
```

Terminal:

```bash
docker compose down
```
