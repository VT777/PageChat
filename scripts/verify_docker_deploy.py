from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        raise AssertionError(f"missing {path}")
    return target.read_text(encoding="utf-8")


def require(path: str, *needles: str) -> None:
    content = read(path)
    for needle in needles:
        if needle not in content:
            raise AssertionError(f"{path} does not contain {needle!r}")


def main() -> None:
    require(
        "docker-compose.yml",
        "pagechat-backend",
        "pagechat-frontend",
        "pagechat-data:/app/data",
        "8000",
        "PAGECHAT_HTTP_PORT",
    )
    require(
        "backend/Dockerfile",
        "python:3.11-slim",
        "pip install",
        "uvicorn",
    )
    require(
        "frontend/Dockerfile",
        "node:20-alpine",
        "nginx",
        "npm ci",
        "npm run build",
    )
    require(
        "deploy/nginx/pagechat.conf",
        "proxy_pass http://pagechat-backend:8000",
        "try_files $uri $uri/ /index.html",
        "client_max_body_size",
    )
    require(
        ".env.example",
        "APP_ENV=development",
        "JWT_SECRET=",
        "LLM_API_KEY=",
        "ANYSEARCH_API_KEY=",
    )
    require(
        "start-pagechat-docker.bat",
        "docker compose up -d",
        "http://localhost:%PAGECHAT_HTTP_PORT%",
    )
    require("stop-pagechat-docker.bat", "docker compose down")
    require("logs-pagechat-docker.bat", "docker compose logs -f")
    print("docker deploy files verified")


if __name__ == "__main__":
    main()
