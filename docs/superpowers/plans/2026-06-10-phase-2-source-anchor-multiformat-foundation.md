# Phase 2 Source Anchor And Multi-Format Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize current non-PDF indexing and make source anchors consistent and resolvable across TXT, Markdown, CSV/TSV, XLSX, DOCX, and PPTX.

**Architecture:** Keep the mature PDF PageIndex path unchanged. Add canonical non-PDF adapter structures, fix current adapter defects, normalize `source_anchor.unit_type`, and introduce internal source-anchor content resolution while preserving existing tool and preview response fields.

**Tech Stack:** FastAPI backend, existing `PageIndexService`, `multi_format_adapter.py`, `ContentExtractionService`, `TableAnalysisService`, `DocumentSearchService`, `ToolExecutor`, pytest, optional parser libraries already present or added deliberately.

---

## Why This Phase Comes Next

Phase 1 made retrieval safe and traceable. Phase 2 makes retrieval evidence precise across file formats.

Current facts:

- `backend/app/services/multi_format_adapter.py` still contains a Markdown fallback block that references `paragraphs`, which is defined only in the DOCX path.
- `backend/tests/test_multi_format_adapter.py` currently covers only TXT and CSV basics.
- `backend/app/models/retrieval.py` already contains `build_source_display_label()`.
- Search and retrieval result paths already preserve `source_anchor`.
- Preview components already accept `source_anchor` in several places.

This phase must not redesign the frontend, change PDF indexing behavior, or add legacy Office conversion.

This phase is not the full multi-format adapter rewrite. It deliberately stabilizes the current paths first. The full parser migration to dedicated TXT/Markdown, table, DOCX, PPTX, and legacy conversion adapters is tracked in:

```text
docs/superpowers/plans/2026-06-10-phase-7-multiformat-adapter-migration.md
```

## Minimum Delivery Boundary

Phase 2 should produce a stable evidence contract, not a full parser platform.

Required minimum:

- Fix the current Markdown adapter defect.
- Ensure existing non-PDF index nodes carry `source_anchor.unit_type`.
- Add canonical adapter dataclasses and conversion helpers that future adapters can reuse.
- Add source-anchor resolution for current line and row anchors.
- For DOCX, XLSX, and PPTX anchors, either resolve them with existing code or return tested explicit `unsupported` responses that Phase 7 must replace.
- Preserve current PDF indexing behavior and current frontend-compatible response fields.

Do not expand Phase 2 into:

- Rewriting all non-PDF parsers.
- Adding legacy Office upload support.
- Redesigning document management UI.
- Changing retrieval planner behavior beyond preserving and resolving source anchors.

## Compatibility And Ownership Rules

- `start_index` and `end_index` remain compatibility fields; new code should prefer `source_anchor` when choosing or displaying evidence.
- `display_label` should be generated from `source_anchor` when possible and should not remove older citation fields.
- Backend response shape changes must be additive unless this plan is explicitly updated.
- Frontend type updates are required only when Phase 2 changes fields consumed by current preview or chat UI.
- Legacy records with `NULL user_id` must not become visible through new anchor, search, or tool behavior. If a test fixture needs legacy data, it must document the expected isolation behavior.
- Source-anchor resolution must bound reads to the requested range and avoid loading unbounded large tables or documents into a tool response.

## Files And Responsibilities

- Modify: `backend/app/services/multi_format_adapter.py`
  - Fix Markdown fallback.
  - Add missing `unit_type` fields to existing anchors.
  - Keep `generate_multi_format_index(file_path)` stable.
- Create: `backend/app/services/format_adapters/__init__.py`
  - Export canonical adapter dataclasses and conversion helpers.
- Create: `backend/app/services/format_adapters/base.py`
  - Define `SourceAnchor`, `ContentBlock`, `IndexNode`, `DocumentContent`, `FormatCapabilities`.
  - Convert canonical content into current index JSON.
- Create: `backend/app/services/source_anchor_resolver.py`
  - Resolve source content by `source_anchor`.
  - Return content, normalized anchor, and display label.
- Modify: `backend/app/services/content_extraction_service.py`
  - Prefer source-anchor-compatible blocks where practical.
  - Preserve current preview API compatibility.
- Modify: `backend/app/services/table_analysis_service.py`
  - Prepare for shared table parsing without changing aggregation behavior yet.
- Modify: `backend/app/services/tool_executor.py`
  - Add internal support for resolving non-PDF anchors behind existing tool flows.
