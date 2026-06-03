"""
Post-processing module to fix TOC titles for divider-based documents.

Features:
- Robust divider page detection (no hardcoded text)
- Generic title extraction from divider pages
- VLM fallback for uncertain cases
- Chapter-number-based mapping (not order-based)
"""
import re
import asyncio
import json
from typing import List, Dict, Tuple, Optional


def detect_divider_pages_robust(page_list: List[Tuple[str, int]]) -> List[int]:
    """
    Detect divider/navigation pages using generic heuristics.
    
    Criteria (ALL must be met):
    1. Short page (< 1000 chars) - divider pages are typically brief
    2. Contains multiple numbering items (Chinese numerals as standalone lines or with separators)
    3. List format - most lines are short (<50 chars), indicating list items
    4. Minimum line count - at least 5 lines
    
    Returns list of 1-indexed page numbers.
    """
    divider_pages = []
    
    for i, (text, _) in enumerate(page_list):
        text_stripped = text.strip()
        if not text_stripped:
            continue
        
        # Criterion 1: Short text
        text_length = len(text_stripped)
        if text_length > 1000:
            continue
        
        lines = [line.strip() for line in text_stripped.split('\n') if line.strip()]
        if len(lines) < 5:
            continue
        
        # Criterion 2: Contains multiple Chinese numbering items
        # Pattern A: "一、" or "一 " (with separator)
        chinese_with_sep = re.findall(r'^[一二三四五六七八九十]+[、.．\s]', text_stripped, re.MULTILINE)
        # Pattern B: "一" as standalone line followed by text
        chinese_standalone = 0
        for j, line in enumerate(lines):
            if re.match(r'^[一二三四五六七八九十]+$', line) and j + 1 < len(lines):
                next_line = lines[j + 1]
                if len(next_line) >= 3 and not re.match(r'^[一二三四五六七八九十\d]+$', next_line):
                    chinese_standalone += 1
        
        has_numbering = len(chinese_with_sep) >= 2 or chinese_standalone >= 2
        
        if not has_numbering:
            continue
        
        # Criterion 3: List format - most lines are short (divider pages use short lines)
        short_lines = sum(1 for line in lines if len(line) < 50)
        is_list_format = short_lines / max(len(lines), 1) > 0.6
        
        if not is_list_format:
            continue
        
        # All criteria met
        divider_pages.append(i + 1)  # 1-indexed
    
    return divider_pages


def _extract_titles_from_text(text: str) -> Tuple[List[str], bool, List[str]]:
    """
    Extract chapter titles from a single divider page text.
    
    Handles formats:
    1. Header line + unnumbered title + numbered items
       e.g., "汇报提纲\nAI驱动的第五科研范式\n一\n百花齐放..."
    2. Numbered items only
       e.g., "一\n百花齐放...\n二\n大模型辅助..."
    
    Returns: (titles_list, found_numbered_items, number_labels)
    """
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    if len(lines) < 4:  # Need at least: header + title + number + title
        return [], False, []
    
    titles = []
    number_labels = []  # Track the Chinese numerals for each title
    i = 0
    found_numbered_items = False
    
    # Step 1: Skip very short first line (likely header like "汇报提纲" / "目录")
    # A valid title should be at least 6 characters to be meaningful
    first_line = lines[0]
    if len(first_line) < 6:
        i = 1
    
    # Step 2: Check if current line is an unnumbered title before numbered items
    if i < len(lines):
        current = lines[i]
        if 6 <= len(current) <= 100:
            # Check if subsequent lines contain Chinese numbering
            has_numbering_after = False
            for j in range(i + 1, min(i + 6, len(lines))):
                if re.match(r'^[一二三四五六七八九十]+[、.．\s]?$', lines[j]):
                    has_numbering_after = True
                    break
            
            if has_numbering_after:
                # This is the first chapter title (before numbered items)
                titles.append(current)
                number_labels.append('')  # No number label for unnumbered title
                i += 1
    
    # Step 3: Extract numbered titles
    while i < len(lines):
        line = lines[i]
        
        if len(line) < 1:
            i += 1
            continue
        
        # Pattern 1: "一" or "一、" on separate line, next line is title
        match_num = re.match(r'^([一二三四五六七八九十]+)[、.．\s]?$', line)
        if match_num and i + 1 < len(lines):
            num_label = match_num.group(1)
            title = lines[i + 1].strip()
            if 3 <= len(title) <= 100:
                titles.append(title)
                number_labels.append(num_label)
                found_numbered_items = True
                i += 2
                continue
        
        # Pattern 2: "一、Title" or "一 Title" (same line)
        match = re.match(r'^([一二三四五六七八九十]+)[、.．\s]+(.+)$', line)
        if match:
            num_label = match.group(1)
            title = match.group(2).strip()
            if 3 <= len(title) <= 100:
                titles.append(title)
                number_labels.append(num_label)
                found_numbered_items = True
                i += 1
                continue
        
        i += 1
    
    return titles, found_numbered_items, number_labels


