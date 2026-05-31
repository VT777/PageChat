"""Quality Validator - Validates generated table of contents"""

import re
from typing import Dict, List, Tuple, Any


class QualityValidator:
    """Validates quality of generated table of contents"""

    def __init__(self):
        pass

    def validate(
        self, toc_result: List[Dict], doc_type: str, page_list: List[Tuple[str, int]]
    ) -> Tuple[float, List[str]]:
        """
        Validate table of contents quality

        Returns:
            (score, issues)
            - score: 0.0-1.0 quality score
            - issues: List of identified issues
        """
        score = 1.0
        issues = []

        # 1. Basic format validation
        if not self._validate_json_format(toc_result):
            return 0.0, ["Invalid JSON format - not a list"]

        # 2. Field completeness validation
        for i, item in enumerate(toc_result):
            missing = self._check_required_fields(item)
            if missing:
                score -= 0.05
                issues.append(f"Item {i}: Missing fields {missing}")

        # 3. Type-specific validation
        if doc_type == "financial_report":
            score, issues = self._validate_financial_report(toc_result, issues, score)
        elif doc_type == "academic_paper":
            score, issues = self._validate_academic_paper(toc_result, issues, score)
        elif doc_type == "legal_contract":
            score, issues = self._validate_legal_contract(toc_result, issues, score)
        elif doc_type == "technical_spec":
            score, issues = self._validate_technical_spec(toc_result, issues, score)

        # 4. Common validation rules
        score, issues = self._validate_common_rules(
            toc_result, page_list, issues, score
        )

        return max(0.0, score), issues

    def _validate_json_format(self, toc_result) -> bool:
        """Check if result is a valid list"""
        return isinstance(toc_result, list)

    def _check_required_fields(self, item: Dict) -> List[str]:
        """Check if item has all required fields"""
        required = ["structure", "title", "physical_index"]
        return [f for f in required if f not in item]

    def _validate_financial_report(
        self, toc: List[Dict], issues: List[str], score: float
    ) -> Tuple[float, List[str]]:
        """Financial report specific validation"""
        titles = [item.get("title", "") for item in toc]
        titles_text = " ".join(titles)

        # Check for required financial keywords
        financial_keywords = [
            "财务",
            "Financial",
            "负债",
            "Balance",
            "利润",
            "Income",
            "现金",
            "Cash",
            "报表",
            "Statement",
        ]
        has_financial = any(kw in titles_text for kw in financial_keywords)

        if not has_financial:
            score -= 0.3
            issues.append("Missing financial statement sections")

        # Check minimum sections
        if len(toc) < 3:
            score -= 0.2
            issues.append(f"Too few sections ({len(toc)}), expected at least 3")

        return score, issues

    def _validate_academic_paper(
        self, toc: List[Dict], issues: List[str], score: float
    ) -> Tuple[float, List[str]]:
        """Academic paper specific validation"""
        titles = [item.get("title", "").lower() for item in toc]
        titles_text = " ".join(titles)

        # Check for required sections
        required_patterns = [
            (r"abstract|摘要", "Abstract/Summary"),
            (r"introduction|引言", "Introduction"),
            (r"conclusion|结论", "Conclusion"),
            (r"references|参考文献|bibliography", "References"),
        ]

        for pattern, name in required_patterns:
            if not re.search(pattern, titles_text):
                score -= 0.1
                issues.append(f"Missing {name} section")

        # Check minimum sections
        if len(toc) < 4:
            score -= 0.2
            issues.append(f"Too few sections ({len(toc)}), expected at least 4")

        return score, issues

    def _validate_legal_contract(
        self, toc: List[Dict], issues: List[str], score: float
    ) -> Tuple[float, List[str]]:
        """Legal contract specific validation"""
        titles = [item.get("title", "") for item in toc]
        titles_text = " ".join(titles)

        # Check for clause numbering patterns
        clause_pattern = r"第[一二三四五六七八九十\d]+条|Article\s*\d+"
        has_clauses = bool(re.search(clause_pattern, titles_text))

        if not has_clauses:
            score -= 0.2
            issues.append("Missing standard clause numbering")

        # Check minimum sections
        if len(toc) < 3:
            score -= 0.2
            issues.append(f"Too few sections ({len(toc)}), expected at least 3")

        return score, issues

    def _validate_technical_spec(
        self, toc: List[Dict], issues: List[str], score: float
    ) -> Tuple[float, List[str]]:
        """Technical specification specific validation"""
        titles_text = " ".join([item.get("title", "") for item in toc])

        # Check for required sections
        required_patterns = [
            (r"范围|scope", "Scope"),
            (r"术语|terms|定义|definitions", "Terms and Definitions"),
        ]

        for pattern, name in required_patterns:
            if not re.search(pattern, titles_text, re.IGNORECASE):
                score -= 0.1
                issues.append(f"Missing {name} section")

        return score, issues

    def _validate_common_rules(
        self,
        toc: List[Dict],
        page_list: List[Tuple[str, int]],
        issues: List[str],
        score: float,
    ) -> Tuple[float, List[str]]:
        """Common validation rules for all document types"""
        max_page = len(page_list)

        # Check physical_index validity
        for i, item in enumerate(toc):
            idx = item.get("physical_index", "")

            # Accept both int and string physical_index forms
            page_num = None
            if isinstance(idx, int):
                page_num = idx
            elif isinstance(idx, str):
                match = re.search(r"physical_index_(\d+)", idx)
                if match:
                    page_num = int(match.group(1))
                else:
                    # Maybe numeric string
                    try:
                        page_num = int(idx)
                    except ValueError:
                        page_num = None

            if page_num is None:
                score -= 0.05
                issues.append(f"Item {i}: Invalid physical_index format: {idx}")
                continue

            if page_num > max_page:
                score -= 0.1
                issues.append(
                    f"Item {i}: Page number {page_num} exceeds total pages {max_page}"
                )

        # Check for empty titles
        for i, item in enumerate(toc):
            title = item.get("title", "").strip()
            if not title:
                score -= 0.05
                issues.append(f"Item {i}: Empty title")

        # Check structure continuity (basic check)
        structures = [item.get("structure", "") for item in toc]
        # Note: Detailed structure validation can be added here

        return score, issues

    def get_quality_level(self, score: float) -> str:
        """Get quality level from score"""
        if score >= 0.8:
            return "excellent"
        elif score >= 0.6:
            return "acceptable"
        else:
            return "poor"
