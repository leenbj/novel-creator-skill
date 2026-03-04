#!/usr/bin/env python3
"""Integration Tests for Novel Quality Enhancement

测试长篇小说质量增强功能的集成效果。

运行方式:
    python3 scripts/tests/test_integration.py
"""

import sys
import unittest
from pathlib import Path
import tempfile
import shutil
import json

# 添加 scripts 目录到路径
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


class TestQualityEnhancementIntegration(unittest.TestCase):
    """质量增强集成测试"""
    
    def setUp(self):
        """测试前置设置"""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # 创建完整的目录结构
        dirs = [
            "00_memory",
            "00_memory/retrieval",
            "00_memory/retrieval/chapter_meta",
            "02_knowledge_base",
            "03_manuscript",
            "04_editing",
            "04_editing/gate_artifacts"
        ]
        
        for d in dirs:
            (self.project_root / d).mkdir(parents=True, exist_ok=True)
    
    def tearDown(self):
        """测试后清理"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_content_expansion_engine_integration(self):
        """测试内容扩充引擎集成"""
        from content_expansion_engine import expand_chapter_content
        
        # 模拟短章节
        short_chapter = """
# 第10章 测试章节

主角走进了房间，环顾四周。

"有人吗？"他问道。

但没有人回答。
"""
        
        # 扩充章节
        context = {
            'characters': {'protagonist': '张三'},
            'plot_line': '测试情节',
            'previous_ending': '上一章结尾',
            'scene_setting': '测试场景'
        }
        
        expanded = expand_chapter_content(
            short_chapter,
            target_chars=500,
            chapter_no=10,
            context=context
        )
        
        # 验证扩充效果
        self.assertGreater(len(expanded), len(short_chapter))
        print(f"✓ 内容扩充: {len(short_chapter)} -> {len(expanded)} 字符")
    
    def test_dynamic_draft_generator_integration(self):
        """测试动态草稿生成器集成"""
        from dynamic_draft_generator import generate_chapter_draft
        
        # 测试不同阶段
        stages = [
            (5, "opening"),
            (20, "rising"),
            (40, "climax_building"),
            (60, "sustaining")
        ]
        
        for chapter_no, stage in stages:
            draft = generate_chapter_draft(
                chapter_no=chapter_no,
                query=f"第{chapter_no}章测试",
                project_root=self.project_root,
                previous_summary=""
            )
            
            # 验证草稿生成
            self.assertGreater(len(draft), 100)
            self.assertIn(f"第{chapter_no}章", draft)
            print(f"✓ 草稿生成: 第{chapter_no}章 ({stage}阶段)")
    
    def test_long_term_context_integration(self):
        """测试长期上下文管理器集成"""
        from long_term_context_manager import LongTermContextManager
        
        manager = LongTermContextManager(self.project_root)
        
        # 测试不同章节的上下文获取
        chapters = [10, 30, 50, 100]
        
        for chapter_no in chapters:
            context = manager.get_context_for_chapter(chapter_no)
            
            # 验证上下文结构
            self.assertIsNotNone(context)
            self.assertIsInstance(context.recent_chapters, list)
            
            # 检查里程碑
            if chapter_no in [50, 100]:
                milestone = manager.get_milestone_info(chapter_no)
                self.assertIsNotNone(milestone)
                print(f"✓ 里程碑: 第{chapter_no}章 - {milestone['name']}")
    
    def test_quality_evaluation_enhancement(self):
        """测试质量评估增强"""
        # 模拟质量评估（简化版本）
        test_chapter = """
这是一个测试章节的内容。主角走进了房间。

"你好，"他说道。

房间里很安静，只有窗外的鸟鸣声。他环顾四周，看到了一张桌子，上面放着一些文件。

他走过去，拿起文件，开始阅读。文件的内容让他感到惊讶。

"这怎么可能？"他自言自语道。

