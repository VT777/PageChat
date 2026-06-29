from __future__ import annotations

from typing import Any

from app.services.anysearch_client import AnySearchClient


WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web through AnySearch when the user requested web search "
            "or QA settings allow automatic web search. Returns compact external "
            "source previews only. For user-provided URLs, use intent=read_url "
            "or extract and pass the URLs in urls instead of document doc_id."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Primary search query or user intent.",
                },
                "intent": {
                    "type": "string",
                    "enum": ["answer", "verify", "compare", "latest", "read_url", "extract"],
                    "description": "Optional routing hint. Use read_url/extract when URLs should be read.",
                },
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional URLs to read through AnySearch extract.",
                },
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional multiple search queries for comparison or multi-topic search.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "1-10, defaults to user setting",
                },
                "language": {
                    "type": "string",
                    "description": "Preferred language, e.g. zh-CN or en",
                },
                "zone": {
                    "type": "string",
                    "enum": ["cn", "intl"],
                    "description": "Search region.",
                },
                "content_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["web", "news"]},
                    "description": "AnySearch content type filter.",
                },
                "domain": {
                    "type": "string",
                    "description": "Optional AnySearch vertical/domain routing hint.",
                },
                "tag": {
                    "type": "string",
                    "description": "Optional AnySearch tag or sub-domain routing hint.",
                },
            },
            "required": ["query"],
        },
    },
}


async def execute_web_search_tool(
    *,
    arguments: dict[str, Any],
    settings: dict[str, Any],
    client: AnySearchClient | None = None,
) -> dict[str, Any]:
    if not settings.get("enabled"):
        return {
            "success": False,
            "error_code": "web_search_disabled",
            "message": "Web Search is disabled for this request.",
        }

    query = str(arguments.get("query") or "").strip()
    if not query:
        return {
            "success": False,
            "error_code": "invalid_request",
            "message": "query is required",
        }

    search_client = client or AnySearchClient()
    return await search_client.unified_search(
        query=query,
        api_key=settings.get("api_key"),
        intent=arguments.get("intent"),
        urls=arguments.get("urls") if isinstance(arguments.get("urls"), list) else None,
        queries=arguments.get("queries") if isinstance(arguments.get("queries"), list) else None,
        max_results=int(arguments.get("max_results") or settings.get("max_results") or 5),
        language=str(arguments.get("language") or settings.get("language") or "zh-CN"),
        zone=str(arguments.get("zone") or settings.get("zone") or "cn"),
        content_types=arguments.get("content_types")
        or settings.get("content_types")
        or ["web", "news"],
        domain=str(arguments.get("domain") or "").strip() or None,
        tag=str(arguments.get("tag") or "").strip() or None,
        params=arguments.get("params") if isinstance(arguments.get("params"), dict) else None,
    )
