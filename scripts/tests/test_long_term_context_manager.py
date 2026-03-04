#!/usr/bin/env python3
"""Unit Tests for Long Term Context Manager

测试长期上下文管理器的核心功能。

运行方式:
    python3 scripts/tests/test_long_term_context_manager.py
"""

import sys
import unittest
from pathlib import Path
import tempfile
import shutil

# 添加 scripts 目录到路径
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from long_term_context_manager import (
    LongTermContextManager,
    LongTermContext,
    ChapterSummary,
    CharacterState,
    get_long_term_context
)


class TestLongTermContextManager(unittest.TestCase):
    """长期上下文管理器测试"""
    
    def setUp(self):
        """测试前置设置"""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # 创建目录结构
        (self.project_root / "00_memory").mkdir(parents=True)
        (self.project_root / "03_manuscript").mkdir(parents=True)
        (self.project_root / "00_memory" / "retrieval").mkdir(parents=True)
        
        self.manager = LongTermContextManager(self.project_root)
    
    def tearDown(self):
        """测试后清理"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_manager_initialization(self):
        """测试管理器初始化"""
        self.assertIsNotNone(self.manager)
        self.assertEqual(len(self.manager.MILESTONES), 4)
    
    def test_context_window_calculation(self):
        """测试上下文窗口计算"""
        test_cases = [
            (5, 3),    # 开篇阶段
            (20, 5),   # 上升阶段
            (40, 7),   # 高潮铺垫
            (60, 10),  # 长程维持
        ]
        
        for chapter_no, expected_size in test_cases:
            window_size = self.manager._calculate_window_size(chapter_no)
            self.assertEqual(window_size, expected_size, 
                           f"第{chapter_no}章应该使用{expected_size}章的窗口")
    
    def test_get_context_for_chapter(self):
        """测试获取章节上下文"""
        context = self.manager.get_context_for_chapter(10)
        
        self.assertIsInstance(context, LongTermContext)
        self.assertIsInstance(context.recent_chapters, list)
        self.assertIsInstance(context.character_states, dict)
    
    def test_should_refresh_context(self):
        """测试上下文刷新判断"""
        # 里程碑章节需要刷新
        self.assertTrue(self.manager.should_refresh_context(50))
        self.assertTrue(self.manager.should_refresh_context(100))
        
        # 每10章刷新
        self.assertTrue(self.manager.should_refresh_context(60))
        self.assertTrue(self.manager.should_refresh_context(70))
        
        # 普通章节不刷新
        self.assertFalse(self.manager.should_refresh_context(55))
    
    def test_milestone_info(self):
        """测试里程碑信息获取"""
        # 第50章
        info_50 = self.manager.get_milestone_info(50)
        self.assertIsNotNone(info_50)
        self.assertEqual(info_50['name'], "半百庆典")
        
        # 第100章
        info_100 = self.manager.get_milestone_info(100)
        self.assertIsNotNone(info_100)
        self.assertEqual(info_100['name'], "百章大节点")
        
        # 非里程碑章节
        info_30 = self.manager.get_milestone_info(30)
        self.assertIsNone(info_30)
    
    def test_build_context_prompt(self):
        """测试上下文提示构建"""
        prompt = self.manager.build_context_prompt(10)
        
        self.assertIsInstance(prompt, str)
    
    def test_context_caching(self):
        """测试上下文缓存"""
        # 第一次获取
        context1 = self.manager.get_context_for_chapter(20)
        
        # 第二次获取（应该使用缓存）
        context2 = self.manager.get_context_for_chapter(20)
        
        # 应该是同一个对象实例
        self.assertIs(context1, context2)
        
        # 强制刷新
        context3 = self.manager.get_context_for_chapter(20, force_refresh=True)
        
        # 强制刷新后应返回新对象实例
        self.assertIsNot(context1, context3)


class TestChapterSummary(unittest.TestCase):
    """章节摘要测试"""
    
    def test_chapter_summary_creation(self):
        """测试章节摘要创建"""
        summary = ChapterSummary(
            chapter_no=10,
            title="测试章节",
            summary="这是一个测试摘要",
            key_events=["事件1", "事件2"],
            word_count=3000
        )
        
        self.assertEqual(summary.chapter_no, 10)
        self.assertEqual(summary.title, "测试章节")
        self.assertEqual(len(summary.key_events), 2)


class TestCharacterState(unittest.TestCase):
    """角色状态测试"""
    
    def test_character_state_creation(self):
        """测试角色状态创建"""
        state = CharacterState(
            name="张三",
            current_location="长安",
            current_status="健康",
            relationships={"李四": "朋友"}
        )
        
        self.assertEqual(state.name, "张三")
        self.assertEqual(state.current_location, "长安")
        self.assertIn("李四", state.relationships)


class TestConvenienceFunction(unittest.TestCase):
    """便捷函数测试"""
    
    def test_get_long_term_context(self):
        """测试便捷函数"""
        temp_dir = tempfile.mkdtemp()
        project_root = Path(temp_dir)
        
        try:
            (project_root / "00_memory").mkdir(parents=True)
            (project_root / "03_manuscript").mkdir(parents=True)
            
            context = get_long_term_context(project_root, 10)
            
            self.assertIsInstance(context, LongTermContext)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
