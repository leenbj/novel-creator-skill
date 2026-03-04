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

# AI提示词模板
SYSTEM_PROMPT = """你是一位专业的小说作家，擅长创作连贯、引人入胜的章节内容。
你的任务是根据提供的上下文信息，生成高质量的小说章节正文。

写作要求：
1. 内容必须承接上一章的剧情，保持连贯性
2. 符合角色设定和性格，不OOC
3. 推进主线剧情，设置合理的章末钩子
4. 字数控制在要求范围内
5. 避免使用AI高频词（不禁、仿佛、映入眼帘、心中暗道、宛如等）
6. 保持统一的叙事风格和节奏

输出格式：
直接输出章节正文，不需要添加章节标题或标记。"""

CHAPTER_PROMPT_TEMPLATE = """
## 章节信息
- 章节号：第{chapter_no}章
- 章节目标：{chapter_goal}
- 目标字数：{target_chars}字（最少{min_chars}字）

## 前情提要（上一章最后部分）
{previous_chapter_summary}

## 主要角色状态
{character_status}

## 当前情节线
{plot_lines}

## 写作风格参考
{style_reference}

## 本章需要包含的元素
{required_elements}

请根据以上信息，创作第{chapter_no}章的正文内容。确保：
1. 承接上一章的剧情
2. 完成本章目标
3. 保持角色性格一致
4. 在章末设置合理的悬念或钩子
5. 字数达标
"""


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
        
        # 解析叙事视角
        perspective_match = re.search(r'视角[：:]\s*(.+)', content)
        if perspective_match:
            style_info['perspective'] = perspective_match.group(1).strip()
        
        # 解析句式特点
        sentence_match = re.search(r'句式[：:]\s*(.+)', content)
        if sentence_match:
            style_info['sentence_pattern'] = sentence_match.group(1).strip()
        
        # 解析对话风格
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
    """AI提示词生成器"""
    
    def __init__(self, context: ProjectContext):
        self.context = context
    
    def generate_prompt(self) -> str:
        """生成完整的AI提示词"""
        sections = []
        
        # 系统角色设定
        sections.append(self._generate_system_role())
        
        # 章节信息
        sections.append(self._generate_chapter_info())
        
        # 前情提要
        sections.append(self._generate_previous_summary())
        
        # 角色信息
        sections.append(self._generate_character_info())
        
        # 情节规划
        sections.append(self._generate_plot_info())
        
        # 风格指南
        sections.append(self._generate_style_guide())
        
        # 输出要求
        sections.append(self._generate_output_requirements())
        
        return "\n\n".join(sections)
    
    def _generate_system_role(self) -> str:
        """生成系统角色设定"""
        return """【系统角色】
你是一位专业的小说作家，擅长创作连贯、引人入胜的长篇小说章节。
你的写作风格成熟稳重，注重细节描写、人物心理刻画和情节推进。
你深知如何设置悬念、控制节奏，让读者欲罢不能。

核心能力：
- 精准把握叙事节奏，张弛有度
- 深入刻画人物心理，行为符合性格逻辑
- 场景描写细腻生动，具有画面感
- 对话自然流畅，符合角色身份
- 章末钩子设置巧妙，引发阅读期待"""
    
    def _generate_chapter_info(self) -> str:
        """生成章节信息"""
        info = f"""【章节信息】
- 章节序号：第{self.context.chapter_no}章
- 本章目标：{self.context.chapter_goal}
- 建议字数：3000-3500字
"""
        return info
    
    def _generate_previous_summary(self) -> str:
        """生成前情提要"""
        if not self.context.previous_chapters:
            return "【前情提要】\n这是小说的开篇第一章，请建立世界观，引入主角，开启主线剧情。"
        
        # 使用最近一章的摘要
        latest = self.context.previous_chapters[-1]
        summary = latest.get('summary', '')[:800]  # 限制长度
        
        return f"""【前情提要】
上一章（第{latest['chapter_no']}章）结尾：
{summary}

请确保本章内容紧密承接上文，保持剧情连贯。"""
    
    def _generate_character_info(self) -> str:
        """生成角色信息"""
        if not self.context.character_tracker:
            return "【主要角色】\n暂无详细角色设定，请根据上下文合理塑造人物。"
        
        lines = ["【主要角色】"]
        for name, info in list(self.context.character_tracker.items())[:5]:  # 最多5个角色
            lines.append(f"\n{name}：")
            if info.get('info'):
                lines.append("  " + " | ".join(info['info'][:3]))
        
        return "\n".join(lines)
    
    def _generate_plot_info(self) -> str:
        """生成情节信息"""
        if not self.context.novel_plan:
            return "【情节规划】\n暂无详细情节规划，请自由发挥，推动故事发展。"
        
        lines = ["【情节规划】"]
        
        volumes = self.context.novel_plan.get('volumes', [])
        if volumes:
            lines.append("\n整体结构：")
            for vol in volumes[:2]:  # 最多显示2卷
                lines.append(f"  - {vol.get('title', '未知卷')}")
                for arc in vol.get('arcs', [])[:3]:  # 每卷最多3个情节线
                    lines.append(f"      • {arc}")
        
        raw_content = self.context.novel_plan.get('raw_content', '')
        if raw_content:
            lines.append(f"\n当前背景：{raw_content[:300]}...")
        
        return "\n".join(lines)
    
    def _generate_style_guide(self) -> str:
        """生成风格指南"""
        if not self.context.style_anchor:
            return """【风格指南】
- 叙事视角：第三人称有限视角
- 句式特点：长短句交错，节奏灵活
- 对话风格：自然口语化，符合角色身份
- 描写重点：场景氛围、人物心理、动作细节"""
        
        style = self.context.style_anchor
        lines = ["【风格指南】"]
        
        if style.get('perspective'):
            lines.append(f"- 叙事视角：{style['perspective']}")
        if style.get('sentence_pattern'):
            lines.append(f"- 句式特点：{style['sentence_pattern']}")
        if style.get('dialogue_style'):
            lines.append(f"- 对话风格：{style['dialogue_style']}")
        
        # 避免使用的词汇
        lines.append("\n【避免使用的词汇】")
        lines.append("不禁、仿佛、映入眼帘、心中暗道、宛如、忽然、突然、竟然")
        
        return "\n".join(lines)
    
    def _generate_output_requirements(self) -> str:
        """生成输出要求"""
        return """【输出要求】
1. 直接输出章节正文，不要添加章节标题
2. 使用中文标点符号
3. 段落之间空一行
4. 对话使用双引号"..."
5. 字数控制在3000-3500字
6. 章末要有悬念或钩子
7. 不要出现作者旁白或注释

【格式示例】
河西的风比前几日更硬，沙粒打在甲片上像细小鼓点。李昊站在望楼北角，目光扫过烽燧、粮车和巡哨交接的时辰。

"先报军情，不报猜测。"他对值守书记说，声音低沉而坚定。

（继续正文...）

请开始创作："""


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

    if dry_run:
        return {
            "ok": True,
            "chapter_file": str(chapter_file),
            "prompt": full_prompt,
            "chapter_no": context.chapter_no,
        }

    # 调用 AI 生成
    try:
        provider = create_ai_provider(config)
        generated_content = provider.generate(SYSTEM_PROMPT, full_prompt)

        if not generated_content or len(generated_content) < 100:
            return {"ok": False, "error": "生成内容太短或为空"}

        chinese_chars = count_chinese_chars(generated_content)
        save_chapter_content(chapter_file, generated_content, config)

        if config.get('auto_update_memory', True):
            update_memory_files(project_root, context.chapter_no, generated_content, context)

        return {
            "ok": True,
            "chapter_file": str(chapter_file),
            "chars": chinese_chars,
            "chapter_no": context.chapter_no,
            "provider": config.get('ai_provider'),
            "model": config.get('model'),
        }
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
