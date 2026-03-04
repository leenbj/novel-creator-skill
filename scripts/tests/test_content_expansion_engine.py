#!/usr/bin/env python3
"""Unit Tests for Content Expansion Engine

测试内容扩充引擎的核心功能。

运行方式:
    python3 scripts/tests/test_content_expansion_engine.py
"""

import sys
import unittest
from pathlib import Path

# 添加 scripts 目录到路径
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from content_expansion_engine import (
    ContentExpansionEngine,
    ExpansionContext,
    expand_chapter_content
)


class TestContentExpansionEngine(unittest.TestCase):
    """内容扩充引擎测试"""
    
    def setUp(self):
        """测试前置设置"""
        self.engine = ContentExpansionEngine()
        self.context = ExpansionContext(
            chapter_no=10,
            characters={'protagonist': {'name': '张三'}},
            plot_line='测试情节',
            previous_ending='上一章结尾',
            scene_setting='测试场景'
        )
    
    def test_engine_initialization(self):
        """测试引擎初始化"""
        self.assertIsNotNone(self.engine)
        self.assertEqual(len(self.engine.strategies), 5)
    
    def test_expansion_context_creation(self):
        """测试上下文创建"""
        self.assertEqual(self.context.chapter_no, 10)
        self.assertIn('protagonist', self.context.characters)
    
    def test_needs_scene_expansion(self):
        """测试场景扩充判断"""
        # 场景少的文本需要扩充
        short_text = "这是一个简单的测试文本。"
        self.assertTrue(self.engine._needs_scene_expansion(short_text))
        
        # 场景多的文本不需要扩充
        rich_text = "场景：清晨的湖边。地点：古庙。时间：黄昏。环境：寂静。"
        self.assertFalse(self.engine._needs_scene_expansion(rich_text))
    
    def test_needs_dialogue(self):
        """测试对话扩充判断"""
        # 对话少的文本
        no_dialogue = "他走进了房间，环顾四周。"
        self.assertTrue(self.engine._needs_dialogue(no_dialogue))
        
        # 对话多的文本
        rich_dialogue = '“你好，”他说道。“很高兴见到你，”她回答道。'
        self.assertFalse(self.engine._needs_dialogue(rich_dialogue))
    
    def test_expand_scenes(self):
        """测试场景扩充"""
        text = "这是一个测试文本。"
        expansion = self.engine._expand_scenes(text, 200, self.context)
        
        self.assertIsInstance(expansion, str)
        self.assertGreater(len(expansion), 0)
    
    def test_enrich_dialogue(self):
        """测试对话丰富化"""
        text = "他走进了房间。"
        expansion = self.engine._enrich_dialogue(text, 200, self.context)
        
        self.assertIsInstance(expansion, str)
        self.assertGreater(len(expansion), 0)
    
    def test_expand_content(self):
        """测试完整内容扩充"""
        original_text = "这是一个测试文本。主角走进了房间。"
        target_chars = 200
        
        expanded = self.engine.expand_content(original_text, target_chars, self.context)
        
        # 验证扩充效果
        self.assertIsInstance(expanded, str)
        self.assertGreater(len(expanded), len(original_text))
    
    def test_expand_chapter_content_function(self):
        """测试便捷函数"""
        text = "测试文本内容。"
        context_dict = {
            'characters': {'protagonist': '张三'},
            'plot_line': '测试',
            'previous_ending': '结尾',
            'scene_setting': '场景'
        }
        
        result = expand_chapter_content(text, 300, 1, context_dict)
        
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), len(text))
    
    def test_integrate_expansion(self):
        """测试内容融合"""
        original = "第一段内容。\n\n第二段内容。"
        expansion = "扩充内容1。\n\n扩充内容2。"
        
        result = self.engine._integrate_expansion(original, expansion)
        
        self.assertIn("第一段内容", result)
        self.assertIn("第二段内容", result)
    
    def test_no_expansion_when_target_reached(self):
        """测试目标字数已达标时不扩充"""
        long_text = "这是一段很长的文本内容。" * 100
        target_chars = 100
        
        result = self.engine.expand_content(long_text, target_chars, self.context)
        
        # 应该返回原文本
        self.assertEqual(result, long_text)


class TestExpansionStrategies(unittest.TestCase):
    """扩充策略测试"""
    
    def setUp(self):
        """测试前置设置"""
        self.engine = ContentExpansionEngine()
        self.context = ExpansionContext(
            chapter_no=10,
            characters={'protagonist': {'name': '张三'}},
            plot_line='测试',
            previous_ending='',
            scene_setting=''
        )
    
    def test_all_strategies_available(self):
        """测试所有策略都可用"""
        strategy_names = [s.name for s in self.engine.strategies]
        
        expected_strategies = [
            'scene_expansion',
            'dialogue_enrichment', 
            'psychological_depth',
            'action_detail',
            'transition_smoothing'
        ]
        
        for expected in expected_strategies:
            self.assertIn(expected, strategy_names)
    
    def test_strategy_priority_analysis(self):
        """测试策略优先级分析"""
        text = "简单的测试文本。"
        priorities = self.engine._analyze_expansion_priorities(text, self.context)
        
        # 应该返回策略列表
        self.assertIsInstance(priorities, list)
        self.assertGreater(len(priorities), 0)
        
        # 每个策略应该有权重
        for strategy_name, weight in priorities:
            self.assertIsInstance(strategy_name, str)
            self.assertIsInstance(weight, float)
            self.assertGreater(weight, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
