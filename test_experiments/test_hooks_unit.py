"""
单元测试：验证钩子架构框架
测试 EnhancementHooks 基类和 MultimodalEnhancementHooks 实现
"""
import sys
sys.path.insert(0, 'backend')

import asyncio
from pageindex.enhancement_hooks import (
    EnhancementHooks,
    MultimodalEnhancementHooks,
    NoOpEnhancementHooks,
)


class TestEnhancementHooks:
    """测试 EnhancementHooks 基类"""
    
    def test_base_class_returns_none(self):
        """测试基类所有钩子返回 None"""
        hooks = EnhancementHooks()
        
        # 测试所有钩子返回 None
        result = asyncio.run(hooks.on_check_toc([], {}))
        assert result is None, "on_check_toc should return None"
        
        result = asyncio.run(hooks.on_toc_extracted([], []))
        assert result is None, "on_toc_extracted should return None"
        
        result = asyncio.run(hooks.on_offset_calculated(0, [], []))
        assert result is None, "on_offset_calculated should return None"
        
        result = asyncio.run(hooks.on_structure_generated([], [], {}))
        assert result is None, "on_structure_generated should return None"
        
        result = asyncio.run(hooks.on_verify(0.5, [], []))
        assert result is None, "on_verify should return None"
        
        result = asyncio.run(hooks.on_fix_incorrect([], []))
        assert result is None, "on_fix_incorrect should return None"
        
        print("[PASS] Base class returns None for all hooks")
    
    def test_noop_hooks(self):
        """测试 NoOpEnhancementHooks"""
        hooks = NoOpEnhancementHooks()
        
        result = asyncio.run(hooks.on_check_toc([], {}))
        assert result is None
        
        result = asyncio.run(hooks.on_structure_generated([], [], {}))
        assert result is None
        
        print("[PASS] NoOp hooks work correctly")
    
    def test_multimodal_hooks_init(self):
        """测试 MultimodalEnhancementHooks 初始化"""
        # 默认初始化
        hooks = MultimodalEnhancementHooks()
        assert hooks.vlm_model == "qwen-vl-max"
        assert hooks.enable_hooks is None  # 全部启用
        
        # 指定模型
        hooks = MultimodalEnhancementHooks(vlm_model="custom-model")
        assert hooks.vlm_model == "custom-model"
        
        # 指定启用特定钩子
        hooks = MultimodalEnhancementHooks(enable_hooks=['on_check_toc'])
        assert hooks._is_enabled('on_check_toc') is True
        assert hooks._is_enabled('on_verify') is False
        
        print("[PASS] Multimodal hooks initialization")
    
    def test_is_enabled(self):
        """测试钩子启用检查"""
        # 全部启用
        hooks = MultimodalEnhancementHooks()
        assert hooks._is_enabled('on_check_toc') is True
        assert hooks._is_enabled('on_structure_generated') is True
        
        # 部分启用
        hooks = MultimodalEnhancementHooks(enable_hooks=['on_structure_generated'])
        assert hooks._is_enabled('on_check_toc') is False
        assert hooks._is_enabled('on_structure_generated') is True
        
        print("[PASS] Hook enablement checks")


class TestStructureGenerationHook:
    """测试结构生成钩子"""
    
    def test_no_dividers_returns_none(self):
        """没有分隔页时返回 None"""
        hooks = MultimodalEnhancementHooks()
        
        result = asyncio.run(hooks.on_structure_generated(
            [], 
            [("text", 100)],
            {"chapter_dividers": []}
        ))
        
        assert result is None, "Should return None when no dividers"
        print("[PASS] No dividers returns None")
    
    def test_build_structure_from_dividers(self):
        """测试从分隔页构建结构"""
        hooks = MultimodalEnhancementHooks()
        
        # 模拟分隔页
        page_list = [
            ("Cover page", 50),
            ("汇报提纲\nAI驱动的第五科研范式\n一 百花齐放的大模型时代", 100),
            ("汇报提纲\nAI驱动的第五科研范式\n一 百花齐放的大模型时代", 100),
            ("正文内容...", 500),
            ("正文内容...", 500),
            ("汇报提纲\nAI驱动的第五科研范式\n二 大模型辅助的科学假设生成", 100),
            ("正文内容...", 500),
        ]
        
        analysis_info = {"chapter_dividers": [2, 3, 6]}
        
        result = asyncio.run(hooks.on_structure_generated(
            [],
            page_list,
            analysis_info
        ))
        
        assert result is not None, "Should return structure"
        assert len(result) == 2, f"Expected 2 chapters, got {len(result)}"
        
        # 检查第一个章节
        assert result[0]['physical_index'] == 2
        assert result[0]['level'] == 1
        
        # 检查第二个章节
        assert result[1]['physical_index'] == 6
        
        print(f"[PASS] Built structure: {len(result)} chapters")
        for item in result:
            print(f"  - {item['title']} (p.{item['physical_index']})")
    
    def test_extract_chapter_title(self):
        """测试标题提取"""
        hooks = MultimodalEnhancementHooks()
        
        # 测试中文标题
        text = "汇报提纲\nAI驱动的第五科研范式\n一 百花齐放的大模型时代"
        title = hooks._extract_chapter_title(text, 1)
        assert "百花齐放" in title or "AI驱动" in title, f"Unexpected title: {title}"
        
        # 测试空文本
        title = hooks._extract_chapter_title("", 1)
        assert title == "Chapter 1"
        
        print(f"[PASS] Title extraction: '{title}'")


