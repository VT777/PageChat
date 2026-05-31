"""
章节分隔符检测策略测试
检测重复出现的短页面作为章节分隔符
"""
import sys, os
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure
import re
from collections import defaultdict

doc_dir = 'backend/data/documents'

# 获取所有PDF文件
pdf_files = [f for f in os.listdir(doc_dir) if f.endswith('.pdf')]
pdf_files.sort()

print("="*80)
print("章节分隔符检测策略测试")
print("="*80)
print(f"测试文档数: {len(pdf_files)}")
print()

# 策略参数
MIN_SHORT_PAGES = 5       # 最少重复短页数（提高阈值减少误报）
MIN_DISPERSION = 5        # 最小分散间隔（页）
MAX_SHORT_LENGTH = 300    # 短页面最大字符数
MIN_FINGERPRINT_LEN = 20  # 指纹最小长度

def extract_content_fingerprint(text, max_len=100):
    """提取内容指纹（去除空格、数字、标点）"""
    # 保留中文字符和英文字母
    fp = re.sub(r'[^\u4e00-\u9fa5a-zA-Z]', '', text[:max_len])
    return fp

def detect_chapter_dividers(page_texts):
    """
    检测章节分隔符：重复出现的相同短页面
    
    返回:
        is_special: 是否是章节分隔文档
        divider_pages: 分隔符页面列表
        confidence: 置信度
    """
    total_pages = len(page_texts)
    
    # 步骤1：提取所有短页面的指纹（排除第一页和最后一页）
    fingerprint_pages = defaultdict(list)
    
    for i, text in enumerate(page_texts):
        page_num = i + 1
        text_stripped = text.strip()
        text_len = len(text_stripped)
        
        # 跳过空白页、长页面、第一页和最后一页
        if text_len == 0 or text_len > MAX_SHORT_LENGTH:
            continue
        if page_num == 1 or page_num == total_pages:
            continue
        
        # 提取指纹
        fp = extract_content_fingerprint(text_stripped)
        
        # 跳过太短的指纹
        if len(fp) < MIN_FINGERPRINT_LEN:
            continue
        
        fingerprint_pages[fp].append(page_num)
    
    # 步骤2：找重复出现的指纹（>=3次）
    candidates = []
    for fp, pages in fingerprint_pages.items():
        if len(pages) >= MIN_SHORT_PAGES:
            # 检查分散性
            pages_sorted = sorted(pages)
            if len(pages_sorted) >= 2:
                gaps = [pages_sorted[i+1] - pages_sorted[i] 
                       for i in range(len(pages_sorted)-1)]
                max_gap = max(gaps)
                
                # 需要有一定的分散性（不是连续的）
                if max_gap >= MIN_DISPERSION:
                    # 计算平均长度
                    avg_len = sum(len(page_texts[p-1].strip()) for p in pages_sorted) / len(pages_sorted)
                    
                    # 检查是否所有页面都是非连续的（真正的分隔符不应该连续出现）
                    non_consecutive = all(g >= 2 for g in gaps)
                    
                    candidates.append({
                        'fingerprint': fp,
                        'pages': pages_sorted,
                        'count': len(pages_sorted),
                        'max_gap': max_gap,
                        'avg_len': avg_len,
                        'non_consecutive': non_consecutive
                    })
    
    if not candidates:
        return False, [], 0.0
    
    # 步骤3：选择最佳候选
    # 优先选择：非连续的 > 页数多的 > 平均长度短的
    best = max(candidates, key=lambda x: (x['non_consecutive'], x['count'], -x['avg_len']))
    
    # 如果最佳候选是连续的，降低置信度
    if not best['non_consecutive']:
        # 检查是否只有前两页连续（可能是目录跨页），其余分散
        pages = best['pages']
        if len(pages) >= 4 and pages[1] - pages[0] == 1 and all(pages[i+1] - pages[i] >= 2 for i in range(1, len(pages)-1)):
            # 只有前两个连续，后面都分散，这是可以接受的（目录页跨页）
            pass
        else:
            # 太多连续页面，可能是误报
            return False, [], 0.0
    
    # 计算置信度
    confidence = min(1.0, best['count'] / 5.0)  # 5页以上=100%置信度
    if best['max_gap'] >= 10:
        confidence = min(1.0, confidence + 0.2)  # 分散性好，加分
    if best['avg_len'] < 100:
        confidence = min(1.0, confidence + 0.1)  # 页面很短，加分
    
    return True, best['pages'], confidence

# 运行测试
results = []
target_detected = False

for pdf_file in pdf_files:
    pdf_path = os.path.join(doc_dir, pdf_file)
    
    try:
        analysis = analyze_pdf_structure(pdf_path)
        page_texts = analysis['page_texts']
        
        is_special, divider_pages, confidence = detect_chapter_dividers(page_texts)
        
        result = {
            'file': pdf_file,
            'pages': len(page_texts),
            'is_special': is_special,
            'divider_pages': divider_pages,
            'confidence': confidence
        }
        results.append(result)
        
        # 检查是否是目标文档
        if 'f9a2f07e' in pdf_file:
            target_detected = is_special
            print(f"目标文档: {pdf_file}")
            print(f"  总页数: {len(page_texts)}")
            print(f"  检测结果: {'[PASS] 是' if is_special else '[FAIL] 否'}")
            print(f"  分隔页: {divider_pages}")
            print(f"  置信度: {confidence:.2f}")
            print()
        
    except Exception as e:
        print(f"错误 - {pdf_file}: {e}")

# 统计结果
special_count = sum(1 for r in results if r['is_special'])

print("="*80)
print("测试结果统计")
print("="*80)
print(f"总文档数: {len(results)}")
print(f"检测到章节分隔符: {special_count}")
print(f"目标文档检测: {'[PASS] 成功' if target_detected else '[FAIL] 失败'}")
print()

# 列出所有检测到的文档
if special_count > 0:
    print("检测到的文档列表:")
    for r in results:
        if r['is_special']:
            print(f"  - {r['file'][:60]}")
            print(f"    页数: {r['pages']}, 分隔页: {r['divider_pages']}, 置信度: {r['confidence']:.2f}")
    print()

# 检查是否有误报（非目标文档被检测）
false_positives = [r for r in results if r['is_special'] and 'f9a2f07e' not in r['file']]
print(f"误报数: {len(false_positives)}")
if false_positives:
    print("误报文档:")
    for r in false_positives:
        print(f"  - {r['file']}")
else:
    print("[OK] 无误报")

print()
print("="*80)
print("测试完成")
print("="*80)
