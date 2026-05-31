"""Prompt templates used by PageIndex runtime paths."""

CHECK_TITLE_APPEARANCE_PROMPT = """
You will be given a section title and one page text.
Judge whether this section appears or starts on this page.

Rules:
1) Use fuzzy matching for spacing and punctuation.
2) Ignore image markdown like ![](...), decorative separators, and empty lines.
3) Return "yes" only if the section title is clearly present on this page.

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

TOC_DETECTOR_SINGLE_PROMPT = """
Your task is to detect whether the given page is a table-of-contents page.

Given text:
{content}

Reply JSON only:
{{
  "thinking": "brief reason",
  "toc_detected": "yes|no"
}}
"""

TOC_DETECTOR_BATCH_PROMPT = """Analyze the following pages and determine which ones are table-of-contents (TOC) pages.

A TOC page typically contains:
- A list of chapter/section titles with corresponding page numbers
- Structured listing of document contents
- Navigation structure of the document

Pages content:
{pages_content}

Reply in JSON format only (no markdown code fences):
{{
  "reasoning": "Brief explanation of which pages look like TOC",
  "toc_pages": [list of page indices that are TOC pages],
  "pages_with_toc": [same list, alternative key]
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
3) Reject chapter/section numbering used as labels (e.g., "落地01", "Part 2", "Chapter 3") — these are NOT page numbers
4) Reject if numbers only appear as part of section titles, not as page references
5) For Chinese documents: "01", "02" after section titles (like "国外大厂AI应用落地01") are typically section labels, NOT page numbers

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

NODE_SUMMARY_PROMPT = """生成章节摘要（50-100字）。

章节标题: {node_title}
章节内容: {node_text}

要求：
1. 列出该章节涉及的所有关键主题和子话题，不要只提第一个
2. 包含关键实体（公司名、产品名、人名、数字等）
3. 禁止编造内容中没有的信息
4. 如果章节涵盖多个公司/产品，必须全部提及

返回："摘要文本"""

DOC_DESCRIPTION_PROMPT = """生成文档的一句话描述。

文档结构: {structure_summary}

要求：
1. 一句话概括整个文档的主题和范围
2. 包含关键实体
3. 不超过50字

返回："一句话描述"""

FAST_DOC_LIGHT_SUMMARY_PROMPT = """你是文档摘要助手。请仅根据目录结构生成文档概述。

文档名: {doc_name}
文件类型: {file_type}
目录结构:
{toc_outline}

要求：
1) 只能依据目录标题概述，不得补充目录中没有的事实。
2) 输出 1-2 句话，总长度 40-90 字。
3) 语气客观中性，使用中文。
4) 若目录信息不足以概述，返回空字符串。

直接输出摘要文本，不要输出 JSON，不要解释。"""

QUERY_VERIFICATION_PROMPT = """验证查询是否在内容中有答案。

查询: {query}
内容片段: {content}

返回JSON：
{{
  "query_appears": "yes|partial|no",
  "confidence": 0.0-1.0,
  "reasoning": "简要理由"
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

TOC_LIGHT_VALIDATION_PROMPT = """你是文档结构审查专家。以下是从 PDF 中自动提取的目录结构。
这是用户打开文件后首先看到的内容，必须能完整概述整份文档。

文档总页数: {page_count}
提取的目录（共 {toc_count} 个条目）:
{toc_outline}

内容匹配检查结果:
- 抽样验证匹配率: {match_rate:.0%}
- 偏移量中位数: {offset_median:+d} 页
- 不匹配条目: {mismatch_details}

判断标准：
1) 覆盖度：目录的页码范围是否覆盖了文档大部分页面？最后一个条目的页码应接近总页数。
   如果最后一个条目的页码远小于总页数（如85页文档目录只到49页），说明目录不完整。
2) 内容匹配：目录条目标题是否出现在对应页面上？匹配率应 >= 60%。
   如果匹配率很低，说明提取的页码与实际内容严重不符。
