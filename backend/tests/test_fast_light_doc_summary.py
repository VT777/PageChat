import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pageindex_service import PageIndexService
import app.services.pageindex_service as pageindex_service_module


def test_build_toc_outline_text_limits_titles() -> None:
    structure = [
        {"node_id": "1", "title": "第一章"},
        {"node_id": "1.1", "title": "背景"},
        {"node_id": "2", "title": "第二章"},
    ]

    outline = PageIndexService._build_toc_outline_text(structure, max_titles=2)
    assert "第一章" in outline
    assert "背景" in outline
    assert "第二章" not in outline


def test_generate_fast_light_doc_summary_timeout_returns_empty() -> None:
    service = PageIndexService()

    async def fake_chat_completion(**_kwargs):
        await asyncio.sleep(0.2)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="不应返回"))]
        )

    async def run_case() -> None:
        import app.core.llm as llm_module

        original_call = llm_module.async_chat_completion
        original_timeout = (
            pageindex_service_module.PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS
        )
        try:
            llm_module.async_chat_completion = fake_chat_completion  # type: ignore
            pageindex_service_module.PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS = 0.05
            summary = await service._generate_fast_light_doc_summary(
                [
                    {"node_id": "1", "title": "公司概览"},
                    {"node_id": "2", "title": "管理团队"},
                ],
                Path("demo.pdf"),
            )
            assert summary == ""
        finally:
            llm_module.async_chat_completion = original_call  # type: ignore
            pageindex_service_module.PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS = (
                original_timeout
            )

    asyncio.run(run_case())


def test_generate_fast_light_doc_summary_success() -> None:
    service = PageIndexService()

    async def fake_chat_completion(**_kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='"这是一份公司简介目录摘要"')
                )
            ]
        )

    async def run_case() -> None:
        import app.core.llm as llm_module

        original_call = llm_module.async_chat_completion
        try:
            llm_module.async_chat_completion = fake_chat_completion  # type: ignore
            summary = await service._generate_fast_light_doc_summary(
                [{"node_id": "1", "title": "公司概览"}],
                Path("demo.pdf"),
            )
            assert summary == "这是一份公司简介目录摘要"
        finally:
            llm_module.async_chat_completion = original_call  # type: ignore

    asyncio.run(run_case())


def test_generate_fast_light_doc_summary_empty_toc_returns_empty() -> None:
    service = PageIndexService()

    async def run_case() -> None:
        summary = await service._generate_fast_light_doc_summary([], Path("demo.pdf"))
        assert summary == ""

    asyncio.run(run_case())


def test_generate_fast_light_doc_summary_retries_within_timeout() -> None:
    service = PageIndexService()
    state = {"count": 0}

    async def flaky_chat_completion(**_kwargs):
        state["count"] += 1
        if state["count"] < 3:
            raise RuntimeError("transient")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content='"重试后成功摘要"'))
            ]
        )

    async def run_case() -> None:
        import app.core.llm as llm_module

        original_call = llm_module.async_chat_completion
        original_timeout = (
            pageindex_service_module.PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS
        )
        try:
            llm_module.async_chat_completion = flaky_chat_completion  # type: ignore
            pageindex_service_module.PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS = 3.0
            summary = await service._generate_fast_light_doc_summary(
                [{"node_id": "1", "title": "公司概览"}],
                Path("demo.pdf"),
            )
            assert summary == "重试后成功摘要"
            assert state["count"] >= 3
        finally:
            llm_module.async_chat_completion = original_call  # type: ignore
            pageindex_service_module.PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS = (
                original_timeout
            )

    asyncio.run(run_case())
