"""Analyze why process_no_toc returns only 4 items for tech insight report."""

import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import glob, os
from pathlib import Path

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.utils import count_tokens

# Find file
doc_dir = "D:/projects/page_chat/backend/data/documents"
files = glob.glob(f"{doc_dir}/*097e50d9*")
file_path = files[0]

analysis = analyze_pdf_structure(file_path)
page_list = analysis['page_list']

# Simulate what process_no_toc does
page_contents = []
token_lengths = []

for page_index in range(1, 1 + len(page_list)):
    page_text = f"<physical_index_{page_index}>\n{page_list[page_index - 1][0]}\n</physical_index_{page_index}>\n\n"
    page_contents.append(page_text)
    token_lengths.append(count_tokens(page_text, "qwen3.6-flash"))

total_tokens = sum(token_lengths)
print(f"Total tokens: {total_tokens}")
print(f"Max tokens (threshold): 60000")
print(f"Will be split: {total_tokens > 60000}")

if total_tokens <= 60000:
    print(f"\nDocument fits in single group!")
    print(f"Pages: {len(page_list)}")
    print(f"Avg tokens/page: {total_tokens / len(page_list):.0f}")
    
    # Show page structure
    print(f"\nPage structure:")
    for i, (text, length) in enumerate(zip(page_contents, token_lengths)):
        # Extract first heading-like line
        lines = text.strip().split('\n')
        first_heading = ""
        for line in lines[:10]:
            line = line.strip()
            if line and len(line) > 5 and not line.startswith('<') and not line.startswith('http'):
                first_heading = line[:60]
                break
        print(f"  p.{i+1}: {length:4d} tokens | {first_heading}...")

# Show what the prompt looks like
full_text = "".join(page_contents)
print(f"\n\nFull text length: {len(full_text)} chars")
print(f"First 1000 chars of prompt:")
print(full_text[:1000])
print(f"\n...")
print(f"Last 500 chars:")
print(full_text[-500:])

# Check for headings in the text
import re
headings = []
for i, text in enumerate(page_contents):
    page_num = i + 1
    # Look for Chinese chapter headings
    patterns = [
        r'^\s*(第[一二三四五六七八九十]+章|[一二三四五六七八九十]、)\s*(.+)$',
        r'^\s*(\d+[\.．])\s*(.+)$',
        r'^\s*(\d+\.\d+)\s*(.+)$',
    ]
    for line in text.split('\n'):
        line = line.strip()
        for pattern in patterns:
            match = re.match(pattern, line, re.MULTILINE)
            if match and len(line) < 100:
                headings.append((page_num, line))
                break

print(f"\n\nFound {len(headings)} heading-like lines:")
for page, heading in headings[:30]:
    print(f"  p.{page}: {heading}")
