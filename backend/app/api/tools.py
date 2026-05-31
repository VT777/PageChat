from fastapi import APIRouter, Depends

from app.api.auth import require_auth
from app.prompts import build_tool_catalog
from app.services.tool_executor import AGENT_TOOLS

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
async def list_tools(_current_user: dict = Depends(require_auth)):
    """只读工具目录接口。"""
    tools = []
    for item in AGENT_TOOLS:
        fn = item.get("function", {})
        tools.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
                "readonly": True,
            }
        )

    return {
        "tools": tools,
        "tool_catalog": build_tool_catalog(AGENT_TOOLS),
        "count": len(tools),
    }
