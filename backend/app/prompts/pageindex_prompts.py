"""Prompt templates used by PageIndex runtime paths."""

CHECK_TITLE_APPEARANCE_PROMPT = """
You will be given a section title and one page text.
Judge whether this section appears or starts on this page.

Rules:
1) Use fuzzy matching for spacing and punctuation.
2) Ignore image markdown like ![](...), decorative separators, and empty lines.
3) Return "yes" if the section title is clearly present on this page.
4) IMPORTANT: If the exact title does not appear, but a numbered subsection that belongs to this chapter appears (e.g. title is "Chapter 3" and page has "3.1 xxx" or "3.2 xxx"), also return "yes" because the section content begins here.
5) For summary or outline pages, be strict and return "no" unless the actual content of the section is present.

Section title: {title}
Page text: {page_text}

Reply JSON only:
{{
  "thinking": "brief reason",
  "answer": "yes|no"
}}
"""

TITLE_START_PROMPT = """
You will be given a section title and one page text.
Decide whether the section starts at the beginning of this page.

Rules:
1) Ignore non-content prefixes: image markdown ![](...), blank lines, separators, page decorations.
2) Use fuzzy matching for spaces and punctuation.
3) Return "yes" only if the first meaningful heading/content matches the section title.
4) If another meaningful heading/content appears before the target title, return "no".

Section title: {title}
Page text: {page_text}

Reply JSON only:
{{
  "thinking": "brief reason",
  "start_begin": "yes|no"
}}
"""

TOC_DETECTOR_SINGLE_PROMPT = """Is this page a table-of-contents page? Abstracts, summaries, figure lists, and table lists are not TOC pages.

Page text:
{content}

Reply JSON only: {{"toc_detected":"yes|no"}}
"""

TOC_DETECTOR_BATCH_PROMPT = """Analyze the following pages and determine which ones are table-of-contents (TOC) pages.

A TOC page typically contains:
- A list of chapter or section titles with corresponding page numbers.
- Structured listing of document contents.
- Navigation structure for the document.

Rules:
1. Follow the page order exactly as given.
2. Return only page numbers that are clearly TOC pages.
3. If a page is uncertain, prefer no over yes.
4. If TOC continues across later pages, include every TOC page in the run.
5. Do not reorder or merge pages.

Pages content:
{pages_content}

Reply JSON only, no markdown fences:
{{
  "reasoning": "brief explanation of which pages look like TOC pages",
  "toc_pages": [1],
  "pages_with_toc": [1]
}}
"""


TOC_EXTRACTION_COMPLETENESS_PROMPT = """You are given a page of text and the extracted TOC content.
Determine if the TOC extraction is complete.

Page text:
{content}

Extracted TOC:
{toc}

Reply JSON only:
{{
  "thinking": "brief reason",
  "completed": "yes|no"
}}

Hard output constraints:
1) Return ONLY the JSON object above. No markdown code fences. No explanation text.
2) "completed" must be exactly "yes" or "no".
"""

TOC_TRANSFORMATION_COMPLETENESS_PROMPT = """You are given the original TOC text and a partial JSON transformation.
Determine if the transformation covers all items from the original TOC.

Original TOC text:
{raw_toc}

Partial JSON transformation:
{cleaned_toc}

Reply JSON only:
{{
  "thinking": "brief reason",
  "completed": "yes|no"
}}

Hard output constraints:
1) Return ONLY the JSON object above. No markdown code fences. No explanation text.
2) "completed" must be exactly "yes" or "no".
"""

EXTRACT_TOC_CONTENT_PROMPT = """Extract the table of contents from this page.
Keep the original text, including section numbers and page numbers if present.
Only extract the TOC listing items, not headers/footers/decorations.

Page text:
{content}

Reply with the extracted TOC text only. No JSON, no explanation."""