def extract_chapter_titles_from_dividers_robust(
    page_list: List[Tuple[str, int]], 
    divider_pages: List[int]
) -> Tuple[List[str], bool]:
    """
    Extract chapter titles from divider pages using generic patterns.
    
    Tries all detected divider pages and returns the best result.
    
    Returns:
        (titles_list, is_reliable) - list of titles and reliability flag
    """
    if not divider_pages:
        return [], False
    
    # Try all detected divider pages and return the best result
    best_titles = []
    best_reliability = 0
    best_number_labels = []
    
    for page_num in divider_pages:
        divider_idx = page_num - 1
        if divider_idx < 0 or divider_idx >= len(page_list):
            continue
        
        text = page_list[divider_idx][0]
        titles, found_numbered, number_labels = _extract_titles_from_text(text)
        
        # Calculate reliability score
        reliability = 0
        if found_numbered:
            reliability += 2
        if len(titles) >= 2:
            reliability += 2
        if all(3 <= len(t) <= 100 for t in titles):
            reliability += 1
        if len(number_labels) > 1:
            # Check if numbering is sequential (一, 二, 三...)
            chinese_nums = '一二三四五六七八九十'
            expected = ''.join([chinese_nums[j] for j in range(len(number_labels) - 1)])
            actual = ''.join([n for n in number_labels[1:] if n])  # Skip unnumbered first title
            if actual == expected:
                reliability += 2  # Sequential numbering is more reliable
        
        # Keep the best result
        if reliability > best_reliability:
            best_reliability = reliability
            best_titles = titles
            best_number_labels = number_labels
        
        # If we found a very good result, stop searching
        if reliability >= 5 and len(titles) >= 3:
            break
    
    # Check if numbering is sequential
    is_sequential = False
    if len(best_number_labels) > 1:
        chinese_nums = '一二三四五六七八九十'
        numbered_labels = [n for n in best_number_labels if n]  # Remove empty (unnumbered)
        if len(numbered_labels) >= 2:
            expected = [chinese_nums[j] for j in range(len(numbered_labels))]
            is_sequential = (numbered_labels == expected)
    
    is_reliable = (
        best_reliability >= 4 and
        len(best_titles) >= 2 and
        is_sequential  # Must have sequential numbering to be reliable
    )
    
    return best_titles, is_reliable


def map_titles_to_chapters(
    chapter_titles: List[str],
    toc_items: List[Dict]
) -> Dict[int, str]:
    """
    Map extracted titles to TOC chapters by chapter number.
    
    Returns: {chapter_number: title}
    """
    main_chapters = [
        item for item in toc_items
        if '.' not in str(item.get('structure', ''))
    ]
    
    mapping = {}
    for i, title in enumerate(chapter_titles):
        chapter_num = i + 1
        if chapter_num <= len(main_chapters):
            mapping[chapter_num] = title
    
    return mapping


def apply_title_mapping(
    toc_items: List[Dict],
    title_mapping: Dict[int, str]
) -> List[Dict]:
    """
    Apply title mapping to TOC items.
    """
    for item in toc_items:
        struct = str(item.get('structure', ''))
        if '.' not in struct:  # Main chapter
            try:
                chapter_num = int(struct)
                if chapter_num in title_mapping:
                    old_title = item.get('title', '')
                    new_title = title_mapping[chapter_num]
                    if old_title != new_title:
                        print(f"[DIVIDER-FIX] Chapter {chapter_num}: '{old_title}' -> '{new_title}'")
                        item['title'] = new_title
            except ValueError:
                pass
    
    return toc_items


async def vlm_detect_divider(
    pdf_path: str,
    page_num: int,
    model: str = "qwen3.6-flash"
) -> bool:
    """
    Use VLM to detect if a page is a divider/outline page.
    
    Returns True if the page is a divider page.
    """
    try:
        from app.core.llm import pdf_page_to_base64, build_vision_message, async_chat_completion
        
        img_b64 = pdf_page_to_base64(pdf_path, page_num)
        if not img_b64:
            return False
        
        messages = build_vision_message(
            "Is this page a divider/outline/navigation page that lists chapter or section titles? "
            "Reply with only 'yes' or 'no'.",
            [img_b64]
        )
        
        response = await async_chat_completion(
            messages=messages,
            model=model,
            temperature=0,
            max_tokens=10
        )
        
        answer = response.choices[0].message.content.strip().lower()
        is_divider = 'yes' in answer
        
        print(f"[VLM] Page {page_num} divider detection: {answer} -> {is_divider}")
        return is_divider
        
    except Exception as e:
        print(f"[VLM] Error detecting divider for page {page_num}: {e}")
        return False


