#!/usr/bin/env python3
"""
Novel Chapter Writer - 自动化小说章节生成器

功能：
1. 自动提取项目上下文（上一章、角色状态、情节线等）
2. 生成结构化的AI提示词
3. 调用外部AI API生成内容
4. 自动写入章节文件并更新记忆

作者：AI Assistant
版本：1.0.0
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# text_humanizer 按需导入（同目录下）
_HUMANIZER_AVAILABLE = False
try:
    SCRIPT_DIR_NCW = Path(__file__).resolve().parent
    if str(SCRIPT_DIR_NCW) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR_NCW))
    from text_humanizer import detect_patterns as _humanizer_detect
    _HUMANIZER_AVAILABLE = True
except Exception:
    pass

# 尝试导入可选依赖
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

# 默认配置
DEFAULT_CONFIG = {
    "ai_provider": "openai",  # openai, anthropic, local, kimi, glm, minimax
    "model": "gpt-4",
    "temperature": 0.8,
    "max_tokens": 4000,
    "min_chapter_chars": 3000,
    "target_chapter_chars": 3500,
    "context_window": 5,  # 加载前5章作为上下文
    "style_consistency": True,
    "auto_update_memory": True,
    "run_gate_check": False,
}

# ---------------------------------------------------------------------------
# 动态系统提示 - 每三章轮换侧重点，打破单一写作视角
# ---------------------------------------------------------------------------
_NOVELIST_PERSONAS: List[str] = [
    # 0: 场景沉浸型
    (
        "你是一位专注于场景沉浸感的小说家。你相信最好的章节入口是把读者扔进现场，"
        "让细节说话，让感官先于逻辑。你写作时不考虑「章节结构」，只考虑「此刻正在发生什么」。"
        "输出纯小说正文，不得夹带任何标题、注释、分析说明或写作思路。"
        "严禁出现以下AI高频词：不禁、仿佛、宛如、映入眼帘、心中暗道、目光如炬、"
        "嘴角微扬、不由自主、此时此刻、意义深远、值得一提。"
    ),
    # 1: 人物心理型
    (
        "你是一位擅长人物内心的小说家。你认为情节只是人物做出选择的容器。"
        "你最在意的是：在这一刻，这个人的脑子里转着什么？他/她的行动由内心哪个部分驱动？"
        "内心世界必须通过具体行为和场景承载，严禁出现「他感到」「她觉得」等情感旁白句式。"
        "输出纯小说正文，不含任何元说明。"
        "严禁出现：不禁、仿佛、宛如、心中暗道、不由自主、情不自禁、只见、目光如炬。"
    ),
    # 2: 张力节奏型
    (
        "你是一位节奏大师型小说家，擅长在平静中埋藏张力，在动作中透露人物本质。"
        "你知道读者的注意力是有限的，每一段都要做到承前启后，松紧交替。"
        "对话必须体现角色的不同性格与立场，禁止对话同质化。"
        "输出纯小说正文，严禁在正文内出现任何写作过程的注记或元说明。"
        "严禁出现：不禁、仿佛、宛如、映入眼帘、此时此刻、值得一提、意义深远、不容忽视。"
    ),
]


def get_system_prompt(chapter_no: int) -> str:
    """按章节号循环返回不同的小说家写作系统提示。"""
    return _NOVELIST_PERSONAS[(chapter_no - 1) % len(_NOVELIST_PERSONAS)]


@dataclass
class ProjectContext:
    """项目上下文数据类"""
    project_root: Path
    chapter_no: int
    chapter_goal: str = ""
    previous_chapters: List[Dict[str, Any]] = field(default_factory=list)
    character_tracker: Dict[str, Any] = field(default_factory=dict)
    novel_plan: Dict[str, Any] = field(default_factory=dict)
    style_anchor: Dict[str, Any] = field(default_factory=dict)
    required_elements: List[str] = field(default_factory=list)


class ConfigManager:
    """配置管理器"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.config_file = project_root / ".novel_writer_config.yaml"
        self.config = self.load_config()
    
    def load_config(self) -> Dict[str, Any]:
        """加载配置，优先级：配置文件 > 环境变量 > 默认配置"""
        config = DEFAULT_CONFIG.copy()
        
        # 从文件加载
        if self.config_file.exists():
            try:
                if HAS_YAML:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        file_config = yaml.safe_load(f)
                        if file_config:
                            config.update(file_config)
                else:
                    # 使用JSON作为备选
                    import json
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        file_config = json.load(f)
                        config.update(file_config)
            except Exception as e:
                print(f"[警告] 加载配置文件失败: {e}")
        
        # 从环境变量加载
        env_mappings = {
            'NOVEL_AI_PROVIDER': 'ai_provider',
            'NOVEL_AI_MODEL': 'model',
            'OPENAI_API_KEY': 'openai_api_key',
            'ANTHROPIC_API_KEY': 'anthropic_api_key',
        }
        
        for env_var, config_key in env_mappings.items():
            value = os.getenv(env_var)
            if value:
                config[config_key] = value
        
        return config
    
    def save_config(self):
        """保存配置到文件"""
        try:
            if HAS_YAML:
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)
            else:
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, ensure_ascii=False, indent=2)
            print(f"[信息] 配置已保存到: {self.config_file}")
        except Exception as e:
            print(f"[错误] 保存配置失败: {e}")


