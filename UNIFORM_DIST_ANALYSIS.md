"""
UNIFORM DISTRIBUTION DEEP ANALYSIS
==================================

Question: Is uniform distribution necessary? Does it add unnecessary complexity?

FINDINGS:
========

1. UNIFORM DISTRIBUTION IS A "LIE"
----------------------------------

When _map_uniformly() is called, it creates positions like:
  p.5, p.10, p.15, p.20, p.24, p.29, p.34, p.39

These positions are MATHEMATICALLY correct (evenly spaced) but SEMANTICALLY wrong.
The real chapters are at:
  p.5, p.13, p.25, p.38

Problem: The system now BELIEVES these fake positions and makes decisions based on them:
- Large node detection: All spans are ~5 pages → no large nodes detected
- Full scan trigger: Blocked because no large nodes
- Post-processing: Thinks coverage is complete (which it is, but structure is wrong)

2. WHEN IS IT USED?
-------------------

Current flow in _map_toc_physical_pages:

a) If items have page numbers → standard offset ✓
b) If items have page numbers but unreliable → proportional mapping ✓
c) If NO page numbers:
   - Check dividers → if match, use dividers ✓ (but this is fragile)
   - Otherwise → uniform distribution ✗ (THIS IS THE PROBLEM)

For 技术应用洞察 report:
- VLM extracts 8 items from TOC page image
- Items don't have "page" field (TOC page doesn't show page numbers)
- Dividers check: top_items (8) != dividers (4) → doesn't match
- Falls back to uniform distribution

3. WHY DIVIDERS CHECK FAILS
---------------------------

Code in _map_toc_physical_pages:
```python
if dividers:
    top_items = [it for it in toc_items if "." not in str(it.get("structure", ""))]
    if top_items and len(top_items) == len(dividers):
        # Use dividers
```

Problem: VLM extracted 8 items, but only 4 are top-level chapters.
The other 4 are sub-sections that VLM mistakenly made top-level.

So top_items = 8, dividers = 4 → mismatch → uniform distribution

4. THE REAL ALTERNATIVES
------------------------

Instead of uniform distribution, we should:

Option A: Use dividers as chapter boundaries
- If dividers exist, they are the GROUND TRUTH for chapter starts
- Don't try to match top_items count with dividers count
- Simply assign each divider to the nearest chapter item

Option B: Cross-reference with bookmarks
- 技术应用洞察 report HAS bookmarks with 41 items and accurate page numbers!
- Why aren't we using them?
- Bookmarks show: Chapter 1 at p.4, sub-sections at p.5, p.6, etc.

Option C: Full document scan
- Scan all pages to find real chapter starts
- More expensive but 100% accurate
- Should be triggered when:
  * No page numbers
  * Dividers exist but can't be matched
  * Document is short (< 50 pages)

5. WHAT BREAKS IF WE REMOVE UNIFORM DISTRIBUTION?
-------------------------------------------------

Let's check all test documents:

a) 技术应用洞察 (097e50d9):
   - Has bookmarks with page numbers
   - Has dividers
   - DOESN'T NEED uniform distribution
   - Should use bookmarks or dividers

b) AI眼镜 (d9b2b5ea):
   - Text path, has regex TOC with page numbers
   - Never reaches uniform distribution
   - NOT AFFECTED

c) 重庆案例集 (8cefa13e):
   - Image-only PDF
   - No bookmarks, no text
   - Visual path, full scan
   - Never reaches uniform distribution
   - NOT AFFECTED

d) 第五范式 (90e75e6f):
   - Text path, regex TOC with page numbers
   - Never reaches uniform distribution
   - NOT AFFECTED

e) AI治理 (a1ed6276):
   - Bookmarks with page numbers
   - Never reaches uniform distribution (fast path works)
   - NOT AFFECTED

f) AI Agent (9cf5b5be):
   - Links TOC with page numbers
   - Never reaches uniform distribution
   - NOT AFFECTED

CONCLUSION: Removing uniform distribution would NOT break any of our test documents.

6. WHAT ABOUT EDGE CASES?
-------------------------

Q: What if a document has:
   - No bookmarks
   - No text (image-only)
   - No dividers
   - TOC page without page numbers
   - Long document (> 50 pages)

A: This is extremely rare. But if it happens:
   - We could do a sampled scan (every N pages) to find chapter starts
   - Or accept that we can't determine exact positions
   - It's better to have no positions than wrong positions

7. RECOMMENDED SOLUTION
-----------------------

REMOVE uniform distribution entirely. Replace with:

a) If dividers exist:
   - Use dividers to position main chapters
   - Don't require exact count match
   - Use fuzzy matching (nearest chapter to each divider)

b) If no dividers but has bookmarks:
   - Use bookmarks for page numbers (fast path)
   - This should be the default for most PDFs

c) If no page numbers at all:
   - For short docs (< 50 pages): full document scan
   - For long docs: sampled scan or accept uncertainty

d) Post-processing enhancement:
   - If tree has large nodes (> 8 pages) with no children
   - Trigger sub-extraction for those nodes

8. COMPLEXITY ANALYSIS
----------------------

Current complexity:
```
_map_toc_physical_pages
├── OCR verification
├── Standard offset
├── Proportional mapping
├── Fixed compression detection
└── Uniform distribution (fallback)
    └── _map_uniformly
        └── _ensure_monotonic_physical
```

Simplified complexity:
```
_map_toc_physical_pages
├── OCR verification
├── Standard offset
├── Proportional mapping
├── Fixed compression detection
└── Dividers matching (if available)
    └── Fuzzy match chapters to dividers
```

This removes:
- _map_uniformly function (~15 lines)
- Complex fallback logic in _map_toc_physical_pages (~20 lines)
- The false confidence that comes with fabricated positions

9. IMPACT ON 技术应用洞察 REPORT
----------------------------------

With uniform distribution removed:
- VLM extracts 8 items from TOC page
- Dividers [5, 13, 25, 38] are detected
- System matches 4 main chapters to dividers
- Sub-sections are identified by smart grouping
- Full scan is triggered for large chapters
- Result: Rich TOC with main chapters + sub-sections

Expected result:
```
[1] p.5  全球人工智能技术发展现状
  [1.1] p.5 全球人工智能技术发展市场格局
  [1.2] p.6 全球人工智能发展重难点分析
  ...
[2] p.13 AI十大行业应用洞察
  [2.1] p.13 全球重点行业人工智能渗透率
  [2.2] p.17 智能制造
  [2.3] p.18 智慧金融
  ...
[3] p.25 全球人工智能应用突破
  ...
[4] p.38 全球人工智能应用未来趋势
  ...
```

This is MUCH better than uniform distribution's:
```
[1] p.5   全球人工智能技术发展现状
[2] p.10  全球数据算力算法变化对产业影响  ← WRONG! Should be p.13
[3] p.15  AI十大行业应用洞察              ← WRONG! Should be p.13
...
```

10. CONCLUSION
--------------

YES, uniform distribution should be REMOVED because:

1. It fabricates wrong positions
2. It prevents large node detection
3. It adds complexity without value
4. Better alternatives exist (dividers, bookmarks, full scan)
5. None of our test documents actually need it
6. Removing it simplifies the code and improves accuracy

The ONLY case where it might be needed is extremely rare:
- No bookmarks, no text, no dividers, no page numbers
- In that case, it's better to admit uncertainty than lie
"""

print(__doc__)
