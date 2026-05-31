# Phase 2 & 3: Pattern Analysis & Root Cause Hypothesis

## Evidence Summary

### File Status Overview

| File | DB Status | TOC Items | Top-level | Structure Quality | Issue |
|------|-----------|-----------|-----------|------------------|-------|
| **AI Agent 2026** | completed | 117 | 2 (should be 9) | ❌ Empty main chapter structure | Main chapters have empty structure |
| **第五范式 2025** | completed | 20 | 10 (should be 3) | ❌ Missing main chapter 3 | Sub-chapters 3.x exist but chapter 3 missing |
| **技术应用洞察 2025** | completed | 28 | 4+children | ✅ Correct hierarchy | Fixed! |
| **AI治理 2025** | failed | N/A | N/A | ❌ Failed at fast TOC | Fast mode failed, no balanced fallback |

---

## Problem A: AI Agent 2026 - Empty Main Chapter Structure

### Evidence
```
[0] struct="" (EMPTY) | pi=10 | Chapter 1 title
[1] struct="" (EMPTY) | pi=11 | Chapter 1 summary
[2] struct=1.1 | pi=12 | Sub-chapter
[3] struct=1.2 | pi=13 | Sub-chapter
...
[16] struct="" (EMPTY) | pi=26 | Chapter 2 title
[17] struct="" (EMPTY) | pi=27 | Chapter 2 summary
[18] struct=2.1 | pi=28 | Sub-chapter
```

### Pattern
- Main chapter titles (e.g., "第一章", "第二章") have **empty structure**
- Chapter summaries (e.g., "导语") also have **empty structure**
- Sub-chapters have correct structure (1.1, 1.2, 2.1, etc.)
- Result: `build_tree()` sees empty structure → cannot split → merges everything into 1 node

### Root Cause Hypothesis
**_infer_structure_from_numbers() fails to assign structure to main chapters**

When VLM extracts TOC:
- Main chapters may have `number` field empty or non-standard
- `_infer_structure_from_numbers()` only processes items with `number` field
- Items without `number` get structure="" (empty string)
- Empty structure breaks `build_tree()` logic

---

## Problem B: 第五范式 2025 - Missing Main Chapter

### Evidence
```
[0] struct=1.1 | pi=4
[1] struct=1.2 | pi=7
[2] struct=2.1 | pi=14
[3] struct=2.2 | pi=22
[4] struct=3.1 | pi=39  ← Sub-chapter WITHOUT parent 3
[5] struct=3.2 | pi=40  ← Sub-chapter WITHOUT parent 3
[6] struct=3.3 | pi=41  ← Sub-chapter WITHOUT parent 3
[7] struct=3.4 | pi=53  ← Should be under chapter 4?
[8] struct=4 | pi=49    ← Main chapter 4 (exists)
[9] struct=4.2 | pi=51
...
[13] struct=5 | pi=61   ← Main chapter 5 (exists)
```

### Pattern
- Main chapter "3" is **completely missing** from TOC
- Sub-chapters 3.1, 3.2, 3.3 exist but float as top-level
- Main chapters 4 and 5 exist correctly
- Code TOC source: **regex** (not VLM)

### Root Cause Hypothesis
**Regex extraction missed chapter 3 in the PDF bookmarks/code TOC**

The PDF's internal TOC/bookmarks may not have chapter 3 as a separate entry, or regex pattern failed to match it. This is a data extraction issue, not a processing issue.

---

## Problem C: AI治理 2025 - Fast Mode Failure

### Evidence
```
Status: failed:fast_toc_incomplete
Error: FAST_TOC_INCOMPLETE: quality_score=0.50 < 0.6
Issues: Page numbers exceed total pages
```

### Pattern
- Fast TOC extraction succeeded but quality check failed
- Code TOC page numbers are wrong (57, 59, 60 > total 54)
- **Should have fallen back to balanced mode** but didn't

### Root Cause Hypothesis
**Fast → Balanced fallback logic has a bug or is bypassed**

In `_generate_index_v2()`:
```python
if execution_mode == "fast":
    fast_result = await try_fast_toc(analysis, model)
    if fast_result:
        toc_items = fast_result["toc_items"]
        toc_source = fast_result["source"]
    elif requested_mode == "fast":
        raise ValueError("FAST_TOC_INCOMPLETE...")
    else:
        print("[INDEX-V3] Fast failed, escalating to balanced")
        execution_mode = "balanced"
```

**Bug**: `try_fast_toc()` returned a result (not None), so it didn't enter the `else` branch. But the result had bad quality. The quality check happens later in `meta_processor()` (old code) or not at all in v2.

---

## Problem D: 技术应用洞察 2025 - FIXED ✅

### What Worked
- Dividers [5, 13, 25, 38] correctly assigned to 4 main chapters
- Smart grouping identified alternating pattern (Chinese + Arabic numbers)
- VLM full-scan extracted 40 page titles for sub-chapters
- Result: 28 items with correct hierarchy

### Why It Worked Here But Not Others
- This file has **clear alternating pattern**: 一, 2, 二, 4, 三, 6, 四, 8
- `_smart_identify_chapters()` successfully detected this pattern
- AI Agent doesn't have clear pattern (empty structures)
- 第五范式 has missing main chapter (not a pattern issue)

---

## Root Cause Summary

### Issue 1: AI Agent - Empty Structure
**Root Cause**: `_infer_structure_from_numbers()` doesn't handle items with empty `number` field when they should be main chapters.

**Fix Strategy**: 
- Detect main chapter titles (e.g., contain "章", "部分", "Chapter")
- Assign sequential structure to empty-structure items that appear before sub-chapters

### Issue 2: 第五范式 - Missing Chapter 3
**Root Cause**: PDF's code TOC (regex extracted) is missing chapter 3.

**Fix Strategy**:
- Post-process TOC to detect gaps in structure sequence (1, 2, missing 3, 4, 5)
- Insert placeholder or merge orphans under previous chapter

### Issue 3: AI治理 - Fast Mode No Fallback
**Root Cause**: `try_fast_toc()` returns result even when quality is bad, bypassing fallback logic.

**Fix Strategy**:
- Add quality check immediately after `try_fast_toc()`
- If quality_score < threshold, force fallback to balanced

---

## Validation Plan

### Test 1: Fix Empty Structure
```python
# Test _infer_structure_from_numbers with empty main chapters
toc_items = [
    {"number": "", "title": "第一章"},
    {"number": "", "title": "导语"},
    {"number": "1.1", "title": "子章节1"},
    {"number": "1.2", "title": "子章节2"},
    {"number": "", "title": "第二章"},
    {"number": "2.1", "title": "子章节3"},
]
# Expected: structure should be ["1", "1.1", "1.1.1", "1.1.2", "2", "2.1"]
```

### Test 2: Fix Missing Chapter
```python
# Test post-processing with missing main chapter
toc_items = [
    {"structure": "1.1", "title": "Sub 1"},
    {"structure": "2.1", "title": "Sub 2"},
    {"structure": "3.1", "title": "Sub 3"},  # Orphan
    {"structure": "3.2", "title": "Sub 4"},  # Orphan
    {"structure": "4", "title": "Chapter 4"},
]
# Expected: detect missing chapter 3, create placeholder or merge orphans
```

### Test 3: Fix Fast Fallback
```python
# Verify fast → balanced fallback triggers when quality is bad
# Run AI治理 report through _generate_index_v2
# Expected: should use balanced mode, not fail
```