class ContextExtractor:
    """上下文提取器"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.memory_dir = project_root / "00_memory"
        self.manuscript_dir = project_root / "03_manuscript"
        self.kb_dir = project_root / "02_knowledge_base"
    
    def extract_chapter_number(self, chapter_file: Path) -> int:
        """从章节文件名提取章节号，返回0表示未知"""
        match = re.search(r'第(\d+)章', chapter_file.name)
        if match:
            return int(match.group(1))
        return 0  # 返回0表示未知，让调用者处理
    
    def extract_chapter_goal(self, chapter_file: Path) -> str:
        """从占位章节提取目标"""
        if not chapter_file.exists():
            return "推进剧情发展"
        
        content = chapter_file.read_text(encoding='utf-8', errors='ignore')
        
        # 尝试提取本章目标
        goal_match = re.search(r'##?\s*本章目标\s*\n+([\s\S]+?)(?=##|\Z)', content)
        if goal_match:
            return goal_match.group(1).strip()
        
        # 尝试提取场景草图中的目标
        scene_match = re.search(r'-\s*章末钩子：(.+)', content)
        if scene_match:
            return f"完成章节目标，引出：{scene_match.group(1).strip()}"
        
        return "推进剧情发展"
    
    def get_previous_chapters(self, current_chapter_no: int, context_window: int = 5) -> List[Dict[str, Any]]:
        """获取前几章作为上下文"""
        chapters = []
        
        for i in range(max(1, current_chapter_no - context_window), current_chapter_no):
            # 查找章节文件
            chapter_files = list(self.manuscript_dir.glob(f"第{i}章*.md"))
            if not chapter_files:
                continue
            
            chapter_file = chapter_files[0]
            content = chapter_file.read_text(encoding='utf-8', errors='ignore')
            
            # 提取正文部分（移除Markdown标题和注释）
            lines = content.split('\n')
            body_lines = []
            for line in lines:
                # 跳过标题行和注释
                if line.startswith('#') or line.startswith('<!--'):
                    continue
                body_lines.append(line)
            
            body = '\n'.join(body_lines).strip()
            
            # 提取最后500字作为摘要
            body_clean = re.sub(r'\s+', '', body)
            if len(body_clean) > 500:
                # 找到大约最后500字的位置
                char_count = 0
                pos = len(body)
                for i in range(len(body) - 1, -1, -1):
                    if not body[i].isspace():
                        char_count += 1
                    if char_count >= 500:
                        pos = i
                        break
                summary = body[pos:]
            else:
                summary = body
            
            chapters.append({
                'chapter_no': i,
                'file': str(chapter_file),
                'summary': summary[:1000],  # 限制长度
            })
        
        return chapters
    
    def get_character_tracker(self) -> Dict[str, Any]:
        """获取角色追踪信息"""
        tracker_file = self.memory_dir / "character_tracker.md"
        if not tracker_file.exists():
            return {}
        
        content = tracker_file.read_text(encoding='utf-8', errors='ignore')
        
        # 解析角色信息
        characters = {}
        current_character = None
        
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 检查是否是角色名（表格格式）
            if line.startswith('|') and not line.startswith('|-'):
                cells = [c.strip() for c in line.split('|')[1:-1]]
                if cells and cells[0] and cells[0] not in ['人物', '角色', '姓名']:
                    current_character = cells[0]
                    characters[current_character] = {
                        'name': cells[0],
                        'info': cells[1:] if len(cells) > 1 else [],
                    }
        
        return characters
    
    def get_novel_plan(self) -> Dict[str, Any]:
        """获取小说规划信息"""
        plan_file = self.memory_dir / "novel_plan.md"
        if not plan_file.exists():
            return {}
        
        content = plan_file.read_text(encoding='utf-8', errors='ignore')
        
        # 提取卷/幕结构
        volumes = []
        current_volume = None
        current_arc = None
        
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 检测卷标题
            if line.startswith('#') and ('卷' in line or '起' in line or '承' in line):
                current_volume = {
                    'title': line.lstrip('#').strip(),
                    'arcs': [],
                }
                volumes.append(current_volume)
            
            # 检测幕/情节线
            elif line.startswith('##') or line.startswith('- ') or line.startswith('* '):
                if current_volume:
                    arc_title = line.lstrip('-*#').strip()
                    current_volume['arcs'].append(arc_title)
        
        return {
            'volumes': volumes,
            'raw_content': content[:2000],  # 保留原始内容的前2000字
        }
    
    def get_style_anchor(self) -> Dict[str, Any]:
        """获取风格锚点信息"""
        style_file = self.memory_dir / "style_anchor.md"
        if not style_file.exists():
            return {}
        
        content = style_file.read_text(encoding='utf-8', errors='ignore')
        
        # 提取风格要素
        style_info = {}
        
        # 解析叙事视角（兼容 "视角：" 和旧版 "叙述视角：" 两种格式）
        perspective_match = (
            re.search(r'(?<!叙述)视角[：:]\s*(.+)', content)
            or re.search(r'叙述视角[：:]\s*(.+)', content)
        )
        if perspective_match:
            style_info['perspective'] = perspective_match.group(1).strip()

        # 解析句式特点（兼容 "句式：" 和旧版 "平均句长" 格式）
        sentence_match = re.search(r'句式[：:]\s*(.+)', content)
        if sentence_match:
            style_info['sentence_pattern'] = sentence_match.group(1).strip()
        else:
            avg_match = re.search(r'平均句长约?\s*(\d+)\s*字', content)
            if avg_match:
                style_info['sentence_pattern'] = f"平均句长约 {avg_match.group(1)} 字"

        # 解析对话风格（兼容 "对话：" 格式）
        dialogue_match = re.search(r'对话[：:]\s*(.+)', content)
        if dialogue_match:
            style_info['dialogue_style'] = dialogue_match.group(1).strip()
        
        # 保留原始内容
        style_info['raw_content'] = content[:1500]
        
        return style_info
    
    def extract_context(self, chapter_file: Path, context_window: int = 5) -> ProjectContext:
        """提取完整的项目上下文"""
        chapter_no = self.extract_chapter_number(chapter_file)
        chapter_goal = self.extract_chapter_goal(chapter_file)
        
        return ProjectContext(
            project_root=self.project_root,
            chapter_no=chapter_no,
            chapter_goal=chapter_goal,
            previous_chapters=self.get_previous_chapters(chapter_no, context_window),
            character_tracker=self.get_character_tracker(),
            novel_plan=self.get_novel_plan(),
            style_anchor=self.get_style_anchor(),
        )


class PromptGenerator:
    """动态章节创作简报生成器。

    用 8 种叙事切入模式替代固定模板结构，确保每章获得不同的写作入口框架，
    从根本上消除「每章结构类似」的问题。所有必要信息（任务、角色、上下文、
    风格）依然完整传递，但以自然语言简报方式呈现，而非带标签的模板填充。
    """

    # 8 种入口模式，按章节号循环选取
    _ENTRY_MODES: List[str] = [
        "action_pivot",       # 从正在发生的动作中切入
        "dialogue_opening",   # 从人物开口的瞬间切入
        "sensory_anchor",     # 从一个具体感官细节切入
        "interior_moment",    # 从角色内心某个清晰念头切入
        "consequence_first",  # 从上一章后果的余韵切入
        "environment_shift",  # 从场景/天气/时间变化切入
        "close_observation",  # 从一个微小观察细节切入
        "collision_setup",    # 从即将到来的碰撞布局切入
    ]

    def __init__(self, context: ProjectContext):
        self.ctx = context

    def generate_prompt(self) -> str:
        """按章节号选取入口模式，返回该模式的创作简报。"""
        mode_idx = (self.ctx.chapter_no - 1) % len(self._ENTRY_MODES)
        mode = self._ENTRY_MODES[mode_idx]
        builder = getattr(self, f"_build_{mode}")
        return builder()
    
    # ------------------------------------------------------------------
    # 辅助数据提取方法
    # ------------------------------------------------------------------

    def _prev_tail(self) -> str:
        """取上一章结尾约 400 字。"""
        if not self.ctx.previous_chapters:
            return ""
        return self.ctx.previous_chapters[-1].get("summary", "")[-400:]

    def _opening_hint(self) -> str:
        """如果是开篇第一章，返回特殊提示。"""
        if not self.ctx.previous_chapters and self.ctx.chapter_no <= 1:
            return "这是全书第一章，需要建立世界观、引出主角、埋下核心矛盾。"
        return ""

    def _chars_brief(self) -> str:
        """返回最多 4 个角色的简短描述。"""
        if not self.ctx.character_tracker:
            return "（暂无角色档案）"
        parts: List[str] = []
        for name, info in list(self.ctx.character_tracker.items())[:4]:
            extras = " | ".join(info.get("info", [])[:2]) if info.get("info") else ""
            parts.append(f"{name}（{extras}）" if extras else name)
        return "；".join(parts)

    def _plan_excerpt(self) -> str:
        """返回小说规划前 300 字。"""
        raw = self.ctx.novel_plan.get("raw_content", "")
        return raw[:300] if raw else "（无规划文件）"

    def _style_note(self) -> str:
        """返回风格锚点摘要。"""
        s = self.ctx.style_anchor
        if not s:
            return "第三人称有限视角；长短句交错；对话自然口语化"
        parts: List[str] = []
        if s.get("perspective"):
            parts.append(f"视角：{s['perspective']}")
        if s.get("sentence_pattern"):
            parts.append(f"句式：{s['sentence_pattern']}")
        if s.get("dialogue_style"):
            parts.append(f"对话：{s['dialogue_style']}")
        return "；".join(parts) or "第三人称有限视角"

    def _target_chars(self) -> int:
        return self.ctx.novel_plan.get("target_chars", 3500) or 3500

    def _hard_rules(self) -> str:
        return (
            "输出纯小说正文。不得在正文中出现任何写作分析、角色定位说明、"
            "创作思路注记、标题行或 Markdown 标记。"
            "对话必须体现各角色的不同性格，不允许对话同质化。"
        )

    # ------------------------------------------------------------------
    # 8 种入口模式
    # ------------------------------------------------------------------

    def _build_action_pivot(self) -> str:
        opening = self._opening_hint()
        prev = self._prev_tail()
        chars = self._chars_brief()
        plan = self._plan_excerpt()
        style = self._style_note()
        target = self._target_chars()
        lines: List[str] = []
        if opening:
            lines.append(opening)
        lines.append(f"本章写作任务：{self.ctx.chapter_goal}")
        if prev:
            lines.append(f"前文刚刚发生了：{prev}")
        lines.append(f"当前在场人物：{chars}")
        lines.append(f"本章在全局剧情中的坐标：{plan}")
        lines.append(f"文风锚点：{style}")
        lines.append(f"字数要求：{target} 字以上。")
        lines.append(
            "从一个正在运动中的动作切入——手的动作、脚步节奏、"
            "呼吸变化或某个物件被触碰的瞬间。场景和关系通过动作呈现，"
            "不做任何总结性描述。"
        )
        lines.append(self._hard_rules())
        return "\n\n".join(lines)

    def _build_dialogue_opening(self) -> str:
        opening = self._opening_hint()
        prev = self._prev_tail()
        chars = self._chars_brief()
        plan = self._plan_excerpt()
        style = self._style_note()
        target = self._target_chars()
        lines: List[str] = []
        if opening:
            lines.append(opening)
        lines.append(f"这一章需要完成：{self.ctx.chapter_goal}")
        lines.append(f"人物群像：{chars}")
        if prev:
            lines.append(f"从上一章衔接：{prev}")
        lines.append(f"叙事所处阶段：{plan}")
        lines.append(f"惯用笔法：{style}")
        lines.append(f"字数要求：{target} 字左右。")
        lines.append(
            "让某个人物开口说话，作为本章第一句正文。"
            "通过这句话和紧随其后的反应，建立当下场域中的张力与关系。"
            "对话标签简洁，各角色说话风格必须有辨识度差异。"
        )
        lines.append(self._hard_rules())
        return "\n\n".join(lines)

    def _build_sensory_anchor(self) -> str:
        opening = self._opening_hint()
        prev = self._prev_tail()
        chars = self._chars_brief()
        plan = self._plan_excerpt()
        style = self._style_note()
        target = self._target_chars()
        lines: List[str] = []
        if opening:
            lines.append(opening)
        lines.append(f"章节任务：{self.ctx.chapter_goal}")
        lines.append(f"人物与处境：{chars}")
        if prev:
            lines.append(f"前情简要：{prev}")
        lines.append(f"全局剧情节奏：{plan}")
        lines.append(f"文风锚点：{style}")
        lines.append(f"正文须达到 {target} 字以上。")
        lines.append(
            "以一个具体的感官细节打开这一章的空间——某种气味、"
            "某种触感、某个特定的声响或温度。不依赖概括，"
            "让读者的感觉先到，认知后到。"
        )
        lines.append(self._hard_rules())
        return "\n\n".join(lines)

    def _build_interior_moment(self) -> str:
        opening = self._opening_hint()
        prev = self._prev_tail()
        chars = self._chars_brief()
        plan = self._plan_excerpt()
        style = self._style_note()
        target = self._target_chars()
        lines: List[str] = []
        if opening:
            lines.append(opening)
        lines.append(f"本章写作目标：{self.ctx.chapter_goal}")
        lines.append(f"相关人物：{chars}")
        if prev:
            lines.append(f"上章结尾的余韵：{prev}")
        lines.append(f"剧情全局位置：{plan}")
        lines.append(f"写作风格：{style}")
        lines.append(f"本章字数要求：约 {target} 字。")
        lines.append(
            "进入一个人物内心在此刻清晰闪过的念头或决定——不是总结式的，"
            "是具体的此时此地的想法，通过行为和场景承载，"
            "不出现「他感到」「她觉得」等情感旁白句式。"
        )
        lines.append(self._hard_rules())
        return "\n\n".join(lines)

    def _build_consequence_first(self) -> str:
        opening = self._opening_hint()
        prev = self._prev_tail()
        chars = self._chars_brief()
        plan = self._plan_excerpt()
        style = self._style_note()
        target = self._target_chars()
        lines: List[str] = []
        if opening:
            lines.append(opening)
        lines.append(f"第 {self.ctx.chapter_no} 章的剧情任务：{self.ctx.chapter_goal}")
        if prev:
            lines.append(f"上一章留下的局面：{prev}")
        lines.append(f"现在在场的人：{chars}")
        lines.append(f"整体故事进展：{plan}")
        lines.append(f"文风：{style}")
        lines.append(f"字数：约 {target} 字。")
        lines.append(
            "从上一章事件的后续余波写起，人物仍在消化刚刚发生的事情。"
            "让结果先于原因出现——读者跟着人物一起理解正在经历什么，"
            "不提前解释，不总结刚才发生了什么。"
        )
        lines.append(self._hard_rules())
        return "\n\n".join(lines)

    def _build_environment_shift(self) -> str:
        opening = self._opening_hint()
        prev = self._prev_tail()
        chars = self._chars_brief()
        plan = self._plan_excerpt()
        style = self._style_note()
        target = self._target_chars()
        lines: List[str] = []
        if opening:
            lines.append(opening)
        lines.append(f"本章写作要点：{self.ctx.chapter_goal}")
        lines.append(f"场景中的人物：{chars}")
        if prev:
            lines.append(f"前文情况：{prev}")
        lines.append(f"叙事节奏节点：{plan}")
        lines.append(f"文风参照：{style}")
        lines.append(f"目标字数：{target} 字。")
        lines.append(
            "从场景本身的某个变化打开——时间推移、天色转换、"
            "温度骤降或某个建筑/地形的新细节。"
            "世界状态的变化映照人物的内在状态，但不做显性类比。"
        )
        lines.append(self._hard_rules())
        return "\n\n".join(lines)

    def _build_close_observation(self) -> str:
        opening = self._opening_hint()
        prev = self._prev_tail()
        chars = self._chars_brief()
        plan = self._plan_excerpt()
        style = self._style_note()
        target = self._target_chars()
        lines: List[str] = []
        if opening:
            lines.append(opening)
        lines.append(f"章节目标：{self.ctx.chapter_goal}")
        lines.append(f"涉及角色：{chars}")
        if prev:
            lines.append(f"上章结尾：{prev}")
        lines.append(f"整体剧情坐标：{plan}")
        lines.append(f"写作风格：{style}")
        lines.append(f"本章字数：{target} 字以上。")
        lines.append(
            "从一个微小的观察细节切入——某人手上的无意识动作、"
            "桌上的某件物品、墙缝里漏进来的光或某个不合时宜的声音。"
            "这个细节是整章情绪或冲突的缩影，但不要直接解释，让画面自己说话。"
        )
        lines.append(self._hard_rules())
        return "\n\n".join(lines)

    def _build_collision_setup(self) -> str:
        opening = self._opening_hint()
        prev = self._prev_tail()
        chars = self._chars_brief()
        plan = self._plan_excerpt()
        style = self._style_note()
        target = self._target_chars()
        lines: List[str] = []
        if opening:
            lines.append(opening)
        lines.append(f"本章关键任务：{self.ctx.chapter_goal}")
        lines.append(f"人物状态：{chars}")
        if prev:
            lines.append(f"从上章到本章：{prev}")
        lines.append(f"剧情全局：{plan}")
        lines.append(f"文笔风格：{style}")
        lines.append(f"字数要求：约 {target} 字。")
        lines.append(
            "本章有一个即将到来的碰撞或摊牌——先写碰撞之前那段时间里的"
            "气氛积压、人物的准备动作和各自的心理活动。"
            "让读者感受到压力在积聚，但不要过早引爆。"
            "结尾由剧情的实际进展决定，不强制设置钩子或总结。"
        )
        lines.append(self._hard_rules())
        return "\n\n".join(lines)


class AIProvider:
    """AI服务提供基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """生成内容，子类必须实现"""
        raise NotImplementedError