- Modify: `backend/app/services/search_service.py`
  - Preserve and normalize `source_anchor` in result metadata.
- Modify: `backend/tests/test_multi_format_adapter.py`
  - Add Markdown and anchor normalization regression coverage.
- Create: `backend/tests/test_format_adapter_base.py`
  - Test canonical structures and index conversion.
- Create: `backend/tests/test_source_anchor_resolution.py`
  - Test source-anchor resolution for current supported formats.
- Create: `backend/tests/test_source_anchor_resolution_office.py`
  - Test DOCX paragraph, XLSX sheet row range, and PPTX slide anchor resolution or explicit unsupported status until Phase 7 migrates parser internals.
- Create: `backend/tests/test_non_pdf_source_anchors.py`
  - Test search/tool output for non-PDF anchors.

## Source Anchor Contract

All non-PDF adapter anchors should include `format` and `unit_type`.

Examples:

```json
{"format": "txt", "unit_type": "line", "start_line": 1, "end_line": 40}
{"format": "markdown", "unit_type": "line", "start_line": 20, "end_line": 42}
{"format": "csv", "unit_type": "row_range", "start_row": 1, "end_row": 100}
{"format": "xlsx", "unit_type": "row_range", "sheet": "Sheet1", "start_row": 2, "end_row": 80}
{"format": "docx", "unit_type": "paragraph", "start_paragraph": 10, "end_paragraph": 18}
{"format": "pptx", "unit_type": "slide", "start_slide": 7, "end_slide": 7}
```

PDF anchors continue to use:

```json
{"format": "pdf", "unit_type": "page", "start_page": 12, "end_page": 15}
```

## Task 1: Stabilize Markdown And Existing Anchors

**Files:**

- Modify: `backend/app/services/multi_format_adapter.py`
- Modify: `backend/tests/test_multi_format_adapter.py`

- [ ] **Step 1: Add failing Markdown regression tests**

Add tests for:

- ATX headings.
- Setext headings.
- Heading-like text inside code fences.
- No-heading Markdown.
- Markdown fallback path does not reference undefined `paragraphs`.
- Markdown anchors include `unit_type: "line"`.

Suggested assertions:

```python
def test_markdown_code_fence_heading_is_not_toc(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.md"
    file_path.write_text("# Real\n\n```python\n# not a heading\n```\n", encoding="utf-8")

    result = generate_multi_format_index(file_path)

    titles = [n["title"] for n in result["structure"]]
    assert "Real" in titles
    assert "not a heading" not in titles
    assert result["structure"][0]["source_anchor"]["unit_type"] == "line"
```

- [ ] **Step 2: Run the tests and verify failure**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_multi_format_adapter.py -q
```

Expected: FAIL on Markdown fallback or missing `unit_type`.

- [ ] **Step 3: Remove the DOCX-only Markdown fallback block**

In `_extract_markdown()`, remove the low-quality block that calls `_toc_quality_score(flat_nodes, "start_paragraph")` and iterates over `paragraphs`.

Keep the later line-based fallback that uses `start_line`.

- [ ] **Step 4: Add `unit_type` to existing anchors**

Update anchors produced by current adapter code:

- TXT and Markdown: `unit_type: "line"`
- CSV and TSV: `unit_type: "row_range"`
- XLSX: `unit_type: "row_range"` with `sheet` when known
- DOCX: `unit_type: "paragraph"`
- PPTX: `unit_type: "slide"`

- [ ] **Step 5: Run adapter tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_multi_format_adapter.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/multi_format_adapter.py backend/tests/test_multi_format_adapter.py
git commit -m "fix: stabilize multi-format source anchors"
```

## Task 2: Add Canonical Adapter Structures

**Files:**

- Create: `backend/app/services/format_adapters/__init__.py`
- Create: `backend/app/services/format_adapters/base.py`
- Create: `backend/tests/test_format_adapter_base.py`

- [ ] **Step 1: Write serialization tests**

Test that canonical `DocumentContent` converts to current index JSON fields:

- `format`
- `doc_description`
- `structure`
- `page_count`
- `unit_type`
- `unit_count`
- `metadata`

- [ ] **Step 2: Run the tests and verify failure**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_format_adapter_base.py -q
```

Expected: FAIL because package does not exist.

- [ ] **Step 3: Implement dataclasses**

Create lightweight dataclasses:

