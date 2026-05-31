"""Analyze actual text content to understand why only 4 items are extracted."""

import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import glob, os
from pageindex.pdf_analyzer import analyze_pdf_structure

# Find file
doc_dir = "D:/projects/page_chat/backend/data/documents"
files = glob.glob(f"{doc_dir}/*097e50d9*")
file_path = files[0]

analysis = analyze_pdf_structure(file_path)
page_list = analysis['page_list']

print("=== PAGE CONTENT ANALYSIS ===\n")

# Show content around chapter pages
chapter_pages = [4, 11, 24, 38]
for page_num in chapter_pages:
    text = page_list[page_num-1][0]
    print(f"--- Page {page_num} (first 500 chars) ---")
    # Try to print safely
    try:
        print(text[:500])
    except:
        print(repr(text[:500]))
    print()

# Check pages between chapters for sub-headings
print("=== CHECKING FOR SUB-HEADINGS BETWEEN CHAPTERS ===\n")

# Page 5-10 (Chapter 1 content)
print("--- Pages 5-10 (Chapter 1) ---")
for i in range(4, 10):
    text = page_list[i][0]
    lines = text.split('\n')
    for line in lines[:5]:
        line = line.strip()
        if line and len(line) < 100 and not line.startswith('http'):
            try:
                print(f"  p.{i+1}: {line}")
            except:
                print(f"  p.{i+1}: {repr(line)}")
            break

# Page 12-23 (Chapter 2 content)
print("\n--- Pages 12-23 (Chapter 2) ---")
for i in range(11, 23):
    text = page_list[i][0]
    lines = text.split('\n')
    for line in lines[:5]:
        line = line.strip()
        if line and len(line) < 100 and not line.startswith('http'):
            try:
                print(f"  p.{i+1}: {line}")
            except:
                print(f"  p.{i+1}: {repr(line)}")
            break

# Page 25-37 (Chapter 3 content)
print("\n--- Pages 25-37 (Chapter 3) ---")
for i in range(24, 37):
    text = page_list[i][0]
    lines = text.split('\n')
    for line in lines[:5]:
        line = line.strip()
        if line and len(line) < 100 and not line.startswith('http'):
            try:
                print(f"  p.{i+1}: {line}")
            except:
                print(f"  p.{i+1}: {repr(line)}")
            break

# Check if there are any numbered sections
print("\n\n=== SEARCHING FOR NUMBERED SECTIONS ===")
import re
for i in range(len(page_list)):
    text = page_list[i][0]
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        # Look for patterns like "1.1", "1.2", "2.1", etc.
        if re.match(r'^\d+\.\d+\s+', line):
            try:
                print(f"  p.{i+1}: {line}")
            except:
                print(f"  p.{i+1}: {repr(line)}")
