"""Test qwen-vl-ocr-latest API call."""

import sys
import os
import base64
import asyncio
from pathlib import Path

# 从 .env 加载配置
env_path = Path(__file__).parent / "backend" / ".env"
if env_path.exists():
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                key, value = line.strip().split('=', 1)
                os.environ[key] = value

sys.path.insert(0, str(Path(__file__).parent / "backend"))

import fitz  # PyMuPDF

# 选择技术应用洞察报告测试
pdf_path = Path(r"D:\projects\page_chat\backend\data\documents")
# 优先找技术应用洞察报告
pdf_files = list(pdf_path.glob("*097e50d9*.pdf"))
if not pdf_files:
    pdf_files = list(pdf_path.glob("*.pdf"))
if not pdf_files:
    print("No PDF files found")
    sys.exit(1)

test_pdf = pdf_files[0]
print(f"Testing with: {test_pdf.name}")

# 提取第5页为图片（技术应用洞察报告的第5页应该是有内容的）
doc = fitz.open(str(test_pdf))
page_num = 5  # 第5页
page = doc[page_num - 1]
pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x缩放提高清晰度
img_bytes = pix.tobytes("png")
img_base64 = base64.b64encode(img_bytes).decode('utf-8')
doc.close()

print(f"Image size: {len(img_bytes)} bytes")
print(f"Base64 length: {len(img_base64)} chars")

# 测试OCR API调用
async def test_ocr():
    from openai import AsyncOpenAI
    
    api_key = os.getenv("LLM_API_KEY")  # 使用同一个DashScope key
    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    if not api_key:
        print("ERROR: LLM_API_KEY not found")
        return
    
    print(f"\nUsing API Key: {api_key[:20]}...")
    print(f"Base URL: {base_url}")
    
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
    )
    
    prompt = """
请提取图像中的所有文本内容，保持原有排版结构。
要求：
1. 保留所有文字，不要遗漏
2. 保持段落和换行格式
3. 不要添加任何额外描述或解释
"""
    
    try:
        print("\nSending OCR request...")
        completion = await client.chat.completions.create(
            model="qwen-vl-ocr-latest",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_base64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }],
            max_tokens=4096,
        )
        
        result = completion.choices[0].message.content
        print(f"\n{'='*60}")
        print("OCR RESULT:")
        print(f"{'='*60}")
        print(result)
        print(f"{'='*60}")
        
        # 保存到文件查看
        with open("test_ocr_result.txt", "w", encoding="utf-8") as f:
            f.write(result)
        print("\nResult saved to test_ocr_result.txt")
        print("\n[PASS] OCR test PASSED")
        
    except Exception as e:
        print(f"\n[FAIL] OCR test FAILED: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(test_ocr())
