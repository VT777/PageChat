"""
Enhancement Hooks for PageIndex

Provides multimodal enhancement capabilities at key points in the official PageIndex pipeline.
This is a hook-based architecture that allows injecting visual/VLM capabilities without
modifying the core official logic.

Usage:
    hooks = MultimodalEnhancementHooks()
    result = await tree_parser(page_list, opt, hooks=hooks)

Each hook receives the official result and can:
1. Return enhanced result (replaces official)
2. Return None (keeps official result)
"""

from typing import List, Dict, Any, Optional, Tuple
from abc import ABC, abstractmethod


class EnhancementHooks(ABC):
    """Base class for enhancement hooks.
    
    Inherit from this class and override the hooks you want to enhance.
    Each hook should return either:
    - Enhanced result (dict/list) - replaces official result
    - None - keeps official result
    """
    
    async def on_check_toc(
        self, 
        page_list: List[Tuple[str, int]], 
        check_toc_result: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Hook called after official TOC detection.
        
        Enhances TOC detection when text-based scanning misses unusual TOC formats.
        E.g., detects "hui bao ti gang" style dividers that text scan misses.
        
        Args:
            page_list: List of (text, token_count) tuples
            check_toc_result: Official TOC detection result
            
        Returns:
            Enhanced TOC result or None to keep official result
        """
        return None
    
    async def on_toc_extracted(
        self, 
        toc_items: List[Dict[str, Any]], 
        page_list: List[Tuple[str, int]]
    ) -> Optional[List[Dict[str, Any]]:
        """Hook called after TOC extraction.
        
        Enhances TOC extraction when official extraction has errors.
        E.g., fixes wrong page numbers (ENIAC -> p.1945) or missing items.
        
        Args:
            toc_items: List of extracted TOC items
            page_list: List of (text, token_count) tuples
            
        Returns:
            Enhanced TOC items or None to keep official result
        """
        return None
    
    async def on_offset_calculated(
        self, 
        offset: int, 
        toc_items: List[Dict[str, Any]], 
        page_list: List[Tuple[str, int]]
    ) -> Optional[int]:
        """Hook called after page offset calculation.
        
        Validates and corrects page offset when text matching fails.
        E.g., recalculates offset using visual page numbers.
        
        Args:
            offset: Calculated page offset
            toc_items: List of TOC items with physical_index
            page_list: List of (text, token_count) tuples
            
        Returns:
            Corrected offset or None to keep official result
        """
        return None
    
    async def on_structure_generated(
        self, 
        structure: List[Dict[str, Any]], 
        page_list: List[Tuple[str, int]],
        analysis_info: Dict[str, Any]
    ) -> Optional[List[Dict[str, Any]]:
        """Hook called after structure generation (process_no_toc mode).
        
        MOST IMPORTANT HOOK.
        Enhances structure generation when document has visual dividers.
        E.g., analyzes "hui bao ti gang" pages to create correct chapter structure.
        
        Args:
            structure: Generated structure list
            page_list: List of (text, token_count) tuples
            analysis_info: Document analysis info (contains chapter_dividers, etc.)
            
        Returns:
            Enhanced structure or None to keep official result
        """
        return None
    
    async def on_verify(
        self, 
        accuracy: float, 
        incorrect_items: List[Dict[str, Any]], 
        page_list: List[Tuple[str, int]]
    ) -> Optional[Tuple[float, List[Dict[str, Any]]]]:
        """Hook called after TOC verification.
        
        Enhances verification when text-based verification fails.
        E.g., uses visual verification instead of text matching for low quality docs.
        
        Args:
            accuracy: Verification accuracy (0.0-1.0)
            incorrect_items: List of incorrectly verified items
            page_list: List of (text, token_count) tuples
            
        Returns:
            Tuple of (enhanced_accuracy, enhanced_incorrect_items) or None
        """
        return None
    
    async def on_fix_incorrect(
        self, 
        incorrect_items: List[Dict[str, Any]], 
        page_list: List[Tuple[str, int]], 
        neighbor_range: Optional[Tuple[int, int]] = None
    ) -> Optional[List[Dict[str, Any]]:
        """Hook called before fixing incorrect TOC items.
        
        Enhances error correction when neighbor-bounded search fails.
        E.g., uses visual search to locate correct page numbers.
        
        Args:
            incorrect_items: List of items needing correction
            page_list: List of (text, token_count) tuples
            neighbor_range: (start_page, end_page) for neighbor search
            
        Returns:
            Corrected items or None to use official fix
        """
        return None


class MultimodalEnhancementHooks(EnhancementHooks):
    """Default implementation of enhancement hooks using VLM.
    
    Provides visual/multimodal capabilities to enhance official pipeline.
    """
    
    def __init__(self, vlm_model: Optional[str] = None, enable_hooks: Optional[List[str]] = None):
        """Initialize multimodal enhancement hooks.
        
        Args:
            vlm_model: VLM model name for visual tasks
            enable_hooks: List of hook names to enable. If None, enables all.
        """
        self.vlm_model = vlm_model or "qwen-vl-max"
        self.enable_hooks = set(enable_hooks) if enable_hooks else None
    
    def _is_enabled(self, hook_name: str) -> bool:
        """Check if a hook is enabled."""
        if self.enable_hooks is None:
            return True
        return hook_name in self.enable_hooks
    
    async def on_check_toc(self, page_list, check_toc_result):
        """Enhance TOC detection using text-based divider detection.
        
        When official text scanning misses TOC, check for divider pages
        which may serve as implicit TOC.
        """
        if not self._is_enabled('on_check_toc'):
            return None
        
        # If official already found TOC, no need to enhance
        if check_toc_result.get('toc_content') and check_toc_result['toc_content'].strip():
            return None
        
        # Check for divider pages in first 20 pages
        import re
        from collections import defaultdict
        
        fingerprint_pages = defaultdict(list)
        for i in range(min(20, len(page_list))):
            text = page_list[i][0].strip()
            text_len = len(text)
            
            # Skip empty and long pages
            if text_len == 0 or text_len > 300:
                continue
            
            # Extract fingerprint (remove spaces, numbers, punctuation)
            fp = re.sub(r'[^\u4e00-\u9fa5a-zA-Z]', '', text[:100])
            if len(fp) >= 20:
                fingerprint_pages[fp].append(i + 1)
        
        # Find repeated fingerprints (potential dividers)
        divider_pages = []
        for fp, pages in fingerprint_pages.items():
            if len(pages) >= 3:
                pages_sorted = sorted(pages)
                if len(pages_sorted) >= 2:
                    gaps = [pages_sorted[j+1] - pages_sorted[j] for j in range(len(pages_sorted)-1)]
                    max_gap = max(gaps) if gaps else 0
                    if max_gap >= 5:
                        divider_pages.extend(pages_sorted)
        
        if divider_pages:
            print(f"[HOOK] Detected {len(divider_pages)} divider pages as implicit TOC: {sorted(set(divider_pages))}")
            # Return a pseudo-TOC result to trigger process_no_toc with divider analysis
            return {
                "toc_content": "",
                "toc_page_list": [],
                "page_index_given_in_toc": "no",
                "has_dividers": True,
                "divider_pages": sorted(set(divider_pages))
            }
        
        return None
    
    async def on_toc_extracted(self, toc_items, page_list):
        """Enhance TOC extraction by validating page numbers."""
        if not self._is_enabled('on_toc_extracted'):
            return None
        
        if not toc_items:
            return None
        
        # Check for obvious errors
        has_errors = False
        for item in toc_items:
            page = item.get('physical_index', 0)
            if page > len(page_list) + 100 or page < 1:
                has_errors = True
                break
        
        if not has_errors:
            return None
        
        # TODO: Use VLM to re-extract TOC from TOC pages
        # 1. Render TOC pages as images
        # 2. Ask VLM to read TOC with correct page numbers
        # 3. Return corrected items
        
        return None
    
    async def on_structure_generated(self, structure, page_list, analysis_info):
        """Enhance structure generation using divider analysis.
        
        This is the most important hook for handling divider-based documents
        like the 5th Paradigm report with "hui bao ti gang" pages.
        """
        if not self._is_enabled('on_structure_generated'):
            return None
        
        # Check if document has chapter dividers
        chapter_dividers = analysis_info.get('chapter_dividers', [])
        if not chapter_dividers:
            return None
        
        print(f"[HOOK] Enhancing structure with {len(chapter_dividers)} dividers: {chapter_dividers}")
        
        # Build structure from dividers
        enhanced_structure = self._build_structure_from_dividers(
            chapter_dividers, page_list
        )
        
        if enhanced_structure:
            print(f"[HOOK] Built structure from dividers: {len(enhanced_structure)} chapters")
            return enhanced_structure
        
        return None
    
    def _build_structure_from_dividers(self, dividers, page_list):
        """Build chapter structure from detected divider pages.
        
        Args:
            dividers: List of divider page numbers (1-indexed)
            page_list: List of (text, token_count) tuples
            
        Returns:
            List of structure items with physical_index
        """
        if not dividers:
            return None
        
        structure = []
        total_pages = len(page_list)
        
        # Group consecutive dividers (e.g., [2, 3] -> one chapter start at 2)
        grouped_dividers = []
        current_group = [dividers[0]]
        
        for i in range(1, len(dividers)):
            if dividers[i] == dividers[i-1] + 1:
                # Consecutive page, add to current group
                current_group.append(dividers[i])
            else:
                # Non-consecutive, start new group
                grouped_dividers.append(current_group)
                current_group = [dividers[i]]
        grouped_dividers.append(current_group)
        
        print(f"[HOOK] Grouped dividers: {grouped_dividers}")
        
        # Build structure from grouped dividers
        for i, group in enumerate(grouped_dividers):
            start_page = group[0]
            
            # Determine end page (next divider group or end of document)
            if i + 1 < len(grouped_dividers):
                end_page = grouped_dividers[i + 1][0]
            else:
                end_page = total_pages + 1  # End of document
            
            # Extract chapter title from divider page text
            divider_text = page_list[start_page - 1][0] if start_page <= total_pages else ""
            title = self._extract_chapter_title(divider_text, i + 1)
            
            structure.append({
                "title": title,
                "physical_index": start_page,
                "level": 1,
                "page_range": (start_page, end_page - 1)
            })
        
        return structure
    
    def _extract_chapter_title(self, text, chapter_num):
        """Extract chapter title from divider page text.
        
        Args:
            text: Divider page text content
            chapter_num: Chapter number for fallback
            
        Returns:
            Extracted or generated chapter title
        """
        import re
        
        if not text:
            return f"Chapter {chapter_num}"
        
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # Strategy 1: Look for Chinese chapter markers
        for line in lines[:5]:  # Check first 5 lines
            # Match: 一、Title, 1.1 Title, 第一章 Title
            match = re.match(r'^[一二三四五六七八九十百]+[、.\s]+(.+)$', line)
            if match:
                return match.group(1).strip()
            
            match = re.match(r'^第[一二三四五六七八九十\d]+[章节]\s*(.+)$', line)
            if match:
                return match.group(1).strip()
        
        # Strategy 2: Look for the longest meaningful line (likely the title)
        meaningful_lines = [line for line in lines if len(line) > 5 and len(line) < 100]
        if meaningful_lines:
            # Return the second line (first is often "目录" or "汇报提纲")
            if len(meaningful_lines) >= 2:
                return meaningful_lines[1]
            return meaningful_lines[0]
        
        # Strategy 3: Fallback to generic chapter name
        return f"Chapter {chapter_num}"
    
    async def on_verify(self, accuracy, incorrect_items, page_list):
        """Enhance verification using text-based fuzzy matching.
        
        When official text verification fails (due to text extraction errors),
        use more lenient matching to reduce false negatives.
        """
        if not self._is_enabled('on_verify'):
            return None
        
        # Only enhance if verification failed
        if accuracy >= 0.8:
            return None
        
        print(f"[HOOK] Enhancing verification (accuracy: {accuracy:.2%})")
        
        # Re-verify with fuzzy matching
        import re
        corrected_items = []
        
        for item in incorrect_items:
            title = item.get('title', '')
            page_num = item.get('physical_index', 0)
            
            if page_num < 1 or page_num > len(page_list):
                corrected_items.append(item)
                continue
            
            page_text = page_list[page_num - 1][0]
            
            # Normalize title and text for matching
            def normalize(s):
                return re.sub(r'[\s\d\.，,；;：:!！?？""''（）()]', '', s).lower()
            
            norm_title = normalize(title)
            norm_text = normalize(page_text[:500])  # Check first 500 chars
            
            # Fuzzy match: title should appear in text (even partially)
            if norm_title and (norm_title in norm_text or 
                              any(part in norm_text for part in norm_title.split() if len(part) >= 3)):
                # Title found with fuzzy matching - mark as correct
                print(f"[HOOK] Fuzzy match found for '{title}' on page {page_num}")
                continue  # Skip adding to corrected_items (it's actually correct)
            else:
                corrected_items.append(item)
        
        # Recalculate accuracy
        total_items = len(incorrect_items)  # Approximate
        if total_items > 0:
            corrected_accuracy = 1.0 - (len(corrected_items) / total_items)
        else:
            corrected_accuracy = accuracy
        
        print(f"[HOOK] Verification enhanced: {accuracy:.2%} -> {corrected_accuracy:.2%}")
        
        if corrected_accuracy > accuracy:
            return (corrected_accuracy, corrected_items)
        
        return None
    
    async def on_fix_incorrect(self, incorrect_items, page_list, neighbor_range=None):
        """Enhance error correction using visual search."""
        if not self._is_enabled('on_fix_incorrect'):
            return None
        
        if not incorrect_items:
            return None
        
        print(f"[HOOK] Enhancing fix for {len(incorrect_items)} incorrect items")
        
        # TODO: Implement visual error correction
        # 1. For each incorrect item, search visually in neighbor range
        # 2. Use VLM to locate correct page
        # 3. Return corrected items
        
        return None


class NoOpEnhancementHooks(EnhancementHooks):
    """No-op implementation that always returns None.
    
    Used when no enhancement is needed. Equivalent to not passing hooks.
    """
    pass