class OpenAIProvider(AIProvider):
    """OpenAI API提供者"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        if not HAS_OPENAI:
            raise ImportError(
                "OpenAI SDK 导入失败\n"
                "请检查:\n"
                "  1) 已安装 openai 包 (pip install openai)\n"
                "  2) Python 环境正确\n"
                "  3) 无版本冲突 (pip check)"
            )
        
        api_key = config.get('openai_api_key') or os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("需要提供OpenAI API Key")
        
        self.client = openai.OpenAI(api_key=api_key)
        self.model = config.get('model', 'gpt-4')
        self.temperature = config.get('temperature', 0.8)
        self.max_tokens = config.get('max_tokens', 4000)
    
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """调用OpenAI API生成内容"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            return response.choices[0].message.content
        except Exception as e:
            raise RuntimeError(f"OpenAI API调用失败: {e}")


class AnthropicProvider(AIProvider):
    """Anthropic Claude API提供者"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        if not HAS_ANTHROPIC:
            raise ImportError(
                "Anthropic SDK 导入失败\n"
                "请检查:\n"
                "  1) 已安装 anthropic 包 (pip install anthropic)\n"
                "  2) Python 环境正确\n"
                "  3) 无版本冲突 (pip check)"
            )
        
        api_key = config.get('anthropic_api_key') or os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError("需要提供Anthropic API Key")
        
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = config.get('model', 'claude-3-sonnet-20240229')
        self.temperature = config.get('temperature', 0.8)
        self.max_tokens = config.get('max_tokens', 4000)
    
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """调用Claude API生成内容"""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )
            return response.content[0].text
        except Exception as e:
            raise RuntimeError(f"Anthropic API调用失败: {e}")


class LocalProvider(AIProvider):
    """本地模型提供者（通过Ollama或其他本地API）"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_url = config.get('local_api_url', 'http://localhost:11434/api/generate')
        self.model = config.get('model', 'llama2')
    
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """调用本地API生成内容"""
        import urllib.request
        import json
        
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        
        data = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False,
        }
        
        try:
            req = urllib.request.Request(
                self.api_url,
                data=json.dumps(data).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=300) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result.get('response', '')
                
        except Exception as e:
            raise RuntimeError(f"本地API调用失败: {e}")


