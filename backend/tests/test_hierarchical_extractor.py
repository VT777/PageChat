import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex import hierarchical_extractor


def test_extract_hierarchical_toc_prefers_page_labeled_full_tree(monkeypatch):
    prompts = []

    async def fake_llm_acompletion(model, prompt):
        prompts.append(prompt)
        assert model == "test-model"
        assert "<physical_index_1>" in prompt
        assert "heading_candidates" not in prompt
        return json.dumps(
            {
                "items": [
                    {
                        "structure": "1",
                        "title": "Opening",
                        "physical_index": "<physical_index_1>",
                    },
                    {
                        "structure": "1.1",
                        "title": "First Topic",
                        "physical_index": "<physical_index_2>",
                    },
                    {
                        "structure": "2",
                        "title": "Analysis",
                        "physical_index": "<physical_index_3>",
                    },
                ]
            }
        )

    monkeypatch.setattr(hierarchical_extractor, "llm_acompletion", fake_llm_acompletion)

    result = asyncio.run(
        hierarchical_extractor.extract_hierarchical_toc(
            ["Opening text", "First Topic\nBody", "Analysis\nBody"],
            model="test-model",
        )
    )

    assert result["source"] == "hierarchical_content_outline"
    assert result["stages"]["content_outline_items"] == 3
    assert len(prompts) == 1
    assert "prominent document/report/paper title" in prompts[0]
    assert [node["title"] for node in result["items"]] == ["Opening", "Analysis"]
    assert result["items"][0]["physical_index"] == 1
    assert result["items"][0]["nodes"][0]["physical_index"] == 2


def test_page_labeled_outline_repairs_llm_with_text_heading_facts(monkeypatch):
    async def fake_llm_acompletion(_model, _prompt):
        return json.dumps(
            {
                "items": [
                    {
                        "structure": "1",
                        "title": "Earth Mover's Distance based Similarity Search at Scale",
                        "physical_index": "<physical_index_1>",
                    },
                    {
                        "structure": "1",
                        "title": "INTRODUCTION",
                        "physical_index": "<physical_index_1>",
                    },
                    {
                        "structure": "2",
                        "title": "PRELIMINARIES",
                        "physical_index": "<physical_index_2>",
                    },
                    {
                        "structure": "2.1",
                        "title": "Computing the EMD",
                        "physical_index": "<physical_index_3>",
                    },
                    {
                        "structure": "5",
                        "title": "EXPERIMENTAL EVALUATION",
                        "physical_index": "<physical_index_9>",
                    },
                    {
                        "structure": "5.2",
                        "title": "Scalability Experiments",
                        "physical_index": "<physical_index_10>",
                    },
                    {
                        "structure": "5.3",
                        "title": "Parameter Tuning in DRO",
                        "physical_index": "<physical_index_10>",
                    },
                ]
            }
        )

    monkeypatch.setattr(hierarchical_extractor, "llm_acompletion", fake_llm_acompletion)

    page_texts = [
        "Earth Mover's Distance based Similarity Search at Scale\n"
        "Authors\nABSTRACT\nText\n1.\nINTRODUCTION\nBody",
        "2.\nPRELIMINARIES\nBody",
        "2.1\nComputing the EMD\nBody\n2.2\nFilter-and-Refinement Framework\nBody",
        "3.\nSCALING UP SSP\nBody",
        "4.\nBOOSTING THE REFINEMENT PHASE\n4.1\nAnalysis of EMD Calculation\nBody",
        "4.3\nSensitivity to Refinement Order\nBody",
        "4.4\nDynamic Refinement Ordering\nBody",
        "4.5\nRunning Upper Bound\nBody\n5.\nEXPERIMENTAL EVALUATION\nBody",
        "5.1\nPerformance Improvement\nBody",
        "5.2\nScalability Experiments\nBody",
        "5.3\nParameter Tuning in DRO\nBody",
        "7.\nCONCLUSION\nBody\n8.\nACKNOWLEDGMENT\nBody\n9.\nREFERENCES\nBody",
    ]

    result = asyncio.run(
        hierarchical_extractor.extract_page_labeled_content_outline(
            page_texts,
            model="test-model",
        )
    )

    roots = result["items"]
    assert [node["title"] for node in roots[:3]] == [
        "Earth Mover's Distance based Similarity Search at Scale",
        "ABSTRACT",
        "INTRODUCTION",
    ]
    assert roots[0]["structure"] == "front-1"
    assert roots[1]["physical_index"] == 1

    experimental = next(node for node in roots if node["title"] == "EXPERIMENTAL EVALUATION")
    assert experimental["physical_index"] == 8
    assert [child["title"] for child in experimental["nodes"]] == [
        "5.1 Performance Improvement",
        "Scalability Experiments",
        "Parameter Tuning in DRO",
    ]
    assert experimental["nodes"][2]["physical_index"] == 11


def test_page_labeled_full_tree_continues_grouped_text(monkeypatch):
    prompts = []

    async def fake_llm_acompletion(_model, prompt):
        prompts.append(prompt)
        if "Previous outline JSON" in prompt:
            return json.dumps(
                {
                    "items": [
                        {
                            "structure": "2",
                            "title": "Second Section",
                            "physical_index": "physical_index_3",
                        }
                    ]
                }
            )
        return json.dumps(
            {
                "items": [
                    {
                        "structure": "1",
                        "title": "First Section",
                        "physical_index": "<physical_index_1>",
                    }
                ]
            }
        )

    monkeypatch.setattr(hierarchical_extractor, "llm_acompletion", fake_llm_acompletion)
    monkeypatch.setattr(hierarchical_extractor, "CONTENT_OUTLINE_GROUP_TOKEN_LIMIT", 20)

    result = asyncio.run(
        hierarchical_extractor.extract_page_labeled_content_outline(
            ["one " * 80, "two " * 80, "three " * 80],
            model="test-model",
        )
    )

    assert len(prompts) >= 2
    assert [item["title"] for item in result["items"]] == ["First Section", "Second Section"]
    assert [item["physical_index"] for item in result["items"]] == [1, 3]


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
    assert "x" * 220 in prompt
    assert "x" * 320 not in prompt


def test_expand_chapter_uses_400_character_page_excerpts(monkeypatch):
    prompts = []

    async def fake_llm_acompletion(model, prompt):
        prompts.append(prompt)
        return json.dumps({"sub_chapters": []})

    monkeypatch.setattr(hierarchical_extractor, "llm_acompletion", fake_llm_acompletion)

    page_texts = [
        "cover",
        "Heading A\n" + "x" * 500,
    ]

    asyncio.run(
        hierarchical_extractor.expand_chapter(
            "Chapter 1",
            2,
            2,
            page_texts,
            model="test-model",
        )
    )

    prompt = prompts[0]
    assert "x" * 350 in prompt
    assert "x" * 420 not in prompt


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