async def vlm_extract_titles(
    pdf_path: str,
    page_num: int,
    model: str = "qwen3.6-flash"
) -> List[str]:
    """
    Use VLM to extract chapter titles from a divider page.
    
    Returns list of chapter titles.
    """
    try:
        from app.core.llm import pdf_page_to_base64, build_vision_message, async_chat_completion
        
        img_b64 = pdf_page_to_base64(pdf_path, page_num)
        if not img_b64:
            return []
        
        messages = build_vision_message(
            "Extract all chapter/section titles from this outline/divider page. "
            "Return ONLY a JSON array of strings, like [\"Title 1\", \"Title 2\"]. "
            "If the first item before numbered items is a title, include it too.",
            [img_b64]
        )
        
        response = await async_chat_completion(
            messages=messages,
            model=model,
            temperature=0,
            max_tokens=500
        )
        
        content = response.choices[0].message.content.strip()
        
        # Extract JSON array
        start = content.find('[')
        end = content.rfind(']')
        if start != -1 and end != -1 and end > start:
            try:
                titles = json.loads(content[start:end+1])
                if isinstance(titles, list) and all(isinstance(t, str) for t in titles):
                    print(f"[VLM] Extracted {len(titles)} titles from page {page_num}: {titles}")
                    return titles
            except json.JSONDecodeError:
                pass
        
        # Fallback: parse line by line
        titles = [line.strip() for line in content.split('\n') if line.strip() and len(line.strip()) > 2]
        print(f"[VLM] Fallback extracted {len(titles)} titles from page {page_num}")
        return titles
        
    except Exception as e:
        print(f"[VLM] Error extracting titles from page {page_num}: {e}")
        return []


async def fix_toc_for_dividers(
    toc_items: List[Dict],
    page_list: List[Tuple[str, int]],
    pdf_path: Optional[str] = None,
    use_vlm: bool = True,
    vlm_model: str = "qwen3.6-flash"
) -> List[Dict]:
    """
    Fix TOC items for documents with divider pages.
    
    Strategy:
    1. Try text-based detection and extraction first (fast)
    2. If unreliable or uncertain, use VLM fallback
    3. Map titles to chapters by chapter number
    """
    # Step 1: Text-based detection
    divider_pages = detect_divider_pages_robust(page_list)
    
    if not divider_pages:
        print("[DIVIDER-FIX] No divider pages detected via text")
        return toc_items
    
    print(f"[DIVIDER-FIX] Detected {len(divider_pages)} potential divider pages: {divider_pages}")
    
    # Step 2: Text-based extraction
    chapter_titles, is_reliable = extract_chapter_titles_from_dividers_robust(
        page_list, divider_pages
    )
    
    print(f"[DIVIDER-FIX] Text extraction: {len(chapter_titles)} titles, reliable={is_reliable}")
    for i, title in enumerate(chapter_titles, 1):
        print(f"  Chapter {i}: '{title}'")
    
    # Step 3: VLM fallback if needed
    if use_vlm and pdf_path and (not is_reliable or not chapter_titles):
        print("[DIVIDER-FIX] Using VLM fallback for divider detection")
        
        # Validate divider pages with VLM
        confirmed_dividers = []
        for page_num in divider_pages[:3]:  # Check first 3 at most
            is_divider = await vlm_detect_divider(pdf_path, page_num, vlm_model)
            if is_divider:
                confirmed_dividers.append(page_num)
        
        if confirmed_dividers:
            # Extract titles from first confirmed divider using VLM
            vlm_titles = await vlm_extract_titles(pdf_path, confirmed_dividers[0], vlm_model)
            if vlm_titles:
                chapter_titles = vlm_titles
                is_reliable = True
                print(f"[DIVIDER-FIX] VLM extracted {len(chapter_titles)} titles")
    
    # Step 4: Apply mapping if we have titles
    if chapter_titles:
        title_mapping = map_titles_to_chapters(chapter_titles, toc_items)
        if title_mapping:
            toc_items = apply_title_mapping(toc_items, title_mapping)
            print(f"[DIVIDER-FIX] Applied mapping for {len(title_mapping)} chapters")
        else:
            print("[DIVIDER-FIX] Warning: Could not map titles to chapters")
    else:
        print("[DIVIDER-FIX] No titles extracted, skipping fix")
    
    return toc_items


# Backward compatibility: synchronous wrapper for non-async callers
def fix_toc_for_dividers_sync(
    toc_items: List[Dict],
    page_list: List[Tuple[str, int]],
    pdf_path: Optional[str] = None,
    use_vlm: bool = True,
    vlm_model: str = "qwen3.6-flash"
) -> List[Dict]:
    """Synchronous wrapper for fix_toc_for_dividers."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an async context, create a new loop
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(
                fix_toc_for_dividers(toc_items, page_list, pdf_path, use_vlm, vlm_model)
            )
        else:
            return loop.run_until_complete(
                fix_toc_for_dividers(toc_items, page_list, pdf_path, use_vlm, vlm_model)
            )
    except RuntimeError:
        # No event loop, create one
        return asyncio.run(
            fix_toc_for_dividers(toc_items, page_list, pdf_path, use_vlm, vlm_model)
        )