class OpenAICompatibleProvider(AIProvider):
    """通用 OpenAI 兼容 API 提供者（Kimi/GLM/MiniMax 等）。

    Kimi 2.5 (Moonshot)、GLM-5 (智谱)、MiniMax 2.5 均提供 OpenAI 兼容 API，
    通过 base_url 切换即可。
    """

    PRESETS = {
        "kimi": {
            "base_url": "https://api.moonshot.cn/v1",
            "default_model": "moonshot-v1-auto",
            "env_key": "MOONSHOT_API_KEY",
        },
        "glm": {
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "default_model": "glm-4-plus",
            "env_key": "GLM_API_KEY",
        },
        "minimax": {
            "base_url": "https://api.minimax.chat/v1",
            "default_model": "MiniMax-Text-01",
            "env_key": "MINIMAX_API_KEY",
        },
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        provider = config.get("ai_provider", "")
        preset = self.PRESETS.get(provider, {})

        base_url = config.get("base_url") or preset.get("base_url", "")
        api_key = (
            config.get(f"{provider}_api_key")
            or os.getenv(preset.get("env_key", ""))
            or config.get("api_key", "")
        )
        if not api_key:
            raise ValueError(f"需要提供 {provider} API Key（环境变量 {preset.get('env_key', 'UNKNOWN')} 或 --api-key）")

        self.base_url = base_url
        self.api_key = api_key
        self.model = config.get("model") or preset.get("default_model", "")
        self.temperature = config.get("temperature", 0.8)
        self.max_tokens = config.get("max_tokens", 4000)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """调用 OpenAI 兼容 API 生成内容。"""
        import urllib.request
        import json as _json

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        try:
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=_json.dumps(data).encode("utf-8"),
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = _json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"{self.config.get('ai_provider', 'unknown')} API 调用失败: {e}")