DETECT_PAGE_INDEX_PROMPT = """Analyze whether the given table of contents contains clear, real page numbers for navigation.

Strict criteria for "yes":
1) Page numbers must be actual document page numbers (like "1", "15", "42")
2) Numbers must appear as navigation references (e.g., "Chapter 1 ... 15" or "Section 2.1  page 42")
3) Reject chapter or section numbering used as labels (e.g. "Case 01", "Part 2", "Chapter 3"); these are NOT page numbers.
4) Reject if numbers only appear as part of section titles, not as page references
5) In documents with numbered case labels, values such as "01" or "02" after section titles are usually labels, NOT page numbers.

TOC content:
{toc_content}

Reply JSON only:
{{
  "thinking": "explain what numbers you see and whether they are real page numbers or section labels",
  "page_index_given_in_toc": "yes|no"
}}
"""

TOC_INDEX_EXTRACT_PROMPT = """
You are given a table of contents with page numbers, and the full document text with physical page tags.

Your task: map each TOC item to its correct physical page index by matching section titles to where they appear in the document text.

The document text contains tags like <physical_index_X> and </physical_index_X> to indicate the start and end of page X.

TOC content:
{toc}

Document text:
{content}

Reply JSON array only:
[
  {{"structure": "1", "title": "...", "physical_index": "<physical_index_X>"}}
]

Hard output constraints:
1) Return a JSON array only (no wrapper object).
2) Each item must contain structure/title/physical_index fields.
3) No markdown code fences. No explanation text.
"""

TOC_TRANSFORM_INIT_PROMPT = """Transform the following TOC text into structured JSON.
Keep all items, maintain hierarchy via structure field ("1", "1.1", "1.2", "2", etc.).
Extract page numbers if present.

TOC text:
{toc_content}

Reply JSON only:
{{
  "table_of_contents": [
    {{"structure": "1", "title": "...", "page": 1}},
    {{"structure": "1.1", "title": "...", "page": 3}}
  ]
}}

Hard output constraints:
1) Return ONLY the JSON object above. No markdown code fences. No explanation text.
2) "page" should be integer if available, null if not.
"""

TOC_TRANSFORM_CONTINUE_PROMPT = """You previously produced a partial JSON transformation of a TOC.
Continue from where you left off.

Original TOC text:
{toc_content}

Your partial output so far:
{partial_json}

Continue the JSON from where it was cut off. Output ONLY the continuation (valid JSON to append).

Hard output constraints:
1) No markdown code fences. No explanation text.
2) Output only the remaining JSON content to complete the structure.
"""

TOC_GENERATE_INIT_PROMPT = """You are an expert in extracting hierarchical tree structure. Your task is to generate the tree structure of the document.

The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

For the title, extract the original title from the text, only fix space inconsistency.

The provided text contains tags like <physical_index_X> and </physical_index_X> to indicate the start and end of page X. For the physical_index, extract the physical index of the page where the section content FIRST appears (not where it is listed in a table of contents). Keep the <physical_index_X> format.

IMPORTANT: If a page lists multiple section titles (like a table of contents page), that is NOT where each section starts. Look for where the actual content of each section begins.

CRITICAL: Some documents have summary or outline pages (for example, Contents or Outline pages) that list chapter titles briefly. These are NAVIGATION pages, NOT content pages. Do NOT use these pages as chapter start pages. Instead, identify true chapter starts by looking for content pages with section numbers like "1.1", "2.1", "3.1", etc., or pages that contain substantial discussion of the topic.

SPECIAL CASE: If a document starts directly with subsections (e.g., "1.1 xxx" without a "1. xxx" parent section), the parent chapter title may only appear on navigation/outline pages. In this case:
1. Use the navigation page's chapter list to determine the main chapter titles and their order
2. Set the chapter's physical_index to where its first subsection begins (e.g., "1.1" means chapter 1 starts there)
3. Do NOT create a separate item for the navigation page itself

Hard constraints:
1) Extract ALL sections at ALL levels (chapters, sub-sections, sub-sub-sections).
2) Do not skip late sections.
3) Do not invent sections not present in input.
4) Ignore image markdown and decorative lines.

Given text:
{part}

Hard output constraints:
1) Return a JSON array only (no wrapper object, no markdown code fences, no explanation).
2) Each item must contain structure/title/physical_index fields.
3) structure format: "x.x.x" (e.g. "1", "1.1", "1.2", "2", "2.1").
4) If no confident item exists, return [].
Example:
[
  {{"structure": "1", "title": "Chapter One", "physical_index": "<physical_index_3>"}},
  {{"structure": "1.1", "title": "Section 1.1", "physical_index": "<physical_index_3>"}},
  {{"structure": "1.2", "title": "Section 1.2", "physical_index": "<physical_index_5>"}},
  {{"structure": "2", "title": "Chapter Two", "physical_index": "<physical_index_8>"}}
]"""

