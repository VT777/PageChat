"""
增强钩子设计：在官方函数内部提供扩展点
不修改官方代码，通过钩子机制注入多模态增强
"""
import sys, os
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure
import re
import glob

doc_dir = 'backend/data/documents'
pdf_files = [f for f in os.listdir(doc_dir) if f.endswith('.pdf')]
pdf_files.sort()

output_lines = []
output_lines.append("="*80)
output_lines.append("增强钩子架构设计")
output_lines.append("="*80)
output_lines.append("")
output_lines.append("核心思想：在官方函数的关键位置插入钩子，而不是替换整个函数")
output_lines.append("")

# 分析每个官方函数的增强机会
output_lines.append("官方函数增强点分析")
output_lines.append("-"*80)
output_lines.append("")

enhancement_points = {
    'check_toc': {
        'description': '检测文档是否有目录',
        'current': '文本扫描前20页',
        'weakness': '可能漏掉不寻常格式的TOC',
        'hook_name': 'on_check_toc',
        'hook_params': ['page_list', 'check_toc_result'],
        'enhancement': 'VLM缩略图验证TOC检测结果',
    },
    'toc_extractor': {
        'description': '从TOC页提取条目',
        'current': 'LLM从文本提取',
        'weakness': '可能提取错误或遗漏',
        'hook_name': 'on_toc_extracted',
        'hook_params': ['toc_items', 'page_list'],
        'enhancement': 'VLM视觉验证提取的条目',
    },
    'calculate_page_offset': {
        'description': '计算页码偏移量',
        'current': '文本匹配计算中位数',
        'weakness': '文本提取错误导致计算错误',
        'hook_name': 'on_offset_calculated',
        'hook_params': ['offset', 'toc_items', 'page_list'],
        'enhancement': 'VLM验证offset是否正确',
    },
    'process_no_toc': {
        'description': '无目录文档生成结构',
        'current': 'LLM从文本生成',
        'weakness': '可能漏掉视觉分隔页',
        'hook_name': 'on_structure_generated',
        'hook_params': ['structure', 'page_list', 'analysis_info'],
        'enhancement': 'VLM分析分隔页和整体布局',
    },
    'verify_toc': {
        'description': '验证TOC准确率',
        'current': 'LLM文本匹配验证',
        'weakness': '文本质量差时验证失败',
        'hook_name': 'on_verify',
        'hook_params': ['accuracy', 'incorrect_items', 'page_list'],
        'enhancement': 'VLM视觉验证替代文本验证',
    },
    'fix_incorrect_toc': {
        'description': '修正错误的TOC条目',
        'current': '在相邻正确条目间搜索',
        'weakness': '搜索范围可能不够',
        'hook_name': 'on_fix_incorrect',
        'hook_params': ['incorrect_items', 'page_list', 'neighbor_range'],
        'enhancement': 'VLM视觉定位正确页码',
    },
}

for func_name, info in enhancement_points.items():
    output_lines.append(f"函数: {func_name}")
    output_lines.append(f"  描述: {info['description']}")
    output_lines.append(f"  当前实现: {info['current']}")
    output_lines.append(f"  弱点: {info['weakness']}")
    output_lines.append(f"  钩子名: {info['hook_name']}")
    output_lines.append(f"  增强方式: {info['enhancement']}")
    output_lines.append("")

# 设计钩子接口
output_lines.append("="*80)
output_lines.append("钩子接口设计")
output_lines.append("="*80)
output_lines.append("")

