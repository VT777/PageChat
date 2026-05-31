import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, pymupdf

file_path = glob.glob("D:/projects/page_chat/backend/data/documents/*fa82c969*")[0]
doc = pymupdf.open(file_path)

# Check bookmarks
raw_toc = doc.get_toc()
print(f"PDF bookmarks: {len(raw_toc)} entries")
for level, title, page in raw_toc[:30]:
    indent = "  " * (level - 1)
    print(f"{indent}L{level} [{title[:60]}] p.{page}")

doc.close()
