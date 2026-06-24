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
            "source previews only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
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
    return await search_client.search(
        query=query,
        api_key=settings.get("api_key"),
        max_results=int(arguments.get("max_results") or settings.get("max_results") or 5),
        language=str(arguments.get("language") or settings.get("language") or "zh-CN"),
        zone=str(arguments.get("zone") or settings.get("zone") or "cn"),
        content_types=arguments.get("content_types")
        or settings.get("content_types")
        or ["web", "news"],
    )
