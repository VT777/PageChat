"""Compatibility shim for the renamed page outline extractor.

The TOC architecture no longer uses a visual-first outline module, but older
tests and integrations import this path. Re-export the deterministic page
outline helpers while the rest of the service uses ``page_outline_extractor``.
"""

from pageindex.page_outline_extractor import (  # noqa: F401
    build_page_title_candidates,
    expand_flat_toc_with_page_titles,
    expand_toc_with_page_evidence,
    extract_appendix_title_candidates,
    extract_page_title_candidates,
)

