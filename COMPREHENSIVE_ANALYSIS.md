
COMPREHENSIVE ANALYSIS: Uniform Distribution + Fast Path Failure
================================================================

FINDING 1: Fast Path SHOULD Work But Doesn't
--------------------------------------------

技术应用洞察 report HAS bookmarks with accurate page numbers:
  [0] s=1   pi=1  默认节
  [1] s=1.1 pi=1  幻灯片 1: 2025全球人工智能技术应用洞察报告
  [2] s=2   pi=4  第一章
  [3] s=2.1 pi=5  幻灯片 5: 全球人工智能技术发展现状
  [4] s=2.2 pi=6  幻灯片 6: 全球人工智能发展重难点分析
  ...
  [40] s=8  pi=43 幻灯片 43: ...

Total: 41 bookmarks with physical_index for ALL items!

But fast path fails because:
1. `verify_content_match` checks if TOC titles appear in page text
2. Page text is garbled (image-only PDF with pseudo-text layer)
3. Match rate becomes very low (< 10%)
4. Fast path rejects the bookmarks!

This is WRONG. Bookmarks come from PDF metadata and should be TRUSTED.
Content match verification is designed for regex-extracted TOC (which might be wrong).

FINDING 2: Uniform Distribution is a Symptom, Not Root Cause
-------------------------------------------------------------

The REAL problem: We're using visual path when we should use fast path.

Visual path flow:
1. VLM reads TOC page image → extracts 8 items
2. No page numbers visible in image → falls back to uniform distribution
3. Uniform distribution creates fake positions
4. Fake positions hide real chapter spans
5. Large node detection fails
6. Full scan never triggered
7. Result: Only 8 flat items

If fast path worked:
1. Bookmarks provide 41 items with accurate page numbers
2. No uniform distribution needed
3. Structure is already hierarchical (1, 1.1, 2, 2.1, etc.)
4. Result: Rich TOC with main chapters + sub-sections

FINDING 3: Bookmarks vs Visual Path Trade-off
----------------------------------------------

Bookmarks (Fast Path):
✓ Accurate page numbers
✓ Already hierarchical
✓ Cheap (no VLM calls)
✗ May have "幻灯片 N:" prefix noise
✗ Might include presentation artifacts

Visual Path:
✓ Extracts clean titles from images
✓ Can handle any PDF format
✗ Expensive (multiple VLM calls)
✗ Loses page numbers (falls back to uniform distribution)
✗ May miss items or extract wrong titles

For 技术应用洞察 report:
- Bookmarks are actually BETTER than visual extraction
- We just need to clean the "幻灯片 N:" prefix
- And trust the page numbers

FINDING 4: Why Other Documents Work
------------------------------------

AI眼镜 report (d9b2b5ea):
- Regex TOC with page numbers
- Text is good quality
- Content match succeeds
- Fast path works ✓

重庆案例集 (8cefa13e):
- No bookmarks, no text
- Visual path is CORRECT choice
- But visual path does full scan and finds all items ✓

技术应用洞察 (097e50d9):
- Has bookmarks but text is garbled
- Fast path fails due to content match
- Visual path loses page numbers
- Result: Poor TOC ✗

FINDING 5: The Fix Should Be Multi-Pronged
-------------------------------------------

A) Trust Bookmarks More:
   - If source is "bookmarks" or "links", skip content match verification
   - Only verify page range (1 to page_count)
   - Bookmarks are PDF metadata, inherently trustworthy

B) Remove Uniform Distribution:
   - When no page numbers exist, don't fabricate positions
   - Use dividers if available
   - Trigger full scan instead

C) Enhance Visual Path:
   - When using visual path, always use dividers for chapter boundaries
   - Don't rely on uniform distribution
   - If dividers exist, force full scan for large chapters

D) Post-Processing Safety Net:
   - After TOC construction, check if top-level nodes match dividers
   - If mismatch, use dividers to restructure

RECOMMENDED ARCHITECTURE CHANGE:
=================================

Current:
```
PDF → Analyze → Fast Path? → Bookmarks/Regex TOC
              ↓ Failed
         Balanced Path
              ↓
    Text Path (LLM) / Visual Path (VLM)
              ↓
    Post-Processing
```

Proposed:
```
PDF → Analyze → Code TOC exists?
              ↓
    YES → Source is bookmarks/links?
              ↓
         YES → Trust directly (skip content match)
              ↓
         NO  → Content match (regex needs validation)
              ↓
    NO  → Visual Path (full scan, no uniform dist)
              ↓
    All paths → Post-processing with dividers correction
```

SPECIFIC CHANGES NEEDED:
=========================

1. fast_toc.py:
   ```python
   # In try_fast_toc()
   if source in ("bookmarks", "links"):
       # Trust bookmarks/links, only do basic validation
       # Skip content match verification
       # Only check page ranges
       valid = all(1 <= it.get("physical_index", 0) <= page_count for it in toc_items)
       if valid:
           return {"toc_items": toc_items, "source": source}
   ```

2. balanced_toc.py:
   - Remove _map_uniformly()
   - In _map_toc_physical_pages():
     * If no page numbers and dividers exist → use dividers
     * If no page numbers and no dividers → trigger full scan
   - In _branch_a_toc_page():
     * After TOC extraction, if items have no page numbers
     * Use dividers to position main chapters
     * Trigger full scan for sub-chapters

3. post_processing.py:
   - Add divider-based restructuring
   - If top-level nodes don't match dividers, reorganize

COST ANALYSIS:
==============

Current approach for 技术应用洞察:
- Fast path: 1 call (fails) → 0 cost
- Visual path: ~5 VLM calls → $0.05-0.10
- Total: $0.05-0.10, result is poor

Proposed approach:
- Fast path: 1 call (succeeds for bookmarks) → $0.01
- Total: $0.01, result is accurate

For documents without bookmarks:
- Visual path with full scan: ~11 VLM calls → $0.10-0.20
- But result is accurate
- Worth the cost for accuracy

CONCLUSION:
===========

The problem is NOT just uniform distribution. The root cause chain is:

1. Bookmarks exist but fast path rejects them (content match fails on garbled text)
2. Falls back to visual path
3. Visual path extracts TOC from image without page numbers
4. Falls back to uniform distribution
5. Uniform distribution creates wrong positions
6. Wrong positions prevent large node detection
7. Full scan never triggered
8. Result: Poor TOC

Fixing ANY of these links breaks the chain:
- Fix #1: Trust bookmarks → fast path succeeds → no uniform dist needed
- Fix #2: Remove uniform dist → full scan triggers → accurate TOC
- Fix #3: Use dividers in visual path → accurate positions → no uniform dist needed

BEST FIX: All three
1. Trust bookmarks in fast path
2. Remove uniform distribution
3. Always use dividers when available

This creates a robust system that:
- Uses cheap fast path when possible (bookmarks, links)
- Uses visual path with dividers when needed
- Never fabricates positions
- Always produces accurate TOC