就在这时，门突然打开了。
""" * 10  # 重复以达到足够字数
        
        # 统计指标
        import re
        pure_text = re.sub(r'\s+', '', test_chapter)
        char_count = len(pure_text)
        
        # 对话占比
        dialogue_chars = len(re.findall(r'[\"\"][^\"\"]+[\"\"]', test_chapter))
        dialogue_ratio = dialogue_chars / char_count if char_count else 0
        
        # 验证质量指标
        self.assertGreater(char_count, 500)  # 字数足够
        self.assertGreater(dialogue_ratio, 0)  # 有对话
        
        print(f"✓ 质量评估: {char_count}字, 对话占比{dialogue_ratio:.2%}")
    
    def test_end_to_end_workflow(self):
        """测试端到端工作流"""
        print("\n=== 端到端工作流测试 ===")
        
        # 1. 生成草稿
        from dynamic_draft_generator import generate_chapter_draft
        draft = generate_chapter_draft(
            chapter_no=10,
            query="测试工作流",
            project_root=self.project_root
        )
        print(f"1. 草稿生成完成: {len(draft)} 字符")
        
        # 2. 获取上下文
        from long_term_context_manager import get_long_term_context
        context = get_long_term_context(self.project_root, 10)
        print(f"2. 上下文获取完成: {len(context.recent_chapters)} 章摘要")
        
        # 3. 扩充内容
        from content_expansion_engine import expand_chapter_content
        expanded = expand_chapter_content(
            draft[:200],  # 使用部分草稿
            target_chars=300,
            chapter_no=10,
            context={'characters': {}, 'plot_line': '测试'}
        )
        print(f"3. 内容扩充完成: {len(draft[:200])} -> {len(expanded)} 字符")
        
        print("✓ 端到端工作流测试通过")


class TestMilestoneHandling(unittest.TestCase):
    """里程碑处理测试"""
    
    def setUp(self):
        """测试前置设置"""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        (self.project_root / "00_memory").mkdir(parents=True)
        (self.project_root / "03_manuscript").mkdir(parents=True)
    
    def tearDown(self):
        """测试后清理"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_milestone_50_workflow(self):
        """测试第50章里程碑工作流"""
        from dynamic_draft_generator import DynamicDraftGenerator
        from long_term_context_manager import LongTermContextManager
        
        # 生成第50章草稿
        generator = DynamicDraftGenerator(self.project_root)
        draft = generator.generate_draft(50, "半百庆典")
        
        # 验证里程碑标记
        self.assertIn("半百庆典", draft)
        self.assertIn("里程碑", draft)
        
        # 获取里程碑信息
        manager = LongTermContextManager(self.project_root)
        milestone = manager.get_milestone_info(50)
        
        self.assertEqual(milestone['name'], "半百庆典")
        self.assertEqual(len(milestone['tasks']), 4)
        
        print("✓ 第50章里程碑处理正确")
    
    def test_milestone_100_workflow(self):
        """测试第100章里程碑工作流"""
        from dynamic_draft_generator import DynamicDraftGenerator
        
        generator = DynamicDraftGenerator(self.project_root)
        draft = generator.generate_draft(100, "百章大节点")
        
        # 验证里程碑标记
        self.assertIn("百章大节点", draft)
        self.assertIn("重大转折", draft)
        
        print("✓ 第100章里程碑处理正确")


class TestPerformanceBenchmarks(unittest.TestCase):
    """性能基准测试"""
    
    def setUp(self):
        """测试前置设置"""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        (self.project_root / "00_memory").mkdir(parents=True)
        (self.project_root / "03_manuscript").mkdir(parents=True)
    
    def tearDown(self):
        """测试后清理"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_content_expansion_performance(self):
        """测试内容扩充性能"""
        import time
        from content_expansion_engine import expand_chapter_content
        
        # 准备测试数据
        test_text = "测试文本。" * 50
        context = {'characters': {}, 'plot_line': '测试'}
        
        # 计时
        start_time = time.time()
        result = expand_chapter_content(test_text, 500, 10, context)
        elapsed_time = time.time() - start_time
        
        # 验证性能
        self.assertLess(elapsed_time, 5.0)  # 应该在5秒内完成
        print(f"✓ 内容扩充性能: {elapsed_time:.2f}秒")
    
    def test_draft_generation_performance(self):
        """测试草稿生成性能"""
        import time
        from dynamic_draft_generator import generate_chapter_draft
        
        # 计时
        start_time = time.time()
        draft = generate_chapter_draft(10, "测试", self.project_root)
        elapsed_time = time.time() - start_time
        
        # 验证性能
        self.assertLess(elapsed_time, 1.0)  # 应该在1秒内完成
        print(f"✓ 草稿生成性能: {elapsed_time:.2f}秒")
    
    def test_context_retrieval_performance(self):
        """测试上下文检索性能"""
        import time
        from long_term_context_manager import get_long_term_context
        
        # 计时
        start_time = time.time()
        context = get_long_term_context(self.project_root, 10)
        elapsed_time = time.time() - start_time
        
        # 验证性能
        self.assertLess(elapsed_time, 1.0)  # 应该在1秒内完成
        print(f"✓ 上下文检索性能: {elapsed_time:.2f}秒")


if __name__ == '__main__':
    # 运行测试
    unittest.main(verbosity=2)