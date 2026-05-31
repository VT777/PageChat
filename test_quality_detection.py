"""Test the enhanced PDF quality detection."""

import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import glob
from pageindex.pdf_analyzer import analyze_pdf_structure

doc_dir = "D:/projects/page_chat/backend/data/documents"

# Test the problematic file
files = glob.glob(f"{doc_dir}/*097e50d9*")
if files:
    print("=== Testing: 技术应用洞察报告 ===")
    analysis = analyze_pdf_structure(files[0])
    print(f"Text coverage: {analysis['text_coverage']:.2f}")
    print(f"Is image only: {analysis['is_image_only_pdf']}")
    print(f"Is garbled: {analysis['is_garbled_pdf']}")
    print(f"Text pages: {len(analysis['text_pages'])}")
    print(f"Garbled pages: {len(analysis['garbled_pages'])}")
    print(f"Quality: {analysis.get('text_quality', {})}")
    print()

# Test a good file for comparison
files = glob.glob(f"{doc_dir}/*d9b2b5ea*")  # AI眼镜
if files:
    print("=== Testing: AI眼镜报告 (should be high quality) ===")
    analysis = analyze_pdf_structure(files[0])
    print(f"Text coverage: {analysis['text_coverage']:.2f}")
    print(f"Is image only: {analysis['is_image_only_pdf']}")
    print(f"Is garbled: {analysis['is_garbled_pdf']}")
    print(f"Text pages: {len(analysis['text_pages'])}")
    print(f"Garbled pages: {len(analysis['garbled_pages'])}")
    print(f"Quality: {analysis.get('text_quality', {})}")
    print()

# Test 重庆案例集
files = glob.glob(f"{doc_dir}/*8cefa13e*")
if files:
    print("=== Testing: 重庆案例集 (should be visual path) ===")
    analysis = analyze_pdf_structure(files[0])
    print(f"Text coverage: {analysis['text_coverage']:.2f}")
    print(f"Is image only: {analysis['is_image_only_pdf']}")
    print(f"Is garbled: {analysis['is_garbled_pdf']}")
    print(f"Text pages: {len(analysis['text_pages'])}")
    print(f"Garbled pages: {len(analysis['garbled_pages'])}")
    print(f"Quality: {analysis.get('text_quality', {})}")
