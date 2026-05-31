"""Document Classifier - Using qwen-turbo for fast classification"""

import asyncio
import json
from typing import Dict, List, Optional, Tuple

from pageindex.classification.cache import ClassificationCache
from app.core.llm import async_chat_completion


CLASSIFICATION_PROMPT = """You are a document classification expert. Analyze the document content and determine its type.

Available types:
- financial_report: Financial reports, annual reports, quarterly reports (characteristics: balance sheet, income statement, cash flow statement, audit report, financial data)
- academic_paper: Academic papers, theses, research articles (characteristics: abstract, keywords, introduction, methodology, results, references)
- legal_contract: Legal contracts, agreements (characteristics: Party A/Party B, clauses, terms and conditions, breach of contract, signatures)
- technical_spec: Technical specifications, standards (characteristics: scope, terminology definitions, technical requirements, specifications)
- general: General documents without obvious professional characteristics

Requirements:
1. If multiple type features are detected, choose the most matching one
2. Mark as "general" if confidence < 0.7
3. Financial reports must meet: has financial statement keywords + substantial content
4. Output language must match the document's primary language

Document content (first 2 pages):
{page_content}

Output JSON format:
{{
    "type": "financial_report|academic_paper|legal_contract|technical_spec|general",
    "confidence": 0.0-1.0,
    "reason": "brief reasoning for classification",
    "key_features": ["detected feature 1", "feature 2"]
}}"""


class DocumentClassifier:
    """Classifies documents using qwen-turbo with caching and retry logic"""

    def __init__(
        self,
        model: str = "qwen-turbo",
        max_retries: int = 5,
        retry_delay: float = 1.0,
        sample_pages: int = 2,
    ):
        self.model = model
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.sample_pages = sample_pages
        self.cache = ClassificationCache(ttl_seconds=600)  # 10 minutes

    async def classify(self, doc_id: str, page_list: List[Tuple[str, int]]) -> Dict:
        """
        Classify document type with caching and retry logic

        Args:
            doc_id: Document ID for caching
            page_list: List of (text, token_count) tuples

        Returns:
            Dict with keys: type, confidence, reason, key_features
        """
        # Check cache first
        cached_result = self.cache.get(doc_id)
        if cached_result:
            print(f"[Classifier] Cache hit for {doc_id}: {cached_result['type']}")
            return cached_result

        # Extract sample text
        sample_text = self._extract_sample(page_list, self.sample_pages)

        # Call LLM with retries
        result = await self._classify_with_retry(sample_text)

        # Cache result
        self.cache.set(doc_id, result)

        print(
            f"[Classifier] Classified {doc_id} as {result['type']} (confidence: {result['confidence']:.2f})"
        )

        return result

    def _extract_sample(self, page_list: List[Tuple[str, int]], num_pages: int) -> str:
        """Extract text sample from first N pages"""
        sample_parts = []
        for i, (text, _) in enumerate(page_list[:num_pages]):
            sample_parts.append(f"=== Page {i + 1} ===\n{text[:2000]}")

        return "\n\n".join(sample_parts)

    async def _classify_with_retry(self, sample_text: str) -> Dict:
        """Call LLM with retry logic"""
        prompt = CLASSIFICATION_PROMPT.format(page_content=sample_text[:4000])

        for attempt in range(self.max_retries):
            try:
                response = await async_chat_completion(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=30,  # Classification should be fast
                )

                # async_chat_completion returns ChatCompletion object
                raw_content = ""
                if hasattr(response, "choices") and response.choices:
                    raw_content = response.choices[0].message.content or ""
                elif isinstance(response, str):
                    raw_content = response

                # Parse JSON response
                result = json.loads(raw_content)

                # Validate response format
                required_keys = ["type", "confidence", "reason"]
                if not all(key in result for key in required_keys):
                    raise ValueError(f"Missing required keys in response: {result}")

                return result

            except json.JSONDecodeError as e:
                print(
                    f"[Classifier] JSON parse error (attempt {attempt + 1}/{self.max_retries}): {e}"
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                else:
                    # Return general type on persistent failure
                    return {
                        "type": "general",
                        "confidence": 0.0,
                        "reason": f"JSON parse error after {self.max_retries} retries: {str(e)}",
                        "key_features": [],
                    }

            except Exception as e:
                print(
                    f"[Classifier] Error (attempt {attempt + 1}/{self.max_retries}): {e}"
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                else:
                    # Return general type on persistent failure
                    return {
                        "type": "general",
                        "confidence": 0.0,
                        "reason": f"Classification failed after {self.max_retries} retries: {str(e)}",
                        "key_features": [],
                    }

        # Should not reach here, but just in case
        return {
            "type": "general",
            "confidence": 0.0,
            "reason": "Unexpected error in classification",
            "key_features": [],
        }