3) 偏移一致性：如果存在偏移，偏移量应一致（所有条目偏移相近），说明是系统性偏移。
4) 结构性：是否有清晰的章节层级（至少 2 个以上的一级标题）？
5) 合理性：标题是否像真实的文档章节（而非页眉页脚、图片说明等噪音）？
   如果大量条目是"图片目录"、"图表汇总"、文档标题本身等，说明提取质量差。

回答 JSON（不要 markdown code fence）:
{{"valid": "yes|no", "reason": "简要说明"}}"""

# ---------------------------------------------------------------------------
# VLM 提示词 v3（balanced 视觉模式用）
# ---------------------------------------------------------------------------

VLM_ANCHOR_DETECTION_PROMPT = """你是文档分析专家。这些是一份 PDF 文档所有页面的缩略图网格。
每个缩略图左上角标注了页码（如 p.1, p.2...）。

请识别以下两类特殊页面：

1. 目录页（Table of Contents）：页面上有结构化的章节标题列表，通常有"目录"或"CONTENTS"字样
2. 章节分隔页（Chapter Divider）：整页是一个大标题，通常有色块背景，正文文字很少

另外，请判断第一个章节内容（非封面、非目录、非前言）实际从哪一页开始。

回答 JSON（不要 markdown code fence）:
{{
  "toc_pages": [4],
  "chapter_dividers": [5, 13, 25, 35, 41],
  "first_content_page": 5
}}

如果没有找到目录页或分隔页，对应数组返回空 []。"""

VLM_TOC_EXTRACT_PROMPT = """你是文档转录助手。这些是 PDF 的目录页图片。

{page_annotations}

注意：目录可能跨多页。请从所有标注为"目录页"的图片中，按从上到下的顺序，转录**每一条**目录。

对每条目录输出：
- number: 该条目在目录上印的编号原样（如 "1", "1.1", "一", "（一）"）。完全没有编号则为空字符串 ""
- title: 条目标题原文（去掉末尾页码和点线）
- page: 目录上标注的页码数字（整数）。没有标注页码则为 null

重要：
- 请转录**所有条目**，包括缩进/字号较小的子条目，不要跳过任何一行
- 不需要判断层级——你只负责转录
- 不需要计算页码偏移

回答 JSON 数组（不要 markdown code fence）:
{{
  "toc_items": [
    {{"number": "1", "title": "市场概述", "page": 6}},
    {{"number": "1.1", "title": "消费趋势", "page": 7}},
    {{"number": "", "title": "结语", "page": 59}}
  ],
  "is_toc_complete": "yes|no"
}}
"""

VLM_TOC_EXTRACT_WITH_OFFSET_PROMPT = """你是文档分析专家。这些是 PDF 文档的连续页面高清图。

{page_annotations}

注意：目录页可能跨多页（例如左页和右页各有一部分目录）。请从所有标注为"目录页"的图片中提取条目，不要遗漏任何一页上的目录内容。

任务 1：提取目录页上的所有章节条目
- structure: 层级编号（"1", "1.1", "1.2", "2"...）。如果目录本身没有层级编号，请按顺序分配 "1", "2", "3"...
- title: 章节标题（原文，去掉页码和点线）
- page: 目录上标注的页码数字（整数）。如果没有标注页码，设为 null

任务 2：确定页码偏移（offset）
观察目录后面的正文页，找到第一个章节内容实际开始的物理页码。
offset = 该物理页码 - 目录中第一个条目的 page 值

任务 3：判断目录是否在最后一页还有延续
如果最后一页底部的内容看起来没有结束（还有更多章节），返回 is_toc_complete: "no"

回答 JSON（不要 markdown code fence）:
{{
  "toc_items": [
    {{"structure": "1", "title": "第一章 概述", "page": 1}},
    {{"structure": "1.1", "title": "背景", "page": 3}}
  ],
  "offset": 5,
  "is_toc_complete": "yes|no"
}}

如果目录上没有页码数字（page 全为 null），offset 设为 0。"""

VLM_TOC_CONTINUE_PROMPT = """你是文档分析专家。这些是目录的后续页面。