def create_ai_provider(config: Dict[str, Any]) -> AIProvider:
    """工厂函数：根据配置创建对应的AI提供者"""
    provider = config.get('ai_provider', 'openai')

    if provider == 'openai':
        return OpenAIProvider(config)
    elif provider == 'anthropic':
        return AnthropicProvider(config)
    elif provider == 'local':
        return LocalProvider(config)
    elif provider in OpenAICompatibleProvider.PRESETS:
        return OpenAICompatibleProvider(config)
    elif config.get('base_url'):
        # 自定义 OpenAI 兼容 API
        return OpenAICompatibleProvider(config)
    else:
        raise ValueError(f"不支持的AI提供者: {provider}。支持: openai, anthropic, local, kimi, glm, minimax, 或指定 base_url")


def count_chinese_chars(text: str) -> int:
    """统计中文字符数（不含标点和空格）"""
    # 匹配中文字符
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    return len(chinese_chars)


def save_chapter_content(chapter_file: Path, content: str, config: Dict[str, Any]):
    """保存章节内容到文件"""
    # 确保目录存在
    chapter_file.parent.mkdir(parents=True, exist_ok=True)
    
    # 读取现有内容（如果有）
    existing_content = ""
    if chapter_file.exists():
        existing_content = chapter_file.read_text(encoding='utf-8', errors='ignore')
    
    # 提取标题（如果存在）
    title_match = re.search(r'^#\s+(.+)$', existing_content, re.MULTILINE)
    title = title_match.group(1) if title_match else chapter_file.stem.replace('-', ' ')
    
    # 构建新内容
    new_content = f"# {title}\n\n"
    
    # 保留原有的目标/草图部分（如果有）
    goal_match = re.search(r'##\s*本章目标[\s\S]*?(?=##|\Z)', existing_content)
    if goal_match:
        new_content += goal_match.group(0) + "\n\n"
    
    scene_match = re.search(r'##\s*场景草图[\s\S]*?(?=##|\Z)', existing_content)
    if scene_match:
        new_content += scene_match.group(0) + "\n\n"
    
    # 添加生成的正文
    new_content += "## 正文\n\n"
    new_content += content.strip()
    new_content += "\n"
    
    # 写入文件
    chapter_file.write_text(new_content, encoding='utf-8')
    print(f"[信息] 章节内容已保存到: {chapter_file}")
    
    # 字数统计
    char_count = count_chinese_chars(content)
    print(f"[信息] 正文字数: {char_count}字")


