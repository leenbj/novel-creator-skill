#!/usr/bin/env python3
"""Unit Tests for Dynamic Draft Generator

测试动态草稿生成器的核心功能。

运行方式:
    python3 scripts/tests/test_dynamic_draft_generator.py
"""

import sys
import unittest
from pathlib import Path
import tempfile

# 添加 scripts 目录到路径
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from dynamic_draft_generator import (
    DynamicDraftGenerator,
    generate_chapter_draft
)


class TestDynamicDraftGenerator(unittest.TestCase):
    """动态草稿生成器测试"""
    
    def setUp(self):
        """测试前置设置"""
        # 使用临时目录
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        self.generator = DynamicDraftGenerator(self.project_root)
    
    def tearDown(self):
        """测试后清理"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_generator_initialization(self):
        """测试生成器初始化"""
        self.assertIsNotNone(self.generator)
        self.assertEqual(len(self.generator.STAGES), 4)
    
    def test_stage_determination(self):
        """测试阶段判断"""
        test_cases = [
            (5, "opening"),
            (20, "rising"),
            (40, "climax_building"),
            (60, "sustaining"),
            (100, "sustaining"),
        ]
        
        for chapter_no, expected_stage in test_cases:
            stage = self.generator._get_stage(chapter_no)
            self.assertEqual(stage, expected_stage, f"第{chapter_no}章应该是{expected_stage}阶段")
    
    def test_milestone_detection(self):
        """测试里程碑检测"""
        milestone_chapters = [50, 100, 150, 200]
        
        for chapter_no in milestone_chapters:
            milestone = self.generator._check_milestone(chapter_no)
            self.assertIsNotNone(milestone, f"第{chapter_no}章应该被识别为里程碑")
            self.assertIn(" - ", milestone)
        
        # 非里程碑章节
        non_milestone = self.generator._check_milestone(30)
        self.assertIsNone(non_milestone)
    
    def test_draft_generation_opening(self):
        """测试开篇阶段草稿生成"""
        draft = self.generator.generate_draft(
            chapter_no=5,
            query="开篇测试",
            previous_summary="前情提要",
            character_states={'protagonist': {'name': '张三'}}
        )
        
        self.assertIsInstance(draft, str)
        self.assertGreater(len(draft), 100)
        self.assertIn("第5章", draft)
        self.assertIn("开篇阶段", draft)
    
    def test_draft_generation_rising(self):
        """测试上升阶段草稿生成"""
        draft = self.generator.generate_draft(
            chapter_no=20,
            query="上升阶段测试",
            previous_summary=""
        )
        
        self.assertIn("上升阶段", draft)
        self.assertIn("第20章", draft)
    
    def test_draft_generation_climax_building(self):
        """测试高潮铺垫阶段草稿生成"""
        draft = self.generator.generate_draft(
            chapter_no=40,
            query="高潮铺垫测试",
            previous_summary=""
        )
        
        self.assertIn("高潮铺垫", draft)
        self.assertIn("第40章", draft)
    
    def test_draft_generation_sustaining(self):
        """测试长程维持阶段草稿生成"""
        draft = self.generator.generate_draft(
            chapter_no=60,
            query="长程维持测试",
            previous_summary=""
        )
        
        self.assertIn("长程维持", draft)
        self.assertIn("第60章", draft)
    
    def test_milestone_50(self):
        """测试第50章里程碑"""
        draft = self.generator.generate_draft(
            chapter_no=50,
            query="半百庆典",
            previous_summary=""
        )
        
        self.assertIn("半百庆典", draft)
        self.assertIn("里程碑", draft)
        self.assertIn("总结前49章", draft)
    
    def test_milestone_100(self):
        """测试第100章里程碑"""
        draft = self.generator.generate_draft(
            chapter_no=100,
            query="百章大节点",
            previous_summary=""
        )
        
        self.assertIn("百章大节点", draft)
        self.assertIn("里程碑", draft)
        self.assertIn("开启全新的故事篇章", draft)
    
    def test_convenience_function(self):
        """测试便捷函数"""
        draft = generate_chapter_draft(
            chapter_no=10,
            query="便捷函数测试",
            project_root=self.project_root,
            previous_summary="",
            character_states={}
        )
        
        self.assertIsInstance(draft, str)
        self.assertIn("第10章", draft)


class TestStageTemplates(unittest.TestCase):
    """阶段模板测试"""
    
    def setUp(self):
        """测试前置设置"""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        self.generator = DynamicDraftGenerator(self.project_root)
    
    def tearDown(self):
        """测试后清理"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_all_stages_have_templates(self):
        """测试所有阶段都有模板"""
        for stage in ['opening', 'rising', 'climax_building', 'sustaining']:
            template = self.generator.templates.get(stage)
            self.assertIsNotNone(template, f"{stage} 阶段应该有模板")
            self.assertIn('structure', template)
            self.assertIn('min_paragraphs', template)
    
    def test_template_structure(self):
        """测试模板结构完整性"""
        for stage, template in self.generator.templates.items():
            # 检查必需字段
            self.assertIn('structure', template)
            self.assertIn('min_paragraphs', template)
            self.assertIn('focus', template)
            
            # 检查结构列表不为空
            self.assertIsInstance(template['structure'], list)
            self.assertGreater(len(template['structure']), 0)
            
            # 检查最小段落数合理
            self.assertGreaterEqual(template['min_paragraphs'], 5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