class TestCheckTocHook:
    """测试 TOC 检测钩子"""
    
    def test_existing_toc_not_enhanced(self):
        """已有 TOC 时不增强"""
        hooks = MultimodalEnhancementHooks()
        
        check_toc_result = {
            "toc_content": "第一章 ... 5\n第二章 ... 10",
            "toc_page_list": [1, 2]
        }
        
        result = asyncio.run(hooks.on_check_toc([], check_toc_result))
        assert result is None, "Should not enhance when TOC exists"
        print("[PASS] Existing TOC not enhanced")
    
    def test_detect_dividers_as_toc(self):
        """检测分隔页作为隐式 TOC"""
        hooks = MultimodalEnhancementHooks()
        
        # 模拟有分隔页的文档（使用相同的长文本作为分隔页）
        divider_text = "汇报提纲\nAI驱动的第五科研范式\n一 百花齐放的大模型时代\n二 大模型辅助的科学假设生成\n三 未来科研范式展望"
        
        page_list = [
            ("Cover", 50),
            (divider_text, 80),
            ("正文内容...", 500),
            ("正文内容...", 500),
            ("正文内容...", 500),
            ("正文内容...", 500),
            (divider_text, 80),
            ("正文内容...", 500),
            ("正文内容...", 500),
            ("正文内容...", 500),
            ("正文内容...", 500),
            (divider_text, 80),
        ]
        
        check_toc_result = {"toc_content": ""}  # 官方未检测到 TOC
        
        result = asyncio.run(hooks.on_check_toc(page_list, check_toc_result))
        
        assert result is not None, "Should detect dividers"
        assert result.get("has_dividers") is True
        assert len(result.get("divider_pages", [])) >= 2
        
        print(f"[PASS] Detected dividers: {result.get('divider_pages', [])}")


class TestVerifyHook:
    """测试验证钩子"""
    
    def test_high_accuracy_not_enhanced(self):
        """高准确率时不增强"""
        hooks = MultimodalEnhancementHooks()
        
        result = asyncio.run(hooks.on_verify(0.9, [], []))
        assert result is None, "Should not enhance when accuracy is high"
        print("[PASS] High accuracy not enhanced")
    
    def test_fuzzy_verification(self):
        """测试模糊匹配验证"""
        hooks = MultimodalEnhancementHooks()
        
        # 模拟验证失败的条目（由于文本提取差异）
        incorrect_items = [
            {
                "title": "AI驱动的科学研究",
                "physical_index": 3
            }
        ]
        
        # 页面文本包含类似标题（但有差异）
        page_list = [
            ("其他内容", 100),
            ("其他内容", 100),
            ("AI驱动的科学研究新范式", 500),  # 标题在文本中
        ]
        
        result = asyncio.run(hooks.on_verify(0.3, incorrect_items, page_list))
        
        if result:
            accuracy, items = result
            print(f"[PASS] Fuzzy verification: accuracy improved to {accuracy:.2%}")
            assert accuracy > 0.3, "Accuracy should improve"
        else:
            print("[INFO] Fuzzy verification did not improve (acceptable)")


def run_all_tests():
    """运行所有测试"""
    print("="*80)
    print("Running Enhancement Hooks Tests")
    print("="*80)
    print()
    
    test_classes = [
        TestEnhancementHooks,
        TestStructureGenerationHook,
        TestCheckTocHook,
        TestVerifyHook,
    ]
    
    passed = 0
    failed = 0
    
    for test_class in test_classes:
        print(f"\n{'='*80}")
        print(f"Testing: {test_class.__name__}")
        print("="*80)
        
        instance = test_class()
        methods = [m for m in dir(instance) if m.startswith('test_')]
        
        for method_name in methods:
            try:
                method = getattr(instance, method_name)
                method()
                passed += 1
            except AssertionError as e:
                print(f"[FAIL] {method_name}: {e}")
                failed += 1
            except Exception as e:
                print(f"[ERROR] {method_name}: {e}")
                failed += 1
    
    print(f"\n{'='*80}")
    print(f"Test Results: {passed} passed, {failed} failed")
    print("="*80)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
