from collections.abc import AsyncIterator, Callable
from typing import Any

from app.agent.nodes import (
    AgentNodeDependencies,
    bind_citations,
    build_evidence_pack,
    decide_retrieval,
    execute_tools,
    finalize,
    generate_answer,
    prepare_scope,
)
from app.agent.state import AgentRunState


AgentNode = Callable[[AgentRunState, AgentNodeDependencies], AsyncIterator[dict[str, Any]]]


class PageChatAgentGraph:
    def __init__(
        self,
        dependencies: AgentNodeDependencies,
        nodes: list[AgentNode] | None = None,
    ):
        self.dependencies = dependencies
        self.nodes = nodes or [
            prepare_scope,
            decide_retrieval,
            execute_tools,
            build_evidence_pack,
            generate_answer,
            bind_citations,
            finalize,
        ]

    async def astream(
        self,
        state: AgentRunState,
        *,
        stream_mode: str = "custom",
        version: str = "v2",
    ) -> AsyncIterator[dict[str, Any]]:
        del version
        if stream_mode != "custom":
            raise ValueError("PageChatAgentGraph only emits custom PageChat events")

        try:
            for node in self.nodes:
                async for event in node(state, self.dependencies):
                    yield {
                        "type": "custom",
                        "ns": (node.__name__,),
                        "data": event,
                    }
        except Exception as exc:
            if self.dependencies.failure_handler is not None:
                await self.dependencies.failure_handler(state, str(exc))
            raise
