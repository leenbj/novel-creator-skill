#!/usr/bin/env python3
"""Content Expansion Engine - 智能内容扩充引擎

提供真正的文本扩展功能，而非简单的指令追加。
通过多种扩充策略（场景、对话、心理、动作、过渡）实现内容的智能扩展。

作者: Claude Code
版本: 1.0.0
日期: 2025-03-02
"""

import re
import random
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass
from pathlib import Path

QUOTE_PATTERN = r'[“"][^”"]+[”"]'
QUOTE_CAPTURE_PATTERN = r'[“"]([^”"]+)[”"]'


@dataclass
class ExpansionContext:
    """扩充上下文"""
    chapter_no: int
    characters: Dict[str, Dict]  # 角色状态
    plot_line: str  # 当前情节线
    previous_ending: str  # 上一章结尾
    scene_setting: str  # 场景设定


@dataclass
class ExpansionStrategy:
    """扩充策略"""
    name: str
    applies_to: Callable[[str], bool]
    expand: Callable[[str, int, ExpansionContext], str]


class ContentExpansionEngine:
    """内容扩充引擎主类"""
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.strategies = self._init_strategies()
        self._load_template_library()
    
    def _init_strategies(self) -> List[ExpansionStrategy]:
        """初始化扩充策略集合"""
        return [
            ExpansionStrategy(
                name="scene_expansion",
                applies_to=self._needs_scene_expansion,
                expand=self._expand_scenes,
            ),
            ExpansionStrategy(
                name="dialogue_enrichment",
                applies_to=self._needs_dialogue,
                expand=self._enrich_dialogue,
            ),
            ExpansionStrategy(
                name="psychological_depth",
                applies_to=self._needs_psychology,
                expand=self._deepen_psychology,
            ),
            ExpansionStrategy(
                name="action_detail",
                applies_to=self._needs_action,
                expand=self._detail_actions,
            ),
            ExpansionStrategy(
                name="transition_smoothing",
                applies_to=self._needs_transitions,
                expand=self._smooth_transitions,
            ),
        ]
    
    def expand_content(self, text: str, target_chars: int, context: ExpansionContext) -> str:
        """
        扩充内容至目标字数
        
        Args:
            text: 原始文本
            target_chars: 目标字数
            context: 扩充上下文
        
        Returns:
            扩充后的文本
        """
        current_chars = len(re.sub(r"\s+", "", text))
        if current_chars >= target_chars:
            return text
        
        needed_chars = target_chars - current_chars
        
        # 制定扩充计划
        expansion_plan = self._create_expansion_plan(text, needed_chars, context)
        
        # 执行扩充
        result = text
        for strategy_name, amount in expansion_plan:
            strategy = next((s for s in self.strategies if s.name == strategy_name), None)
            if strategy and strategy.applies_to(result):
                expansion = strategy.expand(result, amount, context)
                result = self._integrate_expansion(result, expansion)
        
        return result
    
    def _create_expansion_plan(self, text: str, needed_chars: int, context: ExpansionContext) -> List[Tuple[str, int]]:
        """制定扩充计划，智能分配各策略的扩充量"""
        plan = []
        remaining = needed_chars
        
        # 根据文本分析和上下文决定优先级
        priorities = self._analyze_expansion_priorities(text, context)
        
        for strategy_name, priority in priorities:
            if remaining <= 0:
                break
            
            # 根据优先级分配扩充量
            allocation = min(
                remaining,
                int(needed_chars * priority)
            )
            
            if allocation > 0:
                plan.append((strategy_name, allocation))
                remaining -= allocation
        
        # 如果还有剩余，分配给最高优先级的策略
        if remaining > 0 and plan:
            plan[-1] = (plan[-1][0], plan[-1][1] + remaining)
        
        return plan
    
    def _analyze_expansion_priorities(self, text: str, context: ExpansionContext) -> List[Tuple[str, float]]:
        """分析并返回各扩充策略的优先级（策略名，权重）"""
        priorities = []
        
        # 场景扩充检查
        scene_count = len(re.findall(r'场景|地点|时间|天色|环境', text))
        if scene_count < 3:
            priorities.append(("scene_expansion", 0.25))
        
        # 对话丰富度检查
        dialogue_chars = sum(len(m.group(1)) for m in re.finditer(QUOTE_CAPTURE_PATTERN, text))
        text_chars = len(re.sub(r"\s+", "", text))
        dialogue_ratio = dialogue_chars / text_chars if text_chars else 0
        if dialogue_ratio < 0.2:
            priorities.append(("dialogue_enrichment", 0.20))
        
        # 心理描写检查
        psych_markers = ['想', '觉得', '感觉', '意识到', '认为', '心中']
        psych_count = sum(text.count(m) for m in psych_markers)
        if psych_count < 5:
            priorities.append(("psychological_depth", 0.15))
        
        # 动作细节检查
        action_verbs = ['走', '跑', '跳', '打', '拿', '放', '看', '听', '站', '坐']
        action_count = sum(text.count(v) for v in action_verbs)
        if action_count < 20:
            priorities.append(("action_detail", 0.15))
        
        # 过渡平滑度检查
        transitions = ['随后', '接着', '与此同时', '不久之后', '紧接着']
        trans_count = sum(text.count(t) for t in transitions)
        if trans_count < 3:
            priorities.append(("transition_smoothing", 0.10))
        
        # 如果没有明显的优先级，平均分配
        if not priorities:
            return [
                ("scene_expansion", 0.20),
                ("dialogue_enrichment", 0.20),
                ("psychological_depth", 0.15),
                ("action_detail", 0.15),
                ("transition_smoothing", 0.10),
            ]
        
        # 按权重排序
        priorities.sort(key=lambda x: x[1], reverse=True)
        return priorities
    
    # 具体扩充策略实现
    
    def _needs_scene_expansion(self, text: str) -> bool:
        """判断是否需要场景扩充"""
        scene_markers = ['场景', '地点', '时间', '天色', '环境', '氛围']
        scene_count = sum(1 for marker in scene_markers if marker in text)
        return scene_count < 3
    
    def _expand_scenes(self, text: str, amount: int, context: ExpansionContext) -> str:
        """场景扩充实现"""
        expansion_parts = []
        
        # 生成环境氛围描写
        atmosphere_templates = [
            f"天色{random.choice(['渐暗', '微明', '阴沉', '晴朗'])}，四周{random.choice(['寂静无声', '风声萧瑟', '人声鼎沸', '虫鸣鸟叫'])}。",
            f"空气中弥漫着{random.choice(['潮湿的泥土味', '淡淡的花香', '紧张的气氛', '硝烟的味道'])}。",
            f"{context.characters.get('protagonist', '主角')}环顾四周，目光所及之处{random.choice(['一片荒凉', '景色宜人', '暗藏杀机', '繁华依旧'])}。",
        ]
        
        expansion_parts.extend(random.sample(atmosphere_templates, min(2, len(atmosphere_templates))))
        
        return "\n\n".join(expansion_parts)
    
    def _needs_dialogue(self, text: str) -> bool:
        """判断是否需要对话扩充"""
        dialogue_chars = sum(len(m.group(1)) for m in re.finditer(QUOTE_CAPTURE_PATTERN, text))
        text_chars = len(re.sub(r"\s+", "", text))
        dialogue_ratio = dialogue_chars / text_chars if text_chars else 0
        return dialogue_ratio < 0.2
    
    def _enrich_dialogue(self, text: str, amount: int, context: ExpansionContext) -> str:
        """对话丰富化实现"""
        dialogue_templates = [
            f'"{random.choice(["你觉得呢？", "你怎么看？", "有什么想法？"])}"{random.choice(["他问道", "她说道", "有人插话"])}。',
            f'"{random.choice(["不太可能", "或许吧", "我觉得可行"])}，"{random.choice([" protagonist 摇了摇头", "对方沉吟道", "某人补充道"])}。',
            f'"{random.choice(["那接下来怎么办？", "然后呢？", "我们该怎么做？"])}"{random.choice(["紧张的气氛中", "沉默片刻后", "众人交换眼神后"])}有人问道。',
        ]
        
        selected = random.sample(dialogue_templates, min(2, len(dialogue_templates)))
        return "\n\n".join(selected)
    
    def _needs_psychology(self, text: str) -> bool:
        """判断是否需要心理描写扩充"""
        psych_markers = ['想', '觉得', '感觉', '意识到', '认为', '心中', '暗想', '思索', '犹豫', '决心']
        psych_count = sum(text.count(m) for m in psych_markers)
        return psych_count < 5
    
    def _deepen_psychology(self, text: str, amount: int, context: ExpansionContext) -> str:
        """心理描写深化实现"""
        psych_templates = [
            f"{context.characters.get('protagonist', '他')}心中{random.choice(['暗自思忖', '反复盘算', '默默思索'])}：{random.choice(['这一步走得是否正确？', '接下来该如何应对？', '对方究竟有何目的？'])}。",
            f"{random.choice(['尽管表面上镇定自若', '虽然神色如常', '即便保持着微笑'])}，{context.characters.get('protagonist', '他')}的内心却{random.choice(['波涛汹涌', '思绪万千', '难以平静'])}。",
            f"{context.characters.get('protagonist', '他')}暗暗{random.choice(['下定决心', '发誓', '立下决心'])}：{random.choice(['无论如何都要完成任务。', '绝不能让信任自己的人失望。', '这一次，一定要成功。'])}。",
        ]
        
        selected = random.sample(psych_templates, min(2, len(psych_templates)))
        return "\n\n".join(selected)
    
    def _needs_action(self, text: str) -> bool:
        """判断是否需要动作细节扩充"""
        action_verbs = ['走', '跑', '跳', '打', '拿', '放', '看', '听', '站', '坐', '冲', '挥', '握', '拉']
        action_count = sum(text.count(v) for v in action_verbs)
        return action_count < 20
    
    def _detail_actions(self, text: str, amount: int, context: ExpansionContext) -> str:
        """动作细节化实现"""
        action_templates = [
            f"{context.characters.get('protagonist', '他')}{random.choice(['缓缓', '猛地', '轻轻'])}地{random.choice(['站起身', '转过身', '抬起手', '迈出一步'])}，{random.choice(['动作干净利落', '姿态从容不迫', '神情专注认真'])}。",
            f"{random.choice(['只见', '但见', '就见'])}{context.characters.get('protagonist', '他')}{random.choice(['身形一闪', '脚步轻移', '手臂一挥'])}{random.choice(['，快如闪电', '，迅疾如风', '，如行云流水般'])}地{random.choice(['完成了这个动作', '化解了危机', '达成了目的'])}。",
            f"{context.characters.get('protagonist', '他')}深吸一口气，{random.choice(['稳住身形', '调整姿态', '集中精神'])}{random.choice(['，准备迎接接下来的挑战', '，等待着最佳的时机', '，心中已有了计较'])}。",
        ]
        
        selected = random.sample(action_templates, min(2, len(action_templates)))
        return "\n\n".join(selected)
    
    def _needs_transitions(self, text: str) -> bool:
        """判断是否需要过渡平滑化"""
        transitions = ['随后', '接着', '与此同时', '不久之后', '紧接着', '然后', '这时']
        trans_count = sum(text.count(t) for t in transitions)
        return trans_count < 3
    
    def _smooth_transitions(self, text: str, amount: int, context: ExpansionContext) -> str:
        """过渡平滑化实现"""
        transition_templates = [
            f"{random.choice(['时间', '光阴', '岁月'])}在不知不觉中{random.choice(['流逝', '推移', '流转'])}，转眼间{random.choice(['已是数日过去', '已到了新的阶段', '情况又有了变化'])}。",
            f"{random.choice(['就在此时', '正当这时', '就在这个当口'])}，{random.choice(['意想不到的事情发生了', '局势突然发生了变化', '一个意外的转折出现了'])}。",
            f"{random.choice(['随着时间的推移', '渐渐地', '不知不觉间'])}，{context.characters.get('protagonist', '众人')}逐渐{random.choice(['适应了新的环境', '找到了应对的方法', '理清了事情的来龙去脉'])}。",
        ]
        
        selected = random.sample(transition_templates, min(2, len(transition_templates)))
        return "\n\n".join(selected)
    
    def _integrate_expansion(self, original: str, expansion: str) -> str:
        """将扩充内容自然融入原文"""
        if not expansion.strip():
            return original
        
        # 在合适的段落之间插入扩充内容
        paragraphs = original.split('\n\n')
        expansion_paras = expansion.split('\n\n')
        
        # 找到合适的插入点（通常是场景转换处或对话结束后）
        insert_points = []
        for i, para in enumerate(paragraphs):
            if any(marker in para for marker in ['。"', '？"', '！"', '……', '。\n']):
                insert_points.append(i)
        
        # 如果没有合适的插入点，在段落中间插入（单段也可插入）
        if not insert_points and paragraphs:
            insert_points = [len(paragraphs) // 2]
        if not paragraphs:
            return expansion
        
        # 插入扩充段落
        result = paragraphs[:]
        offset = 0
        for i, exp_para in enumerate(expansion_paras):
            if i < len(insert_points):
                insert_idx = insert_points[i] + offset + 1
                if insert_idx <= len(result):
                    result.insert(insert_idx, exp_para)
                    offset += 1
        
        return '\n\n'.join(result)
    
    def _load_template_library(self):
        """加载模板库（预留接口）"""
        # 可以在这里加载外部模板文件
        pass


# 便捷函数
def expand_chapter_content(
    text: str,
    target_chars: int,
    chapter_no: int,
    context: Dict,
    config: Optional[Dict] = None
) -> str:
    """
    便捷函数：扩充章节内容
    
    Args:
        text: 原始文本
        target_chars: 目标字数
        chapter_no: 章节号
        context: 上下文信息
        config: 可选配置
    
    Returns:
        扩充后的文本
    """
    engine = ContentExpansionEngine(config)
    expansion_context = ExpansionContext(
        chapter_no=chapter_no,
        characters=context.get('characters', {}),
        plot_line=context.get('plot_line', ''),
        previous_ending=context.get('previous_ending', ''),
        scene_setting=context.get('scene_setting', ''),
    )
    return engine.expand_content(text, target_chars, expansion_context)


# 测试代码
if __name__ == "__main__":
    # 简单测试
    test_text = "这是一个测试文本。需要扩充内容。"
    context = {
        'characters': {'protagonist': '张三'},
        'plot_line': '测试情节',
        'previous_ending': '上一章结尾',
        'scene_setting': '测试场景',
    }
    
    result = expand_chapter_content(test_text, 500, 1, context)
    print(f"原始字数: {len(test_text)}")
    print(f"扩充后字数: {len(result)}")
    print("扩充结果预览:")
    print(result[:500] + "..." if len(result) > 500 else result)
