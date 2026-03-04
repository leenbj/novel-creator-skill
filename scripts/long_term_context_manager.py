#!/usr/bin/env python3
"""Long Term Context Manager - 长期上下文管理器

解决长篇小说续写过程中的上下文丢失和连贯性问题。
实现动态上下文窗口、定期刷新机制和长期记忆管理。

作者: Claude Code
版本: 1.0.0
日期: 2025-03-02
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ChapterSummary:
    """章节摘要"""
    chapter_no: int
    title: str
    summary: str
    key_events: List[str] = field(default_factory=list)
    character_changes: Dict[str, str] = field(default_factory=dict)
    word_count: int = 0


@dataclass
class CharacterState:
    """角色状态"""
    name: str
    current_location: str = ""
    current_status: str = ""
    relationships: Dict[str, str] = field(default_factory=dict)
    recent_actions: List[str] = field(default_factory=list)
    last_updated_chapter: int = 0


@dataclass
class PlotThread:
    """情节线索"""
    thread_id: str
    description: str
    status: str  # active, resolved, suspended
    start_chapter: int
    end_chapter: Optional[int] = None
    key_chapters: List[int] = field(default_factory=list)


@dataclass
class LongTermContext:
    """长期上下文"""
    recent_chapters: List[ChapterSummary] = field(default_factory=list)
    character_states: Dict[str, CharacterState] = field(default_factory=dict)
    plot_threads: List[PlotThread] = field(default_factory=list)
    world_state: Dict[str, Any] = field(default_factory=dict)
    milestones_reached: List[int] = field(default_factory=list)


class LongTermContextManager:
    """长期上下文管理器主类"""
    
    # 里程碑章节定义
    MILESTONES = [50, 100, 150, 200]
    
    # 动态上下文窗口配置
    CONTEXT_WINDOWS = {
        "opening": (1, 10, 3),      # 开篇阶段：3章窗口
        "rising": (11, 30, 5),      # 上升阶段：5章窗口
        "climax_building": (31, 50, 7),  # 高潮铺垫：7章窗口
        "sustaining": (51, float('inf'), 10)  # 长程维持：10章窗口
    }
    
    def __init__(self, project_root: Path, max_window_size: int = 10):
        self.project_root = project_root
        self.max_window_size = max_window_size
        self.memory_dir = project_root / "00_memory"
        self.manuscript_dir = project_root / "03_manuscript"
        self.retrieval_dir = self.memory_dir / "retrieval"
        
        # 确保目录存在
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.retrieval_dir.mkdir(parents=True, exist_ok=True)
        
        # 上下文缓存
        self._context_cache: Optional[LongTermContext] = None
        self._cache_chapter: int = 0
    
    def get_context_for_chapter(self, chapter_no: int, force_refresh: bool = False) -> LongTermContext:
        """
        获取指定章节的长期上下文
        
        Args:
            chapter_no: 章节号
            force_refresh: 是否强制刷新缓存
        
        Returns:
            长期上下文对象
        """
        # 检查缓存
        if not force_refresh and self._context_cache and self._cache_chapter == chapter_no:
            return self._context_cache
        
        # 计算动态窗口大小
        window_size = self._calculate_window_size(chapter_no)
        
        # 构建上下文
        context = LongTermContext()
        
        # 1. 获取最近章节摘要
        context.recent_chapters = self._get_recent_chapter_summaries(chapter_no, window_size)
        
        # 2. 获取角色状态
        context.character_states = self._get_character_states(chapter_no)
        
        # 3. 获取情节线索
        context.plot_threads = self._get_plot_threads(chapter_no)
        
        # 4. 获取世界状态
        context.world_state = self._get_world_state(chapter_no)
        
        # 5. 检查里程碑
        context.milestones_reached = [m for m in self.MILESTONES if m < chapter_no]
        
        # 更新缓存
        self._context_cache = context
        self._cache_chapter = chapter_no
        
        return context
    
    def _calculate_window_size(self, chapter_no: int) -> int:
        """动态计算上下文窗口大小"""
        for stage, (start, end, size) in self.CONTEXT_WINDOWS.items():
            if start <= chapter_no <= end:
                return min(size, self.max_window_size)
        return self.max_window_size
    
    def _get_recent_chapter_summaries(self, chapter_no: int, window_size: int) -> List[ChapterSummary]:
        """获取最近N章的摘要"""
        summaries = []
        
        # 从 retrieval 目录读取章节元数据
        meta_dir = self.retrieval_dir / "chapter_meta"
        if not meta_dir.exists():
            # 回退到直接读取章节文件
            return self._get_chapter_summaries_from_files(chapter_no, window_size)
        
        # 读取最近章节的元数据
        for i in range(max(1, chapter_no - window_size), chapter_no):
            meta_file = meta_dir / f"chapter_{i:03d}.meta.json"
            if meta_file.exists():
                try:
                    with open(meta_file, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    
                    summary = ChapterSummary(
                        chapter_no=i,
                        title=meta.get('title', f'第{i}章'),
                        summary=meta.get('summary', ''),
                        key_events=meta.get('key_events', []),
                        character_changes=meta.get('character_changes', {}),
                        word_count=meta.get('word_count', 0)
                    )
                    summaries.append(summary)
                except Exception:
                    continue
        
        return summaries
    
    def _get_chapter_summaries_from_files(self, chapter_no: int, window_size: int) -> List[ChapterSummary]:
        """从章节文件直接提取摘要"""
        summaries = []
        
        if not self.manuscript_dir.exists():
            return summaries
        
        # 找到最近的章节文件
        for i in range(max(1, chapter_no - window_size), chapter_no):
            # 尝试多种文件名格式
            patterns = [
                f"第{i}章*.md",
                f"第{i:03d}章*.md",
                f"chapter_{i:03d}*.md"
            ]
            
            chapter_file = None
            for pattern in patterns:
                matches = list(self.manuscript_dir.glob(pattern))
                if matches:
                    chapter_file = matches[0]
                    break
            
            if chapter_file and chapter_file.exists():
                try:
                    content = chapter_file.read_text(encoding='utf-8')
                    
                    # 提取标题
                    title = chapter_file.stem.replace('-', ' ')
                    
                    # 提取摘要（取前500字）
                    clean_content = re.sub(r'#.*?\n', '', content)
                    clean_content = re.sub(r'<!--.*?-->', '', clean_content, flags=re.S)
                    clean_content = re.sub(r'\[.*?\]', '', clean_content)
                    summary = clean_content[:500].strip()
                    
                    summary_obj = ChapterSummary(
                        chapter_no=i,
                        title=title,
                        summary=summary,
                        word_count=len(clean_content)
                    )
                    summaries.append(summary_obj)
                except Exception:
                    continue
        
        return summaries
    
    def _get_character_states(self, chapter_no: int) -> Dict[str, CharacterState]:
        """获取角色状态"""
        states = {}
        
        # 尝试读取角色追踪文件
        tracker_file = self.memory_dir / "character_tracker.md"
        if not tracker_file.exists():
            return states
        
        try:
            content = tracker_file.read_text(encoding='utf-8')
            
            # 简单解析（实际可以使用更复杂的解析逻辑）
            # 这里提供一个基本的实现
            lines = content.split('\n')
            current_char = None
            
            for line in lines:
                if line.startswith('## ') or line.startswith('### '):
                    # 新角色
                    char_name = line.lstrip('#').strip()
                    if char_name:
                        current_char = char_name
                        states[current_char] = CharacterState(name=current_char)
                elif current_char and ':' in line:
                    # 角色属性
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    if current_char in states:
                        if '位置' in key or '地点' in key:
                            states[current_char].current_location = value
                        elif '状态' in key:
                            states[current_char].current_status = value
                        elif '关系' in key:
                            # 解析关系
                            if ':' in value:
                                other, relation = value.split(':', 1)
                                states[current_char].relationships[other.strip()] = relation.strip()
        
        except Exception:
            pass
        
        return states
    
    def _get_plot_threads(self, chapter_no: int) -> List[PlotThread]:
        """获取情节线索"""
        threads = []
        
        # 尝试读取伏笔追踪文件
        foreshadow_file = self.memory_dir / "foreshadowing_tracker.md"
        if not foreshadow_file.exists():
            return threads
        
        try:
            content = foreshadow_file.read_text(encoding='utf-8')
            
            # 简单解析
            lines = content.split('\n')
            thread_id = 0
            
            for line in lines:
                if line.startswith('- ') or line.startswith('* '):
                    # 情节线索
                    thread_id += 1
                    description = line.lstrip('-*').strip()
                    
                    # 确定状态
                    status = "active"
                    if '已回收' in line or '已完成' in line or '✓' in line:
                        status = "resolved"
                    elif '暂停' in line or '延后' in line:
                        status = "suspended"
                    
                    thread = PlotThread(
                        thread_id=f"thread_{thread_id}",
                        description=description,
                        status=status,
                        start_chapter=1,  # 默认值
                        key_chapters=[]
                    )
                    threads.append(thread)
        
        except Exception:
            pass
        
        return threads
    
    def _get_world_state(self, chapter_no: int) -> Dict[str, Any]:
        """获取世界状态"""
        world_state = {}
        
        # 尝试读取世界状态文件
        world_file = self.memory_dir / "world_state.md"
        if not world_file.exists():
            return world_state
        
        try:
            content = world_file.read_text(encoding='utf-8')
            
            # 简单解析
            lines = content.split('\n')
            
            for line in lines:
                if ':' in line and not line.startswith('#'):
                    key, value = line.split(':', 1)
                    world_state[key.strip()] = value.strip()
        
        except Exception:
            pass
        
        return world_state
    
    def should_refresh_context(self, chapter_no: int) -> bool:
        """判断是否需要刷新上下文"""
        # 每10章强制刷新
        if chapter_no > 50 and chapter_no % 10 == 0:
            return True
        
        # 里程碑章节刷新
        if chapter_no in self.MILESTONES:
            return True
        
        return False
    
    def get_milestone_info(self, chapter_no: int) -> Optional[Dict[str, Any]]:
        """获取里程碑信息"""
        if chapter_no not in self.MILESTONES:
            return None
        
        milestone_info = {
            50: {
                "name": "半百庆典",
                "description": "中期总结，检查进度",
                "tasks": [
                    "总结前49章的核心进展",
                    "整理主要角色的成长轨迹",
                    "检查并回收重要伏笔",
                    "设置下一阶段的关键转折"
                ]
            },
            100: {
                "name": "百章大节点",
                "description": "重大转折，开启新篇章",
                "tasks": [
                    "完成第一阶段的宏大叙事",
                    "开启全新的故事篇章",
                    "引入新的势力或角色",
                    "升级世界观或力量体系"
                ]
            },
            150: {
                "name": "后半程开启",
                "description": "加速推进，收紧线索",
                "tasks": [
                    "总结前半程的经验教训",
                    "加速剧情推进节奏",
                    "为最终高潮做铺垫",
                    "收紧所有松散的情节线"
                ]
            },
            200: {
                "name": "终局铺垫",
                "description": "准备最终高潮",
                "tasks": [
                    "启动最终篇章的倒计时",
                    "所有伏笔必须回收完毕",
                    "主要角色的最终定位",
                    "为最终决战做好准备"
                ]
            }
        }
        
        return milestone_info.get(chapter_no)
    
    def build_context_prompt(self, chapter_no: int) -> str:
        """构建上下文提示"""
        context = self.get_context_for_chapter(chapter_no)
        lines = []
        
        # 最近章节摘要
        if context.recent_chapters:
            lines.append("## 前情回顾")
            for summary in context.recent_chapters[-3:]:  # 最近3章
                lines.append(f"\n**第{summary.chapter_no}章**: {summary.summary[:200]}...")
        
        # 角色状态
        if context.character_states:
            lines.append("\n## 主要角色状态")
            for name, state in list(context.character_states.items())[:5]:  # 前5个角色
                status_parts = []
                if state.current_location:
                    status_parts.append(f"位置: {state.current_location}")
                if state.current_status:
                    status_parts.append(f"状态: {state.current_status}")
                if status_parts:
                    lines.append(f"- **{name}**: {', '.join(status_parts)}")
        
        # 情节线索
        active_threads = [t for t in context.plot_threads if t.status == "active"]
        if active_threads:
            lines.append("\n## 活跃情节线")
            for thread in active_threads[:3]:  # 前3条线索
                lines.append(f"- {thread.description}")
        
        # 里程碑信息
        milestone_info = self.get_milestone_info(chapter_no)
        if milestone_info:
            lines.append(f"\n## 🎯 里程碑章节: {milestone_info['name']}")
            lines.append(f"**{milestone_info['description']}**")
            lines.append("\n### 特殊任务:")
            for task in milestone_info['tasks']:
                lines.append(f"- {task}")
        
        return '\n'.join(lines) if lines else ""


# 便捷函数
def get_long_term_context(
    project_root: Path,
    chapter_no: int,
    max_window_size: int = 10
) -> LongTermContext:
    """
    便捷函数：获取长期上下文
    
    Args:
        project_root: 项目根目录
        chapter_no: 章节号
        max_window_size: 最大窗口大小
    
    Returns:
        长期上下文对象
    """
    manager = LongTermContextManager(project_root, max_window_size)
    return manager.get_context_for_chapter(chapter_no)


# 测试代码
if __name__ == "__main__":
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        
        # 创建测试目录结构
        (project_root / "00_memory").mkdir()
        (project_root / "03_manuscript").mkdir()
        
        # 测试不同章节的上下文窗口
        manager = LongTermContextManager(project_root)
        
        test_chapters = [5, 20, 40, 60, 100]
        
        for chapter_no in test_chapters:
            window_size = manager._calculate_window_size(chapter_no)
            print(f"第{chapter_no}章: 上下文窗口大小 = {window_size}")
            
            if manager.should_refresh_context(chapter_no):
                milestone = manager.get_milestone_info(chapter_no)
                if milestone:
                    print(f"  🎯 里程碑: {milestone['name']}")
                else:
                    print(f"  🔄 需要刷新上下文")
        
        print("\n测试完成！")