def update_memory_files(project_root: Path, chapter_no: int, content: str, context: ProjectContext):
    """更新记忆文件"""
    memory_dir = project_root / "00_memory"
    
    # 更新章节摘要
    try:
        # 生成章节摘要（可以简化，取前500字）
        summary = content[:500] + "..." if len(content) > 500 else content
        
        # 保存到最近摘要
        recent_file = memory_dir / "chapter_summaries" / "recent.md"
        recent_file.parent.mkdir(parents=True, exist_ok=True)
        
        timestamp = time.strftime("%Y-%m-%d %H:%M")
        entry = f"\n## 第{chapter_no}章 - {timestamp}\n\n{summary}\n\n---\n"
        
        # 追加到文件
        with open(recent_file, 'a', encoding='utf-8') as f:
            f.write(entry)
        
        print(f"[信息] 已更新章节摘要: {recent_file}")
        
    except Exception as e:
        print(f"[警告] 更新章节摘要失败: {e}")
    
    # 更新novel_state
    try:
        state_file = memory_dir / "novel_state.md"
        if state_file.exists():
            content_old = state_file.read_text(encoding='utf-8', errors='ignore')
            # 更新当前章节进度
            content_new = re.sub(
                r'当前章节[：:]\s*\d+',
                f'当前章节：第{chapter_no}章',
                content_old
            )
            state_file.write_text(content_new, encoding='utf-8')
            print(f"[信息] 已更新小说状态: {state_file}")
    except Exception as e:
        print(f"[警告] 更新小说状态失败: {e}")


def _run_humanizer_pass(
    provider: "AIProvider",
    text: str,
    detection: Dict[str, Any],
    system_prompt: str,
) -> str:
    """基于检测结果生成二次润色 prompt，调用 AI 执行，返回润色后文本。

    只针对检测到的具体问题生成精准修改指令，不做大规模重写。
    """
    hits: List[str] = []

    # 收集高频 AI 词汇命中
    for item in detection.get("vocab_hits", [])[:8]:
        phrase = item.get("phrase", "")
        count = item.get("count", 0)
        if phrase and count:
            hits.append(f"「{phrase}」出现 {count} 次，需替换或删除")

    # 弱化副词密度
    adverb_density = detection.get("weak_adverb_density", 0)
    if adverb_density > 3:
        hits.append(f"弱化副词（微微/淡淡/缓缓等）密度 {adverb_density:.1f}/千字，需削减")

    # 段落首句总结模式
    summary_hits = detection.get("para_summary_hits", [])
    if summary_hits:
        hits.append(f"段落首句总结套话：{', '.join(summary_hits[:3])}，需改为具体描写")

    # 对话同质化
    if detection.get("dialogue_monotone"):
        hits.append("对话标签单一/对话风格同质化，需让各角色说话有明显差异")

    if not hits:
        return text  # 无具体问题，不润色

    hit_summary = "\n".join(f"- {h}" for h in hits)

    humanizer_prompt = (
        "以下是一段小说正文，需要针对以下具体问题进行最小化修改：\n\n"
        f"{hit_summary}\n\n"
        "修改规则：\n"
        "1. 只改有问题的部分，其余文字一字不动\n"
        "2. 被替换的 AI 词汇改为符合语境的具体描写或动作\n"
        "3. 对话同质化问题：根据角色性格调整说话方式\n"
        "4. 不改变情节内容、人物行为或剧情走向\n"
        "5. 输出完整修改后的正文，不加任何说明\n\n"
        f"原文：\n{text}"
    )

    humanizer_system = (
        "你是专业文字编辑。接收小说正文和修改清单，"
        "执行最小化精准修改后输出完整正文。"
        "不输出任何说明、注释或修改记录，只输出修改后的小说正文。"
    )

    try:
        return provider.generate(humanizer_system, humanizer_prompt)
    except Exception:
        return text  # 润色失败，返回原文