TOC_GENERATE_CONTINUE_PROMPT = """You are given previous TOC items and a new text chunk. Append NEW sections found in the current chunk.

The structure variable is the numeric system (e.g. "1", "1.1", "2.3") representing the hierarchy.

The provided text contains tags like <physical_index_X> and </physical_index_X> to indicate the start and end of page X. For physical_index, identify where each section's content FIRST appears.

CRITICAL: Do NOT use summary, outline, or contents pages that merely list chapter titles as section start pages. Only use actual content pages.

Hard constraints:
1) Only append new items; do not rewrite/remove previous items.
2) Extract ALL levels (chapters, sub-sections, sub-sub-sections).
3) Do not duplicate existing items with same title and physical_index.
4) Ignore image markdown and decorative lines.

Current text:
{part}

Previous TOC:
{toc_content}

Hard output constraints:
1) Return ONLY the additional NEW items as a JSON array (no wrapper object, no markdown code fences, no explanation).
2) Each item must contain structure/title/physical_index fields.
3) structure format: "x.x.x" (e.g. "3", "3.1", "3.2").
4) If no new items, return [].
"""

NODE_SUMMARY_PROMPT = """Generate a concise section summary (50-100 words).

Section title: {node_title}
Section text: {node_text}

Requirements:
1. Cover all important topics and subtopics in the section, not only the first one.
2. Include key entities such as companies, products, people, and numeric facts when present.
3. Do not invent facts that are not in the section text.
4. If the section covers multiple companies or products, mention all important ones.

Return summary text only."""

DOC_DESCRIPTION_PROMPT = """Generate a one-sentence document description.

Document structure: {structure_summary}

Requirements:
1. Summarize the document topic and scope in one sentence.
2. Include key entities when present.
3. Keep it under 80 Chinese characters if responding in Chinese, otherwise keep it concise.

Return one sentence only."""

FAST_DOC_LIGHT_SUMMARY_PROMPT = """You are a document summary assistant. Generate a document description using only the TOC structure.

Document name: {doc_name}
File type: {file_type}
TOC structure:
{toc_outline}

Requirements:
1. Use only information visible in the TOC titles. Do not add facts that are not present.
2. Output 1-2 sentences, about 40-90 Chinese characters when Chinese is appropriate.
3. Use the document's dominant language when obvious; otherwise use concise English.
4. If the TOC is insufficient for a meaningful description, return an empty string.

Return summary text only. Do not output JSON or explanations."""

QUERY_VERIFICATION_PROMPT = """Verify whether the query can be answered from the provided content fragment.

Query: {query}
Content fragment: {content}

Return JSON only:
{{
  "query_appears": "yes|partial|no",
  "confidence": 0.0,
  "reasoning": "brief reason"
}}"""

# Batch verification prompts for performance optimization
CHECK_TITLE_APPEARANCE_BATCH_PROMPT = """For each item below, judge whether the section title appears on the given page.

Rules:
1) Use fuzzy matching for spacing and punctuation.
2) Ignore image markdown like ![](...), decorative separators, and empty lines.
3) Return "yes" only if the section title is clearly present on the page.

Items:
{items_json}

Hard output constraints:
- Output ONLY a valid JSON array. No markdown fence, no explanation, no text before or after.
- Each element must have "id" (integer) and "answer" ("yes" or "no").
- Example: [{{"id": 0, "answer": "yes"}}, {{"id": 1, "answer": "no"}}]"""