```python
@dataclass(frozen=True)
class SourceAnchor:
    format: str
    unit_type: str
    values: Mapping[str, Any]

@dataclass
class ContentBlock:
    id: str
    type: str
    content: str
    source_anchor: Mapping[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class IndexNode:
    node_id: str
    title: str
    summary: str
    text: str
    start_index: int
    end_index: int
    source_anchor: Mapping[str, Any]
    level: int = 1
    nodes: list["IndexNode"] = field(default_factory=list)

@dataclass
class DocumentContent:
    format: str
    title: str
    doc_description: str
    unit_type: str
    unit_count: int
    nodes: list[IndexNode]
    blocks: list[ContentBlock] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Implement compatibility conversion**

Add `document_content_to_index(content: DocumentContent) -> dict`.

Do not migrate existing adapters in this task. This task only creates the shared target structure.

- [ ] **Step 5: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_format_adapter_base.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/format_adapters backend/tests/test_format_adapter_base.py
git commit -m "feat: add canonical format adapter structures"
```

## Task 3: Add Source Anchor Resolver

**Files:**

- Create: `backend/app/services/source_anchor_resolver.py`
- Modify: `backend/app/services/tool_executor.py`
- Create: `backend/tests/test_source_anchor_resolution.py`

- [ ] **Step 1: Write resolver tests**

Cover:

- TXT line range.
- Markdown line range.
- CSV row range.
- XLSX sheet row range, using a small generated workbook if `openpyxl` is already available.
- DOCX paragraph range, using a generated fixture if `python-docx` is already available.
- PPTX slide range, using a generated fixture if `python-pptx` is already available.
- PDF page anchor returns a compatibility result or delegates to existing page path.
- Unknown anchor returns a clear error result.

Initial test shape:

```python
def test_resolve_text_line_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.txt"
    file_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = resolve_source_anchor(
        file_path=file_path,
        document_name="notes.txt",
        anchor={"format": "txt", "unit_type": "line", "start_line": 2, "end_line": 3},
    )

    assert result["content"] == "two\nthree"
    assert result["display_label"] == "notes.txt lines 2-3"
```

- [ ] **Step 2: Run tests and verify failure**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_source_anchor_resolution.py -q
```

Expected: FAIL because resolver does not exist.

- [ ] **Step 3: Implement resolver**

Add:

```python
def resolve_source_anchor(
    file_path: Path,
    document_name: str,
    anchor: Mapping[str, Any],
) -> dict[str, Any]:
    ...
```

Return:

```json
{
  "content": "...",
  "source_anchor": {},
  "display_label": "notes.md lines 20-42",
  "status": "success"
}
```

Use `build_source_display_label()` from `backend/app/models/retrieval.py`.

Office-format handling rule:

- If a parser dependency is already present, implement real content resolution for that format in this task.
- If the dependency is not present, return `{"status": "unsupported", "reason": "..."}` and add a test that locks the explicit unsupported response. Phase 7 must replace the unsupported response with real parser-backed resolution.

- [ ] **Step 4: Integrate internally in `ToolExecutor`**

Add a private helper such as `_resolve_source_anchor_content(doc, source_anchor)`.

Do not expose a new public tool yet unless tests require it. Keep `get_page_content` compatible.

- [ ] **Step 5: Run resolver tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_source_anchor_resolution.py tests/test_source_anchor_resolution_office.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/source_anchor_resolver.py backend/app/services/tool_executor.py backend/tests/test_source_anchor_resolution.py backend/tests/test_source_anchor_resolution_office.py
git commit -m "feat: resolve content by source anchor"
```

## Task 4: Propagate Non-PDF Anchors Through Search And Tools

**Files:**

- Modify: `backend/app/services/search_service.py`
- Modify: `backend/app/services/tool_executor.py`
- Create: `backend/tests/test_non_pdf_source_anchors.py`

- [ ] **Step 1: Write search/tool output tests**

Cover at least:

- Markdown line anchor in matched segment.
- CSV row-range anchor in matched segment.
- Display label produced from anchor.
- Existing `start_index` and `end_index` remain present.

- [ ] **Step 2: Run tests and verify failure or current gaps**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_non_pdf_source_anchors.py -q
```

- [ ] **Step 3: Normalize anchors in search metadata**

In `DocumentSearchService._source_anchor_from_segment()`:

- Preserve adapter-provided anchors.
- Add missing `unit_type` only when it can be inferred safely.
- Do not convert non-PDF row/line/paragraph/slide anchors to PDF page anchors.

- [ ] **Step 4: Normalize tool output**

Ensure `_find_related_documents()` returns:

- `source_anchor`
- `display_label`
- `retrieval_source`
- `confidence`
- `why_selected`

for non-PDF matched segments.

- [ ] **Step 5: Run focused tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_non_pdf_source_anchors.py tests/test_find_related_documents_modes.py tests/test_retrieval_trace_contract.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/search_service.py backend/app/services/tool_executor.py backend/tests/test_non_pdf_source_anchors.py
git commit -m "feat: propagate non-pdf source anchors"
```