def write_chapter(
    project_root: Path,
    chapter_file: Optional[Path] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    context_window: int = 5,
) -> Dict[str, Any]:
    """自动写作入口，可被外部脚本（如 auto_novel_writer.py）调用。

    Args:
        project_root: 项目根目录
        chapter_file: 章节文件路径（None 则自动检测）
        config_overrides: 配置覆盖
        dry_run: 只生成提示词不调用 AI
        context_window: 上下文窗口大小

    Returns:
        {"ok": bool, "chapter_file": str, "chars": int, "prompt": str (if dry_run), ...}
    """
    config_manager = ConfigManager(project_root)
    config = config_manager.config
    if config_overrides:
        config.update(config_overrides)
    config['context_window'] = context_window

    manuscript_dir = project_root / "03_manuscript"

    # 确定章节文件
    if chapter_file is None:
        if not manuscript_dir.exists():
            return {"ok": False, "error": f"手稿目录不存在: {manuscript_dir}"}

        chapter_files = list(manuscript_dir.glob("第*章*.md"))
        chapter_files.sort(key=lambda p: p.name)

        chapter_file = None
        for cf in reversed(chapter_files):
            content = cf.read_text(encoding='utf-8', errors='ignore')
            if '[待写]' in content or '<!-- NOVEL_FLOW_STUB -->' in content:
                chapter_file = cf
                break

        if not chapter_file:
            if chapter_files:
                latest = chapter_files[-1]
                match = re.search(r'第(\d+)章', latest.name)
                if match:
                    next_no = int(match.group(1)) + 1
                    chapter_file = manuscript_dir / f"第{next_no}章-待写.md"
                else:
                    chapter_file = manuscript_dir / "第1章-开篇.md"
            else:
                chapter_file = manuscript_dir / "第1章-开篇.md"

    # 提取上下文
    extractor = ContextExtractor(project_root)
    context = extractor.extract_context(chapter_file, context_window)

    # 生成提示词
    prompt_generator = PromptGenerator(context)
    full_prompt = prompt_generator.generate_prompt()
    system_prompt = get_system_prompt(context.chapter_no)

    if dry_run:
        return {
            "ok": True,
            "chapter_file": str(chapter_file),
            "prompt": full_prompt,
            "system_prompt": system_prompt,
            "entry_mode": PromptGenerator._ENTRY_MODES[
                (context.chapter_no - 1) % len(PromptGenerator._ENTRY_MODES)
            ],
            "chapter_no": context.chapter_no,
        }

    # 调用 AI 生成
    try:
        provider = create_ai_provider(config)
        generated_content = provider.generate(system_prompt, full_prompt)

        if not generated_content or len(generated_content) < 100:
            return {"ok": False, "error": "生成内容太短或为空"}

        # --- Humanizer 自动后处理 ---
        ai_score_before = 0.0
        ai_score_after = 0.0
        humanizer_applied = False
        if _HUMANIZER_AVAILABLE and not config.get("skip_humanizer", False):
            try:
                detection = _humanizer_detect(generated_content)
                ai_score_before = float(detection.get("ai_score", 0))
                if ai_score_before > 25:
                    print(
                        f"[人性化] AI痕迹分数 {ai_score_before:.1f}，"
                        "启动自动二次润色..."
                    )
                    humanized = _run_humanizer_pass(
                        provider, generated_content, detection, system_prompt
                    )
                    if humanized and len(humanized) > len(generated_content) * 0.6:
                        detection2 = _humanizer_detect(humanized)
                        ai_score_after = float(detection2.get("ai_score", 0))
                        # 只有润色后分数确实下降才采用
                        if ai_score_after < ai_score_before:
                            generated_content = humanized
                            humanizer_applied = True
                            print(
                                f"[人性化] 润色完成：{ai_score_before:.1f} → "
                                f"{ai_score_after:.1f}"
                            )
                        else:
                            print(
                                f"[人性化] 润色后分数未改善"
                                f"({ai_score_after:.1f})，保留原文。"
                            )
            except Exception as _he:
                print(f"[人性化] 跳过（{_he}）")

        chinese_chars = count_chinese_chars(generated_content)
        save_chapter_content(chapter_file, generated_content, config)

        if config.get("auto_update_memory", True):
            update_memory_files(
                project_root, context.chapter_no, generated_content, context
            )

        result: Dict[str, Any] = {
            "ok": True,
            "chapter_file": str(chapter_file),
            "chars": chinese_chars,
            "chapter_no": context.chapter_no,
            "provider": config.get("ai_provider"),
            "model": config.get("model"),
            "entry_mode": PromptGenerator._ENTRY_MODES[
                (context.chapter_no - 1) % len(PromptGenerator._ENTRY_MODES)
            ],
        }
        if _HUMANIZER_AVAILABLE:
            result["ai_score_before"] = ai_score_before
            result["ai_score_after"] = ai_score_after if humanizer_applied else ai_score_before
            result["humanizer_applied"] = humanizer_applied
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="小说章节自动化生成器 - 提取上下文、生成提示词、调用AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 基础用法（自动生成提示词并调用AI）
  python novel_chapter_writer.py --project-root ./my_novel

  # 只生成提示词，不调用AI（用于手动复制到ChatGPT/Claude）
  python novel_chapter_writer.py --project-root ./my_novel --dry-run

  # 指定章节文件
  python novel_chapter_writer.py --project-root ./my_novel --chapter-file ./my_novel/03_manuscript/第5章-待写.md

  # 使用Claude API
  python novel_chapter_writer.py --project-root ./my_novel --provider anthropic --api-key YOUR_KEY
        """
    )
    
    # 必需参数
    parser.add_argument('--project-root', '-p', required=True,
                        help='项目根目录路径')
    
    # 可选参数
    parser.add_argument('--chapter-file', '-c',
                        help='章节文件路径（自动检测最新章节）')
    parser.add_argument('--dry-run', '-d', action='store_true',
                        help='只生成提示词，不调用AI')
    parser.add_argument('--save-prompt', '-s',
                        help='保存生成的提示词到文件')
    parser.add_argument('--context-window', type=int, default=5,
                        help='加载前几章作为上下文（默认5）')
    
    # AI配置
    parser.add_argument('--provider', choices=['openai', 'anthropic', 'local', 'kimi', 'glm', 'minimax'],
                        help='AI提供商（覆盖配置）')
    parser.add_argument('--model',
                        help='模型名称（覆盖配置）')
    parser.add_argument('--api-key',
                        help='API密钥（覆盖配置和环境变量）')
    parser.add_argument('--temperature', type=float,
                        help='生成温度（覆盖配置）')
    
    # 其他选项
    parser.add_argument('--no-update-memory', action='store_true',
                        help='不自动更新记忆文件')
    parser.add_argument('--run-gate-check', action='store_true',
                        help='生成后运行门禁检查')
    parser.add_argument('--config', '-f',
                        help='指定配置文件路径')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='显示详细信息')
    
    args = parser.parse_args()
    
    # 初始化
    project_root = Path(args.project_root).expanduser().resolve()
    
    if not project_root.exists():
        print(f"[错误] 项目目录不存在: {project_root}")
        sys.exit(1)
    
    # 加载配置
    config_manager = ConfigManager(project_root)
    config = config_manager.config
    
    # 命令行参数覆盖配置
    if args.provider:
        config['ai_provider'] = args.provider
    if args.model:
        config['model'] = args.model
    if args.api_key:
        if config['ai_provider'] == 'openai':
            config['openai_api_key'] = args.api_key
        elif config['ai_provider'] == 'anthropic':
            config['anthropic_api_key'] = args.api_key
        else:
            config['api_key'] = args.api_key
    if args.temperature is not None:
        config['temperature'] = args.temperature
    if args.context_window:
        config['context_window'] = args.context_window
    
    # 确定章节文件
    manuscript_dir = project_root / "03_manuscript"
    
    if args.chapter_file:
        chapter_file = Path(args.chapter_file).expanduser().resolve()
    else:
        # 自动检测最新的占位章节
        if not manuscript_dir.exists():
            print(f"[错误] 手稿目录不存在: {manuscript_dir}")
            sys.exit(1)
        
        # 查找包含待写标记的章节
        chapter_files = list(manuscript_dir.glob("第*章*.md"))
        chapter_files.sort(key=lambda p: p.name)  # 按名称排序
        
        chapter_file = None
        for cf in reversed(chapter_files):  # 从最新的开始找
            content = cf.read_text(encoding='utf-8', errors='ignore')
            if '[待写]' in content or '<!-- NOVEL_FLOW_STUB -->' in content:
                chapter_file = cf
                break
        
        if not chapter_file:
            # 没有找到占位章节，使用最新的章节+1
            if chapter_files:
                latest = chapter_files[-1]
                match = re.search(r'第(\d+)章', latest.name)
                if match:
                    next_no = int(match.group(1)) + 1
                    chapter_file = manuscript_dir / f"第{next_no}章-待写.md"
                else:
                    chapter_file = manuscript_dir / "第1章-开篇.md"
            else:
                chapter_file = manuscript_dir / "第1章-开篇.md"
    
    print(f"[信息] 目标章节: {chapter_file}")
    
    # 提取上下文
    print("[信息] 正在提取项目上下文...")
    extractor = ContextExtractor(project_root)
    context = extractor.extract_context(chapter_file, config.get('context_window', 5))
    
    if args.verbose:
        print(f"[调试] 章节号: {context.chapter_no}")
        print(f"[调试] 章节目标: {context.chapter_goal}")
        print(f"[调试] 前几章数: {len(context.previous_chapters)}")
        print(f"[调试] 角色数: {len(context.character_tracker)}")
    
    # 生成提示词
    print("[信息] 正在生成AI提示词...")
    prompt_generator = PromptGenerator(context)
    full_prompt = prompt_generator.generate_prompt()
    
    # 保存提示词（如果请求）
    if args.save_prompt:
        prompt_file = Path(args.save_prompt)
        prompt_file.write_text(full_prompt, encoding='utf-8')
        print(f"[信息] 提示词已保存到: {prompt_file}")
    
    # 如果是dry-run，只输出提示词
    if args.dry_run:
        print("\n" + "="*60)
        print("生成的AI提示词（预览）:")
        print("="*60)
        print(full_prompt[:2000])  # 只显示前2000字符
        print("...")
        print("="*60)
        print("\n[信息] Dry-run模式，未调用AI。使用 --save-prompt 保存完整提示词。")
        return
    
    # 创建AI提供者并生成内容
    print(f"[信息] 正在调用AI生成内容（Provider: {config['ai_provider']}, Model: {config['model']}）...")
    print("[信息] 这可能需要一些时间，请耐心等待...")
    
    try:
        provider = create_ai_provider(config)
        generated_content = provider.generate(SYSTEM_PROMPT, full_prompt)
        
        if not generated_content or len(generated_content) < 100:
            raise ValueError("生成的内容太短或为空")
        
        print(f"[信息] 内容生成完成，长度: {len(generated_content)}字符")
        
        # 统计中文字数
        chinese_chars = count_chinese_chars(generated_content)
        print(f"[信息] 中文字数: {chinese_chars}字")
        
        if chinese_chars < config.get('min_chapter_chars', 3000):
            print(f"[警告] 字数不足（{chinese_chars} < {config['min_chapter_chars']}），可能需要补充")
        
        # 保存到文件
        save_chapter_content(chapter_file, generated_content, config)
        
        # 更新记忆文件（如果启用）
        if config.get('auto_update_memory', True) and not args.no_update_memory:
            print("[信息] 正在更新记忆文件...")
            update_memory_files(project_root, context.chapter_no, generated_content, context)
        
        print("\n" + "="*60)
        print("✅ 章节生成完成！")
        print("="*60)
        print(f"📄 章节文件: {chapter_file}")
        print(f"📝 中文字数: {chinese_chars}字")
        print(f"📊 AI模型: {config['ai_provider']}/{config['model']}")
        
        if config.get('run_gate_check', False) or args.run_gate_check:
            print("\n[提示] 运行门禁检查...")
            # 这里可以调用门禁检查脚本
            # subprocess.run([...])
        
        print("\n[下一步建议]")
        print("1. 审阅生成的内容，必要时进行人工修改")
        print("2. 执行 /更新记忆 确保记忆文件同步")
        print("3. 执行 /继续写 进入下一章")
        
    except Exception as e:
        print(f"\n[错误] 生成内容失败: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