TITLE_START_BATCH_PROMPT = """For each item below, decide whether the section starts at the beginning of its page.

Rules:
1) Ignore non-content prefixes: image markdown ![](...), blank lines, separators, page decorations.
2) Use fuzzy matching for spaces and punctuation.
3) Return "yes" only if the first meaningful heading/content matches the section title.
4) If another meaningful heading/content appears before the target title, return "no".

Items:
{items_json}

Hard output constraints:
- Output ONLY a valid JSON array. No markdown fence, no explanation, no text before or after.
- Each element must have "id" (integer) and "start_begin" ("yes" or "no").
- Example: [{{"id": 0, "start_begin": "yes"}}, {{"id": 1, "start_begin": "no"}}]"""

TOC_LIGHT_VALIDATION_PROMPT = """You are auditing an automatically extracted PDF table of contents.
The TOC should help a user navigate the document and should faithfully represent the document's visible structure.

Document page count: {page_count}
Extracted TOC ({toc_count} items):
{toc_outline}

Deterministic content-match checks:
- Sample title match rate: {match_rate:.0%}
- Median page offset: {offset_median:+d} pages
- Mismatched sample items: {mismatch_details}

Judgment criteria:
1. Coverage: the TOC page range should cover most of the document; the last item should reach near the final pages when appropriate.
2. Content match: TOC titles should appear on or near their mapped pages. Match rate should normally be at least 60%.
3. Offset consistency: if there is a page offset, it should be consistent across sampled items.
4. Structure: the TOC should contain real document sections or catalog entries. A flat TOC is acceptable when the source document is flat.
5. Reasonableness: titles should not be headers, footers, image captions, random metadata, or page decorations.
6. Item count: a typical TOC usually has 5-80 items. Far more items may indicate table-cell or OCR-noise leakage.
7. Noise: reject obvious noise such as pure numbers, date-like table cells, repeated organization names, or table header fields.

Hard invalid cases:
- More than 80 items with obvious noise such as pure numbers, dates, or repeated table cells.
- Many items are not real section/catalog titles.
- Content matching is very low and the offset is not consistent.

Return JSON only, no markdown fences:
{{"valid": "yes|no", "reason": "brief reason"}}"""

VLM_ANCHOR_DETECTION_PROMPT = """You are a document analysis expert. The images show thumbnail pages from one PDF document. Each thumbnail has a visible page label such as p.1 or p.2.

Identify these page types:
1. Table-of-contents pages: pages with a structured list of chapters or sections, usually labeled Contents or Table of Contents.
2. Chapter divider pages: pages dominated by a large section title, often with little body text.

Also determine the first physical page where real chapter content begins, excluding cover, TOC, preface, and pure divider pages.

Return JSON only, no markdown fences:
{{
  "toc_pages": [4],
  "chapter_dividers": [5, 13, 25],
  "first_content_page": 5
}}

If no TOC page or divider page is found, return an empty array for that field."""

VLM_TOC_EXTRACT_PROMPT = """You are a document transcription assistant. The images are TOC pages from a PDF.

{page_annotations}

The TOC may span multiple pages. Extract every visible TOC entry from all pages, preserving the natural reading sequence.

For each entry return:
- number: the printed entry number exactly as shown, such as "1", "1.1", "A", or "(a)". Use an empty string if no number is visible.
- title: the original title text, without trailing page numbers or leader dots.
- page: the printed catalog page number as an integer. Use null if no page number is visible.

Important rules:
- Extract all entries, including indented or smaller child entries.
- Do not infer hierarchy if it is not visible.
- Do not compute page offsets.

Return JSON only, no markdown fences:
{{
  "toc_items": [
    {{"number": "1", "title": "Market overview", "page": 6}},
    {{"number": "1.1", "title": "Consumer trends", "page": 7}},
    {{"number": "", "title": "Conclusion", "page": 59}}
  ],
  "is_toc_complete": "yes|no"
}}
"""