## Task 5: Preview Compatibility Pass

**Files:**

- Modify: `backend/app/services/content_extraction_service.py`
- Modify: `backend/app/api/documents.py`
- Modify: `frontend/src/types/preview.ts`
- Create: `backend/tests/test_content_extraction_source_anchors.py`

- [ ] **Step 1: Write backend preview tests**

Assert preview responses preserve existing fields and include `source_anchor` for:

- TXT/Markdown line blocks.
- CSV row blocks.
- DOCX paragraph blocks if existing extraction supports it.
- PPTX slide blocks if existing extraction supports it.

- [ ] **Step 2: Run tests and verify current behavior**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_content_extraction_source_anchors.py -q
```

- [ ] **Step 3: Add anchors without breaking old shape**

Add anchor fields to preview blocks where they are missing.

Do not require frontend visual changes beyond type compatibility in this task.

- [ ] **Step 4: Run backend tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_content_extraction_source_anchors.py tests/test_multi_format_adapter.py -q
```

- [ ] **Step 5: Run frontend build**

```powershell
cd frontend
npm.cmd run build
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/content_extraction_service.py backend/app/api/documents.py frontend/src/types/preview.ts backend/tests/test_content_extraction_source_anchors.py
git commit -m "feat: include source anchors in preview blocks"
```

## Task 6: Final Verification And Completion Gate

**Files:**

- No source changes expected.

- [ ] **Step 1: Run Phase 2 focused suite**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_multi_format_adapter.py tests/test_format_adapter_base.py tests/test_source_anchor_resolution.py tests/test_non_pdf_source_anchors.py tests/test_content_extraction_source_anchors.py tests/test_find_related_documents_modes.py tests/test_retrieval_trace_contract.py -q
```

If Office-format explicit unsupported tests were added in Task 3, include:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_source_anchor_resolution_office.py -q
```

- [ ] **Step 2: Run full backend suite**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

- [ ] **Step 3: Run frontend build**

```powershell
cd frontend
npm.cmd run build
```

- [ ] **Step 4: Run completion gate audit**

Use:

```text
docs/superpowers/completion-gate-gap-audit.md
```

Inputs:

- This Phase 2 plan.
- `docs/superpowers/2026-06-10-next-phase-roadmap.md`
- `docs/superpowers/2026-06-10-phase-1-improvement-report.md`
- Source plan: `<source-plan-copy>\docs\superpowers\plans\2026-06-10-multi-format-document-support-plan.md`
- Source plan: `<source-plan-copy>\docs\superpowers\plans\2026-06-10-core-tree-retrieval-quality-plan.md`
- Current git status.
- Test output from Steps 1-3.

- [ ] **Step 5: Create gap-closure plan if needed**

If the completion gate finds P0/P1 gaps, create:

```text
docs/superpowers/2026-06-10-phase-2-1-gap-closure.md
```

## Done Criteria

Phase 2 is complete when:

- Markdown adapter no longer references DOCX-only `paragraphs`.
- Existing supported non-PDF formats emit anchors with `unit_type`.
- Canonical adapter dataclasses exist and can convert to current index JSON.
- Source-anchor resolver can resolve current line and row anchors.
- Source-anchor resolver either resolves DOCX paragraph, XLSX row range, and PPTX slide anchors or returns tested explicit `unsupported` responses that Phase 7 is required to replace.
- Resolver responses are bounded to requested source ranges and do not expose unscoped or legacy `NULL user_id` documents.
- Search and tool outputs preserve non-PDF anchors and display labels.
- Preview responses include anchors without breaking current frontend build.
- Focused Phase 2 tests pass.
- Full backend suite passes.
- Frontend build passes.
- Completion gate passes or only records accepted P2 follow-ups.

## Out Of Scope

- Rewriting PDF indexing.
- Adding legacy `.doc`, `.xls`, `.ppt` support.
- Full frontend redesign.
- Full migration to dedicated parser adapters for every format. This is Phase 7.
- User-configurable model settings.
- Replacing `find_related_documents`.
- Building a full retrieval planner.