output_lines.append("class EnhancementHooks:")
output_lines.append('    """多模态增强钩子 - 在官方流程关键节点提供增强能力"""')
output_lines.append("")
output_lines.append("    # 钩子1: TOC检测增强")
output_lines.append("    async def on_check_toc(self, page_list, check_toc_result):")
output_lines.append("        \"\"\"")
output_lines.append("        在check_toc后调用")
output_lines.append("        ")
output_lines.append("        Args:")
output_lines.append("            page_list: 页面文本列表")
output_lines.append("            check_toc_result: 官方检测结果")
output_lines.append("            ")
output_lines.append("        Returns:")
output_lines.append("            修正后的check_toc_result，或None（使用官方结果）")
output_lines.append("        \"\"\"")
output_lines.append("        pass")
output_lines.append("")
output_lines.append("    # 钩子2: TOC提取增强")
output_lines.append("    async def on_toc_extracted(self, toc_items, page_list):")
output_lines.append("        \"\"\"")
output_lines.append("        在TOC提取后调用")
output_lines.append("        ")
output_lines.append("        Args:")
output_lines.append("            toc_items: 提取的TOC条目列表")
output_lines.append("            page_list: 页面文本列表")
output_lines.append("            ")
output_lines.append("        Returns:")
output_lines.append("            修正后的toc_items，或None（使用官方结果）")
output_lines.append("        \"\"\"")
output_lines.append("        pass")
output_lines.append("")
output_lines.append("    # 钩子3: 偏移量计算增强")
output_lines.append("    async def on_offset_calculated(self, offset, toc_items, page_list):")
output_lines.append("        \"\"\"")
output_lines.append("        在offset计算后调用")
output_lines.append("        ")
output_lines.append("        Args:")
output_lines.append("            offset: 计算出的偏移量")
output_lines.append("            toc_items: TOC条目")
output_lines.append("            page_list: 页面文本列表")
output_lines.append("            ")
output_lines.append("        Returns:")
output_lines.append("            修正后的offset，或None（使用官方结果）")
output_lines.append("        \"\"\"")
output_lines.append("        pass")
output_lines.append("")
output_lines.append("    # 钩子4: 结构生成增强")
output_lines.append("    async def on_structure_generated(self, structure, page_list, analysis_info):")
output_lines.append("        \"\"\"")
output_lines.append("        在结构生成后调用（process_no_toc模式）")
output_lines.append("        ")
output_lines.append("        Args:")
output_lines.append("            structure: 生成的结构列表")
output_lines.append("            page_list: 页面文本列表")
output_lines.append("            analysis_info: 文档分析信息（包含分隔页等）")
output_lines.append("            ")
output_lines.append("        Returns:")
output_lines.append("            修正后的structure，或None（使用官方结果）")
output_lines.append("        \"\"\"")
output_lines.append("        pass")
output_lines.append("")
output_lines.append("    # 钩子5: 验证增强")
output_lines.append("    async def on_verify(self, accuracy, incorrect_items, page_list):")
output_lines.append("        \"\"\"")
output_lines.append("        在verify_toc后调用")
output_lines.append("        ")
output_lines.append("        Args:")
output_lines.append("            accuracy: 验证准确率")
output_lines.append("            incorrect_items: 验证错误的条目")
output_lines.append("            page_list: 页面文本列表")
output_lines.append("            ")
output_lines.append("        Returns:")
output_lines.append("            (修正后的accuracy, 修正后的incorrect_items)，或None")
output_lines.append("        \"\"\"")
output_lines.append("        pass")
output_lines.append("")
output_lines.append("    # 钩子6: 错误修正增强")
output_lines.append("    async def on_fix_incorrect(self, incorrect_items, page_list, neighbor_range):")
output_lines.append("        \"\"\"")
output_lines.append("        在fix_incorrect_toc_with_retries前调用")
output_lines.append("        ")
output_lines.append("        Args:")
output_lines.append("            incorrect_items: 需要修正的条目")
output_lines.append("            page_list: 页面文本列表")
output_lines.append("            neighbor_range: 相邻正确条目的范围")
output_lines.append("            ")
output_lines.append("        Returns:")
output_lines.append("            修正后的incorrect_items，或None（使用官方修正）")
output_lines.append("        \"\"\"")
output_lines.append("        pass")
output_lines.append("")

# 使用方式
output_lines.append("="*80)
output_lines.append("使用方式")
output_lines.append("="*80)
output_lines.append("")

output_lines.append("# 1. 创建自定义增强钩子")
output_lines.append("class MultimodalEnhancementHooks(EnhancementHooks):")
output_lines.append("    async def on_check_toc(self, page_list, check_toc_result):")
output_lines.append("        # 如果官方未检测到TOC，用VLM确认")
output_lines.append("        if not check_toc_result.get('toc_content'):")
output_lines.append("            vlm_result = await vlm_detect_toc(page_list)")
output_lines.append("            if vlm_result:")
output_lines.append("                return vlm_result")
output_lines.append("        return None  # 使用官方结果")
output_lines.append("")
output_lines.append("    async def on_structure_generated(self, structure, page_list, analysis_info):")
output_lines.append("        # 如果有分隔页，用VLM分析")
output_lines.append("        if analysis_info.get('has_dividers'):")
output_lines.append("            vlm_structure = await vlm_analyze_dividers(page_list, analysis_info['dividers'])")
output_lines.append("            if vlm_structure:")
output_lines.append("                return vlm_structure")
output_lines.append("        return None")
output_lines.append("")

output_lines.append("# 2. 在官方流程中使用")
output_lines.append("hooks = MultimodalEnhancementHooks()")
output_lines.append("result = await tree_parser(page_list, opt, hooks=hooks)")
output_lines.append("")

