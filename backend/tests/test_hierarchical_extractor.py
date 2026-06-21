import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex import hierarchical_extractor


def test_expand_chapter_uses_page_excerpt_input_only(monkeypatch):
    prompts = []

    async def fake_llm_acompletion(model, prompt):
        prompts.append(prompt)
        return json.dumps(
            {
                "sub_chapters": [
                    {"title": "1.1 Opening", "level": 2, "page": 2},
                ]
            }
        )

    monkeypatch.setattr(hierarchical_extractor, "llm_acompletion", fake_llm_acompletion)

    page_texts = [
        "cover",
        "Heading A\nline two\n" + "x" * 260,
        "Heading B\nline two",
    ]

    result = asyncio.run(
        hierarchical_extractor.expand_chapter(
            "Chapter 1",
            2,
            3,
            page_texts,
            model="test-model",
        )
    )

    assert result == [{"title": "1.1 Opening", "level": 2, "page": 2}]
    assert len(prompts) == 1
    prompt = prompts[0]
    assert '"page": 2' in prompt
    assert '"excerpt": "Heading A\\nline two' in prompt
    assert "heading_candidates" not in prompt
    assert "short_summary" not in prompt
    assert "summary" not in prompt.lower()
    assert "x" * 220 not in prompt


def test_expand_chapter_windows_long_ranges_and_merges_duplicates(monkeypatch):
    calls = []

    async def fake_llm_acompletion(model, prompt):
        calls.append(prompt)
        if '"page": 1,' in prompt:
            return json.dumps(
                {
                    "sub_chapters": [
                        {"title": "Intro", "level": 2, "page": 2},
                        {"title": "Overlap", "level": 2, "page": 10},
                    ]
                }
            )
        if '"page": 10,' in prompt:
            return json.dumps(
                {
                    "sub_chapters": [
                        {"title": "Overlap", "level": 2, "page": 10},
                        {"title": "Middle", "level": 2, "page": 18},
                    ]
                }
            )
        return json.dumps(
            {
                "sub_chapters": [
                    {"title": "Tail", "level": 2, "page": 28},
                ]
            }
        )

    monkeypatch.setattr(hierarchical_extractor, "llm_acompletion", fake_llm_acompletion)

    page_texts = [f"Page {index}\nbody" for index in range(1, 31)]

    result = asyncio.run(
        hierarchical_extractor.expand_chapter(
            "Long Chapter",
            1,
            30,
            page_texts,
            model="test-model",
        )
    )

    assert len(calls) == 4
    assert [(item["title"], item["page"]) for item in result] == [
        ("Intro", 2),
        ("Overlap", 10),
        ("Middle", 18),
        ("Tail", 28),
    ]
    assert all("heading_candidates" not in prompt for prompt in calls)
    assert all("short_summary" not in prompt for prompt in calls)