之前已经提取的目录条目（最后几个）：
{previous_items}

请继续提取这些页面中的目录条目。如果这些页面不再是目录页，返回空列表。
保持 structure 编号的连续性。

回答 JSON（不要 markdown code fence）:
{{
  "toc_items": [
    {{"structure": "3.1", "title": "...", "page": 25}}
  ],
  "is_toc_complete": "yes|no"
}}"""

VLM_FULLTEXT_SECTION_PROMPT = """你是文档分析专家。看这些连续的 PDF 页面图片（第 {start_page} 页到第 {end_page} 页），
识别出所有章节标题和它们开始的页码。

要求：
- 识别所有层级的标题（章、节、小节）
- physical_index 是图片对应的实际页码：第一张图片是第 {start_page} 页
- 只提取这些页面中能看到的新标题
- 忽略页眉页脚中的重复标题
{previous_context}
回答 JSON 数组（不要 markdown code fence）:
[
  {{"structure": "1", "title": "章节标题", "physical_index": {start_page}}},
  {{"structure": "1.1", "title": "子节标题", "physical_index": {start_page_plus1}}}
]

如果这些页面中没有新的章节标题，返回空数组 []"""

VLM_TOPIC_BOUNDARY_PROMPT = """你是文档分析专家。这些是一份 PDF 文档的缩略图网格。
这份文档没有明显的目录页或章节分隔页。

请观察页面内容的变化，识别文档中主题切换的大致位置。
例如：前面几页在讲市场分析，某一页突然开始讲技术方案，那就是一个切换点。

不需要精确的章节标题，只需找到"内容发生明显变化"的页码。

回答 JSON（不要 markdown code fence）:
{{
  "topic_boundaries": [1, 11, 25, 40],
  "estimated_sections": 4,
  "reasoning": "简要说明为什么在这些位置切换"
}}"""

VLM_FIX_ITEM_PROMPT = """你是文档分析专家。我需要你确认一个章节标题在文档中的准确位置。

章节标题: "{title}"

这些图片是该标题可能出现的页面范围（第 {start_page} 页到第 {end_page} 页）。
请找到这个标题的实际内容开始的页码。

注意：
- 目录页上列出的标题不算，要找实际内容开始的位置
- 返回的是图片对应的实际页码

回答 JSON（不要 markdown code fence）:
{{"physical_index": N, "confidence": "high|medium|low"}}

如果在这些页面中找不到该标题的内容：
{{"physical_index": null, "confidence": "low"}}"""

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

TOC_QUALITY_CHECK_PROMPT = """你是文档结构分析专家。请评估以下文档目录（TOC）的质量。

文档信息：
- 总页数: {page_count}
- 目录来源: {source}
- 是否有章节分隔页: {has_dividers}
- 章节分隔页数量: {divider_count}

目录结构（按层级）：
{toc_tree_formatted}

请从以下维度评估并返回 JSON：

1. 结构合理性 (structure_score: 0-100)
   - 章节数量是否和文档长度匹配（通常每 5-15 页一个章节）
   - 是否存在过于扁平的结构（如 43 页文档有 9 个顶级节点）
   - 层级是否清晰（是否有过多的同级节点）

2. 大节点检测 (large_nodes: list)
   - 检查是否有 span > 8 页的节点但没有子节点
   - 如果有，标记为 "missing_children"

3. 遗漏检测 (missing_chapters: list)
   - 检查页码是否连续（不应该有大段空白）
   - 检查是否有明显的章节遗漏

4. 整体评分 (overall_score: 0-100)
   - 综合以上维度

5. 修复建议 (suggestions: list)
   - 如果发现问题，给出具体建议

返回格式（严格 JSON，不要 markdown）：
{{
  "structure_score": 85,
  "large_nodes": [
    {{"title": "章节标题", "span": 12, "issue": "missing_children"}}
  ],
  "missing_chapters": [],
  "overall_score": 75,
  "suggestions": [
    "建议对 span > 8 页的章节进行子章节提取"
  ],
  "needs_repair": true
}}"""