output_lines.append("# 3. 官方tree_parser内部逻辑（伪代码）")
output_lines.append("async def tree_parser(page_list, opt, hooks=None):")
output_lines.append("    # 步骤1: 检测TOC")
output_lines.append("    check_toc_result = check_toc(page_list, opt)")
output_lines.append("    ")
output_lines.append("    # 钩子: TOC检测增强")
output_lines.append("    if hooks:")
output_lines.append("        enhanced_result = await hooks.on_check_toc(page_list, check_toc_result)")
output_lines.append("        if enhanced_result is not None:")
output_lines.append("            check_toc_result = enhanced_result")
output_lines.append("    ")
output_lines.append("    # 步骤2: 根据检测结果路由")
output_lines.append("    if check_toc_result.get('toc_content'):")
output_lines.append("        toc_items = await meta_processor(...)")
output_lines.append("    else:")
output_lines.append("        toc_items = await meta_processor(mode='process_no_toc', ...)")
output_lines.append("    ")
output_lines.append("    # 步骤3: 验证")
output_lines.append("    accuracy, incorrect = await verify_toc(page_list, toc_items)")
output_lines.append("    ")
output_lines.append("    # 钩子: 验证增强")
output_lines.append("    if hooks and accuracy < 0.8:")
output_lines.append("        enhanced_verify = await hooks.on_verify(accuracy, incorrect, page_list)")
output_lines.append("        if enhanced_verify:")
output_lines.append("            accuracy, incorrect = enhanced_verify")
output_lines.append("    ")
output_lines.append("    # 步骤4: 修正错误")
output_lines.append("    if accuracy < 0.6:")
output_lines.append("        # 钩子: 错误修正增强")
output_lines.append("        if hooks:")
output_lines.append("            enhanced_fix = await hooks.on_fix_incorrect(incorrect, page_list, ...)")
output_lines.append("            if enhanced_fix:")
output_lines.append("                incorrect = enhanced_fix")
output_lines.append("        ")
output_lines.append("        # 官方修正逻辑")
output_lines.append("        fixed_items = await fix_incorrect_toc_with_retries(...)")
output_lines.append("    ")
output_lines.append("    return toc_items")
output_lines.append("")

# 优势分析
output_lines.append("="*80)
output_lines.append("优势分析")
output_lines.append("="*80)
output_lines.append("")

output_lines.append("vs 简单触发方案:")
output_lines.append("  [OK] 更精细的增强粒度（在每个函数内部）")
output_lines.append("  [OK] 保持官方API不变")
output_lines.append("  [OK] 模块化，每个钩子独立")
output_lines.append("  [OK] 失败自动回退到官方逻辑")
output_lines.append("")

output_lines.append("vs 替换官方方案:")
output_lines.append("  [OK] 保留官方核心逻辑")
output_lines.append("  [OK] 渐进式增强")
output_lines.append("  [OK] 风险可控")
output_lines.append("  [OK] 易于回滚")
output_lines.append("")

output_lines.append("vs 我们当前的Branch A/B/C:")
output_lines.append("  [OK] 没有并行路径")
output_lines.append("  [OK] 没有复杂的条件分支")
output_lines.append("  [OK] 逻辑清晰：官方为主，钩子增强")
output_lines.append("  [OK] 易于测试（每个钩子独立测试）")
output_lines.append("")

# 实施建议
output_lines.append("="*80)
output_lines.append("实施建议")
output_lines.append("="*80)
output_lines.append("")

output_lines.append("Phase 1: 基础框架（1-2天）")
output_lines.append("  1. 创建EnhancementHooks基类")
output_lines.append("  2. 修改tree_parser接受hooks参数")
output_lines.append("  3. 在关键位置插入钩子调用")
output_lines.append("  4. 测试无hooks时的行为（应与官方一致）")
output_lines.append("")

output_lines.append("Phase 2: 实现关键钩子（2-3天）")
output_lines.append("  1. on_structure_generated: 分隔页分析")
output_lines.append("  2. on_check_toc: TOC检测增强")
output_lines.append("  3. on_verify: 视觉验证")
output_lines.append("  4. 每个钩子独立测试")
output_lines.append("")

output_lines.append("Phase 3: 集成测试（1-2天）")
output_lines.append("  1. 在24个文档上测试")
output_lines.append("  2. 对比增强前后的准确率")
output_lines.append("  3. 测量性能和成本")
output_lines.append("")

output_lines.append("Phase 4: 优化（持续）")
output_lines.append("  1. 根据测试结果调整钩子策略")
output_lines.append("  2. 添加配置项控制钩子启用/禁用")
output_lines.append("  3. 监控钩子触发率和效果")
output_lines.append("")

output_lines.append("="*80)
output_lines.append("总结")
output_lines.append("="*80)
output_lines.append("")
output_lines.append("核心创新：钩子架构")
output_lines.append("  - 不替换官方流程")
output_lines.append("  - 在关键节点提供增强能力")
output_lines.append("  - 保持向后兼容")
output_lines.append("  - 模块化、可测试、可维护")
output_lines.append("")
output_lines.append("预期效果:")
output_lines.append("  - 准确率: ~85% -> ~95%")
output_lines.append("  - 成本: 增加20-30%（仅对需要增强的文档）")
output_lines.append("  - 复杂度: 远低于当前Branch A/B/C方案")
output_lines.append("  - 维护性: 每个钩子独立，易于调试")
output_lines.append("")

# Write to file
output_text = "\n".join(output_lines)
with open('test_experiments/hook_architecture_design.txt', 'w', encoding='utf-8') as f:
    f.write(output_text)

print("="*80)
print("Hook Architecture Design Complete")
print("="*80)
print()
print("Key innovation: Hook-based enhancement at official function level")
print("6 enhancement hooks identified in official pipeline")
print()
print("Benefits:")
print("  - Keep official API unchanged")
print("  - Modular, testable, maintainable")
print("  - Gradual enhancement, controllable risk")
print()
print("Report: test_experiments/hook_architecture_design.txt")