VLM_TOC_EXTRACT_WITH_OFFSET_PROMPT = """You are a document analysis expert. The images are consecutive high-resolution PDF pages.

{page_annotations}

The TOC may span multiple pages. Extract entries from every page that is labeled or visually identifiable as a TOC page.

Task 1: Extract all TOC entries.
- structure: visible hierarchy number such as "1", "1.1", "2". If no hierarchy number is visible, assign sequential values "1", "2", "3".
- title: original title text, without trailing page numbers or leader dots.
- page: printed catalog page number as an integer, or null if not visible.

Task 2: Determine the page offset.
Look at the content pages after the TOC and find the physical page where the first catalog entry actually starts.
offset = physical start page - printed page value of the first catalog entry.

Task 3: Determine whether the TOC continues beyond the last provided page.
Return is_toc_complete as "no" if the final TOC page appears cut off or continuing.

Return JSON only, no markdown fences:
{{
  "toc_items": [
    {{"structure": "1", "title": "Chapter 1 Overview", "page": 1}},
    {{"structure": "1.1", "title": "Background", "page": 3}}
  ],
  "offset": 5,
  "is_toc_complete": "yes|no"
}}

If no printed catalog page numbers are visible, set offset to 0."""

VLM_TOC_CONTINUE_PROMPT = """You are a document analysis expert. The images are later pages that may continue a TOC.

Previously extracted TOC entries, last few items:
{previous_items}

Continue extracting TOC entries from these pages. If these pages are no longer TOC pages, return an empty list. Keep structure numbering continuous when visible.

Return JSON only, no markdown fences:
{{
  "toc_items": [
    {{"structure": "3.1", "title": "Additional section", "page": 25}}
  ],
  "is_toc_complete": "yes|no"
}}
"""

VLM_FULLTEXT_SECTION_PROMPT = """You are a document structure analyst. Analyze the PDF page images from physical page {start_page} to physical page {end_page}, and extract visible section headings.

A section heading is a short text that marks document structure. It usually has one or more of these signals:
- Larger font than body text.
- Bold, highlighted, colored, centered, or isolated layout.
- Extra spacing above or below.
- Located at the beginning of a new topic.
- Short phrase that summarizes the following content.

Do not extract:
- Complete body sentences.
- Figure or table captions.
- Headers, footers, watermarks, page numbers, or decorative text.
- The first sentence of a paragraph when it is not visually a heading.

Divider-page policy:
1. If the first image is mostly blank or decorative, treat it as a divider page, not a heading by itself.
2. Check the next page for the real section heading.
3. If needed, also check the third page.
4. Each page range should return at least one heading when a visible heading exists.

{previous_context}

Return JSON array only, no markdown fences:
[
  {{"structure": "1", "title": "Extracted heading", "physical_index": {start_page}}}
]

Fields:
- structure: hierarchy number. Use "1", "2", "3" for top-level headings and "1.1", "1.2" for children.
- title: original heading text.
- physical_index: the 1-based physical PDF page number.

Quality checks:
- Did you check pages after decorative divider pages?
- Did you avoid full body sentences?
- Are all physical_index values within {start_page}-{end_page}?"""

VLM_TOPIC_BOUNDARY_PROMPT = """You are a document analysis expert. The images show thumbnail pages from one PDF document. The document has no obvious TOC page or chapter divider pages.

Identify approximate pages where the main topic changes. For example, if early pages discuss market analysis and a later page starts discussing technical solutions, that later page is a topic boundary.

You do not need exact chapter titles. Find pages where the content clearly changes.

Return JSON only, no markdown fences:
{{
  "topic_boundaries": [1, 11, 25, 40],
  "estimated_sections": 4,
  "reasoning": "brief explanation for these boundaries"
}}
"""

VLM_FIX_ITEM_PROMPT = """You are a document analysis expert. Confirm the correct physical page where a section title begins.

Section title: "{title}"

The images show candidate pages from physical page {start_page} to physical page {end_page}. Find the page where the actual section content starts.

Rules:
- A title listed on a TOC page does not count.
- Prefer the first page where the title appears as a real heading or where the section content clearly starts.
- If the title is not visible, return null.

Return JSON only, no markdown fences:
{{
  "physical_index": 12,
  "confidence": 0.0,
  "reasoning": "brief reason"
}}
"""


