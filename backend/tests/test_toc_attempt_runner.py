from pathlib import Path
import asyncio
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.pipeline.toc_attempt_runner import TocAttemptRunner


def _draft(title: str = "Chapter") -> dict:
    return {"type": "toc_draft", "source": "test", "items": [{"title": title, "level": 1}]}


def _mapped(title: str = "Chapter") -> dict:
    return {
        "type": "mapped_toc",
        "source": "unified_s5",
        "items": [{"title": title, "physical_index": 1, "start_index": 1, "end_index": 3}],
        "mapping_report": {"status": "ok"},
    }


def test_attempt_runner_accepts_first_quality_passing_attempt() -> None:
    async def run_case() -> None:
        runner = TocAttemptRunner(
            builders={
                "embedded_toc": lambda _context: _draft("Embedded"),
                "content_outline": lambda _context: _draft("Outline"),
            },
            mapper=lambda draft, _context, _attempt: _mapped(draft["items"][0]["title"]),
            quality_gate=lambda mapped, _context, _attempt: {"status": "ok", "hard_fail_reasons": []},
        )

        result = await runner.run(
            {"attempts": [{"path": "embedded_toc"}, {"path": "content_outline"}]},
            {},
        )

        assert result["status"] == "ok"
        assert result["source"] == "embedded_toc"
        assert result["items"][0]["title"] == "Embedded"
        assert [item["path"] for item in result["attempt_chain"]] == ["embedded_toc"]

    asyncio.run(run_case())


def test_attempt_runner_falls_back_after_mapping_failure() -> None:
    runner = TocAttemptRunner(
        builders={
            "visible_toc_with_pages": lambda _context: _draft("Paged"),
            "visible_toc_no_pages": lambda _context: _draft("Unpaged"),
        },
        mapper=_mapping_failure_then_ok,
        quality_gate=lambda mapped, _context, _attempt: {"status": "ok", "hard_fail_reasons": []},
    )

    result = asyncio.run(runner.run(
        {"attempts": [{"path": "visible_toc_with_pages"}, {"path": "visible_toc_no_pages"}]},
        {},
    ))

    assert result["status"] == "ok"
    assert result["source"] == "visible_toc_no_pages"
    assert result["items"][0]["title"] == "Unpaged"
    assert result["attempt_chain"][0]["mapping_status"] == "failed"
    assert result["attempt_chain"][1]["mapping_status"] == "ok"


def _mapping_failure_then_ok(draft: dict, _context: dict, attempt: dict) -> dict:
    if attempt["path"] == "visible_toc_with_pages":
        return {
            "type": "mapped_toc",
            "source": "unified_s5",
            "items": [],
            "mapping_report": {"status": "failed", "reasons": ["title_match_rate_below_threshold"]},
        }
    return _mapped(draft["items"][0]["title"])


def test_attempt_runner_keeps_best_candidate_when_all_attempts_fail() -> None:
    runner = TocAttemptRunner(
        builders={
            "embedded_toc": lambda _context: _draft("Embedded"),
            "content_outline": lambda _context: _draft("Outline"),
        },
        mapper=lambda draft, _context, _attempt: _mapped(draft["items"][0]["title"]),
        quality_gate=lambda mapped, _context, attempt: {
            "status": "failed",
            "hard_fail_reasons": [f"{attempt['path']}_bad"],
        },
    )

    result = asyncio.run(runner.run(
        {"attempts": [{"path": "embedded_toc"}, {"path": "content_outline"}]},
        {},
    ))

    assert result["status"] == "failed"
    assert result["best_candidate"]["items"][0]["title"] == "Embedded"
    assert len(result["attempt_chain"]) == 2
    assert result["failure_reasons"] == ["embedded_toc_bad", "content_outline_bad"]