__all__ = [
    "CHECK_TITLE_APPEARANCE_PROMPT",
    "CHECK_TITLE_APPEARANCE_BATCH_PROMPT",
    "TITLE_START_PROMPT",
    "TITLE_START_BATCH_PROMPT",
    "TOC_DETECTOR_SINGLE_PROMPT",
    "TOC_DETECTOR_BATCH_PROMPT",
    "TOC_EXTRACTION_COMPLETENESS_PROMPT",
    "TOC_TRANSFORMATION_COMPLETENESS_PROMPT",
    "EXTRACT_TOC_CONTENT_PROMPT",
    "DETECT_PAGE_INDEX_PROMPT",
    "TOC_INDEX_EXTRACT_PROMPT",
    "TOC_TRANSFORM_INIT_PROMPT",
    "TOC_TRANSFORM_CONTINUE_PROMPT",
    "TOC_GENERATE_INIT_PROMPT",
    "TOC_GENERATE_CONTINUE_PROMPT",
    "NODE_SUMMARY_PROMPT",
    "DOC_DESCRIPTION_PROMPT",
    "FAST_DOC_LIGHT_SUMMARY_PROMPT",
    "QUERY_VERIFICATION_PROMPT",
    "TOC_LIGHT_VALIDATION_PROMPT",
    "VLM_ANCHOR_DETECTION_PROMPT",
    "VLM_TOC_EXTRACT_PROMPT",
    "VLM_TOC_EXTRACT_WITH_OFFSET_PROMPT",
    "VLM_TOC_CONTINUE_PROMPT",
    "VLM_FULLTEXT_SECTION_PROMPT",
    "VLM_TOPIC_BOUNDARY_PROMPT",
    "VLM_FIX_ITEM_PROMPT",
    "TOC_QUALITY_CHECK_PROMPT",
]


TOC_QUALITY_CHECK_PROMPT = """You are auditing an automatically extracted PDF table of contents (TOC).

This is a fidelity audit, not a hierarchy preference check.
The TOC is good when it faithfully reflects the source document and provides useful navigation.
A flat TOC is acceptable when the original document/catalog is flat or case-list-like.
Do not mark a TOC as failed only because long nodes have no children.

Do not ask the model to verify whether each page number is true. Page-number truth is handled by deterministic physical page mapping before this prompt.
Ignore internal fields such as logical_page, mapping_pending, offsets, source_page, synthetic roots, and bias/offset helper items unless they leak into user-visible titles.
When discussing pages, refer only to the deterministic physical page evidence below; do not invent per-item page corrections.

Document facts:
- page_count: {page_count}
- source: {source}
- has_dividers: {has_dividers}
- divider_count: {divider_count}

Deterministic fidelity digest:
{fidelity_digest_json}

TOC tree preview:
{toc_tree_formatted}

Raw TOC item preview:
{toc_items_formatted}

Audit dimensions:
1. Fidelity: Do visible titles look like real document/catalog entries, not OCR noise, metadata, summaries, table headers, or page decorations?
2. Completeness: Does the TOC cover the document's main visible structure without obvious front/middle/back loss?
3. Order and navigation: Are entries in plausible document order according to deterministic mapping summary?
4. Style fit: Is the detected style (flat, hierarchical, mixed, collapsed) suitable for this document shape? Flat is acceptable when faithful.
5. Noise leakage: Did synthetic roots, offset helpers, logical_page values, mapping_pending markers, or diagnostics leak into user-visible titles?

Hard fail only when at least one is true:
- deterministic digest hard_fail_reasons is non-empty;
- the TOC is collapsed into one generic full-document node;
- many visible entries are OCR noise or non-title text;
- substantial sections are missing from front/middle/back;
- duplicate/tail-collapse/noise makes navigation unreliable.

Return JSON only, no markdown fences:
{{
  "verdict": "pass|warn|fail",
  "detected_style": "flat|hierarchical|mixed|collapsed|unknown",
  "fidelity_score": 0,
  "navigation_score": 0,
  "style_fit_score": 0,
  "overall_score": 0,
  "hard_fail_reasons": [],
  "warnings": [],
  "suggestions": [],
  "needs_repair": false
}}
"""



