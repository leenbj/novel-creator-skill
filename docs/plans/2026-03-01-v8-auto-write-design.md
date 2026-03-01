# Novel Creator Skill v8.0 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 升级小说创作技能至 v8.0，新增通用联网调研能力、多LLM支持、一键写书功能，同时消除代码重复和优化架构。

**Architecture:** 联网调研作为独立通用模块（research_agent.py），可被任何写作流程调用。多LLM引擎整合 novel_chapter_writer.py 为统一 AI Provider 层，支持 OpenAI/Claude/Kimi/GLM/MiniMax 等。一键写书（auto_novel_writer.py）作为顶层调度器，串联调研→开书→循环写作→完成报告，支持断点续写。

**Tech Stack:** Python 3.9+, 零外部依赖（requests/openai/anthropic 为可选），JSON 状态文件，SKILL.md 指令层

---

## Task 1: 整合 common.py 到所有脚本 - 消除重复函数

**Files:**
- Modify: `scripts/novel_flow_executor.py:45-98` (删除重复的 ensure_dir, read_text, write_text, sha1_text, file_sha1, load_json, slugify)
- Modify: `scripts/plot_rag_retriever.py:33-69` (删除重复的 slugify, ensure_dir, read_text, tokenize, parse_chapter_no)
- Modify: `scripts/chapter_gate_check.py:15-17` (删除重复的 slugify)
- Modify: `scripts/gate_repair_plan.py:15-17` (删除重复的 slugify)
- Modify: `scripts/style_fingerprint.py:37-41` (删除重复的 slugify)
- Modify: `scripts/common.py` (确保所有需要的函数都已导出)
- Test: `scripts/test_novel_flow_executor.py`

**Step 1: 更新 common.py 补充缺失的函数**

在 common.py 中确认已有：ensure_dir, read_text, write_text, load_json, save_json, slugify, sha1_text, file_sha1, is_chapter_file, chapter_no_from_name。需要新增 normalize_text（来自 plot_rag_retriever.py:46）。

```python
# 在 common.py 的文本处理区域追加
def normalize_text(text: str) -> str:
    """将连续空白替换为单个空格。"""
    return re.sub(r"\s+", " ", text).strip()
```

**Step 2: 修改 novel_flow_executor.py - 用 import 替换重复函数**

在文件头部添加导入：
```python
from common import (
    ensure_dir, read_text, write_text, slugify,
    sha1_text, file_sha1, load_json, save_json,
    chapter_no_from_name, is_chapter_file,
)
```
删除第 45-98 行和第 241-243 行的重复定义（ensure_dir, read_text, write_text, sha1_text, file_sha1, load_json, slugify）。保留 run_python 函数（common.py 中没有）。

注意：novel_flow_executor.py 的 load_json 签名是 `load_json(path, default)` 但 common.py 的是 `load_json(path, default=None, required_keys=None)`，兼容。

**Step 3: 修改 plot_rag_retriever.py - 用 import 替换重复函数**

在文件头部添加导入：
```python
from common import ensure_dir, read_text, slugify, chapter_no_from_name, normalize_text
```
删除第 33-48 行和第 67-69 行的重复定义。保留 tokenize（待 Task 2 整合 performance.py 时处理）。

**Step 4: 修改 chapter_gate_check.py - 用 import 替换**

```python
from common import slugify
```
删除第 15-17 行。

**Step 5: 修改 gate_repair_plan.py - 用 import 替换**

```python
from common import slugify
```
删除第 15-17 行。

**Step 6: 修改 style_fingerprint.py - 用 import 替换**

注意：style_fingerprint.py 的 slugify 实现略有不同（用 .lower() 和 md5 fallback）。需要保留其特殊版本或在 common.py 中增加参数。

保留 style_fingerprint.py 的自定义版本（重命名为 `_slugify_style`），其他通用 slugify 场景用 common.py 的。

**Step 7: 运行回归测试**

Run: `cd /Users/wangbo/Desktop/novel-creator-skill && PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_novel_flow_executor.py`
Expected: 所有测试通过

**Step 8: Commit**

```bash
git add scripts/common.py scripts/novel_flow_executor.py scripts/plot_rag_retriever.py scripts/chapter_gate_check.py scripts/gate_repair_plan.py scripts/style_fingerprint.py
git commit -m "refactor: 整合 common.py 消除 6 个脚本中的重复函数定义"
```

---

## Task 2: 整合 performance.py 到 plot_rag_retriever.py

**Files:**
- Modify: `scripts/plot_rag_retriever.py:50-64` (替换手写 tokenize 为 performance.Tokenizer)
- Modify: `scripts/config.py` (确认 RetrievalConfig.stopwords 被使用)
- Test: `scripts/test_novel_flow_executor.py`

**Step 1: 修改 plot_rag_retriever.py 使用 performance.Tokenizer**

```python
# 在文件头部添加
from performance import Tokenizer
from config import get_retrieval_config

# 替换全局常量
_retrieval_config = get_retrieval_config()
STOPWORDS = _retrieval_config.stopwords
TRIGGER_KEYWORDS = _retrieval_config.trigger_keywords
LIGHT_SCENE_KEYWORDS = _retrieval_config.light_scene_keywords

# 创建全局 tokenizer 实例
_tokenizer = Tokenizer(stopwords=STOPWORDS)

# 替换原有 tokenize 函数
def tokenize(text: str) -> List[str]:
    return _tokenizer.tokenize(text)
```

删除第 50-64 行的手写 tokenize 实现。

**Step 2: 运行回归测试**

Run: `cd /Users/wangbo/Desktop/novel-creator-skill && PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_novel_flow_executor.py`
Expected: 所有测试通过

**Step 3: Commit**

```bash
git add scripts/plot_rag_retriever.py
git commit -m "perf: 整合 performance.Tokenizer 替换手写分词实现"
```

---

## Task 3: 多LLM写作引擎 - 重构 novel_chapter_writer.py

**Files:**
- Modify: `scripts/novel_chapter_writer.py` (重构为可导入模块，新增 Kimi/GLM/MiniMax Provider)
- Create: `scripts/novel_writer_config.template.yaml` (配置模板)
- Test: 手动验证 `python3 scripts/novel_chapter_writer.py --dry-run --project-root <test-dir>`

**Step 1: 新增 OpenAI 兼容 Provider（覆盖 Kimi/GLM/MiniMax）**

Kimi 2.5（Moonshot）、GLM-5（智谱）、MiniMax 2.5 均提供 OpenAI 兼容 API。新增一个通用的 OpenAICompatibleProvider：

```python
class OpenAICompatibleProvider(AIProvider):
    """通用 OpenAI 兼容 API 提供者（Kimi/GLM/MiniMax 等）"""

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
            raise ValueError(f"需要提供 {provider} API Key")

        self.base_url = base_url
        self.api_key = api_key
        self.model = config.get("model") or preset.get("default_model", "")
        self.temperature = config.get("temperature", 0.8)
        self.max_tokens = config.get("max_tokens", 4000)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """调用 OpenAI 兼容 API"""
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
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=_json.dumps(data).encode("utf-8"),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = _json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
```

**Step 2: 更新 create_ai_provider 工厂函数**

```python
def create_ai_provider(config: Dict[str, Any]) -> AIProvider:
    provider = config.get("ai_provider", "openai")

    if provider == "openai":
        return OpenAIProvider(config)
    elif provider == "anthropic":
        return AnthropicProvider(config)
    elif provider == "local":
        return LocalProvider(config)
    elif provider in OpenAICompatibleProvider.PRESETS:
        return OpenAICompatibleProvider(config)
    elif config.get("base_url"):
        # 自定义 OpenAI 兼容 API
        return OpenAICompatibleProvider(config)
    else:
        raise ValueError(f"不支持的AI提供者: {provider}")
```

**Step 3: 将 novel_chapter_writer.py 重构为可导入模块**

将 main() 中的核心逻辑提取为独立函数：

```python
def write_chapter(
    project_root: Path,
    chapter_file: Optional[Path] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """自动写作入口，可被外部脚本调用。返回 JSON 结果。"""
    # ... 现有 main() 逻辑提取至此
```

**Step 4: 更新配置模板**

更新 `scripts/novel_writer_config.template.yaml`，添加新 LLM 配置示例。

**Step 5: 验证 dry-run 模式**

Run: `cd /Users/wangbo/Desktop/novel-creator-skill && python3 scripts/novel_chapter_writer.py --project-root novel_projects/穿越大唐之我是皇帝 --dry-run`
Expected: 输出提示词预览，无报错

**Step 6: Commit**

```bash
git add scripts/novel_chapter_writer.py scripts/novel_writer_config.template.yaml
git commit -m "feat: 多LLM引擎支持 Kimi/GLM/MiniMax 及 OpenAI 兼容 API"
```

---

## Task 4: 通用联网调研模块 - research_agent.py

**Files:**
- Create: `scripts/research_agent.py`
- Test: `python3 scripts/research_agent.py keywords --genre 历史 --topic "唐朝安史之乱"`

**Step 1: 创建 research_agent.py**

```python
#!/usr/bin/env python3
"""通用联网调研工具。

职责：
1. 根据题材和剧情生成搜索关键词列表
2. 知识库缺口检测（已有 vs 需要）
3. 资料结构化存储到 02_knowledge_base/
4. 调研日志记录

不包含搜索 API 调用 — 搜索由 AI 工具（Claude Code/OpenCode/Codex）执行。
也支持配置 Tavily/Google API 独立运行。
"""

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from common import ensure_dir, read_text, write_text, load_json, save_json

# =========================================================
# 题材-调研维度映射
# =========================================================

GENRE_RESEARCH_DIMENSIONS = {
    "历史": [
        "历史背景与朝代制度", "地理环境与行政区划", "社会阶层与礼仪规范",
        "服饰妆容与日常饮食", "兵器装备与军事制度", "经济货币与商贸体系",
        "同题材优秀小说写作手法",
    ],
    "玄幻": [
        "修炼体系与境界划分", "种族设定与势力分布", "天材地宝与法器装备",
        "阵法符文与功法体系", "世界地图与秘境设定", "同题材爽点与钩子手法",
    ],
    "科幻": [
        "核心科技设定与硬科幻基础", "太空航行与星际社会", "AI与生物科技",
        "武器与防御体系", "政治体制与文明形态", "同题材经典作品分析",
    ],
    "都市": [
        "行业知识与职场规则", "城市生活与社会现象", "商业运作与投资金融",
        "法律常识与社会制度", "人际关系与社交文化", "同题材爆款分析",
    ],
    "仙侠": [
        "道教与佛教文化背景", "修真境界与法术体系", "宗门架构与江湖规矩",
        "灵药灵兽与法宝设定", "天劫渡劫与飞升设定", "同题材经典设定参考",
    ],
    "游戏": [
        "游戏机制与数值体系", "技能树与职业系统", "副本与Boss设计",
        "经济系统与装备体系", "PVP与公会系统", "同题材系统流写法",
    ],
    "悬疑": [
        "刑侦技术与法医知识", "犯罪心理与行为分析", "法律程序与司法制度",
        "社会暗面与灰色地带", "诡计设计与推理逻辑", "同题材叙事诡计分析",
    ],
    "default": [
        "世界观背景资料", "核心设定参考", "同题材优秀作品分析", "写作手法研究",
    ],
}


def generate_search_keywords(
    genre: str,
    topic: str,
    chapter_goal: str = "",
    existing_keywords: Optional[Set[str]] = None,
) -> List[Dict[str, str]]:
    """根据题材和主题生成分类搜索关键词列表。

    Returns:
        [{"category": "历史背景", "keyword": "唐朝安史之乱 历史背景", "priority": "high"}, ...]
    """
    dimensions = GENRE_RESEARCH_DIMENSIONS.get(genre, GENRE_RESEARCH_DIMENSIONS["default"])
    existing = existing_keywords or set()
    keywords = []

    for dim in dimensions:
        kw = f"{topic} {dim}"
        if kw not in existing:
            keywords.append({
                "category": dim,
                "keyword": kw,
                "priority": "high" if "背景" in dim or "设定" in dim else "medium",
            })

    # 如果有章节目标，生成针对性关键词
    if chapter_goal:
        # 提取关键名词/概念
        for concept in re.findall(r"[\u4e00-\u9fff]{2,6}", chapter_goal):
            kw = f"{topic} {concept}"
            if kw not in existing and len(concept) >= 2:
                keywords.append({
                    "category": "章节相关",
                    "keyword": kw,
                    "priority": "high",
                })

    return keywords


def detect_knowledge_gaps(
    project_root: Path,
    chapter_goal: str = "",
    genre: str = "",
) -> Dict[str, Any]:
    """检测知识库中的缺口。

    扫描 02_knowledge_base/ 已有内容，与本章需求对比，找出缺失领域。

    Returns:
        {"has_gaps": bool, "gaps": [...], "existing_topics": [...]}
    """
    kb_dir = project_root / "02_knowledge_base"
    existing_topics: List[str] = []

    if kb_dir.exists():
        for f in kb_dir.glob("*.md"):
            content = read_text(f) or ""
            # 提取一级标题作为已有主题
            for match in re.finditer(r"^#+\s+(.+)$", content, re.MULTILINE):
                existing_topics.append(match.group(1).strip())

    # 分析章节目标中的关键概念
    needed_concepts = set()
    if chapter_goal:
        for concept in re.findall(r"[\u4e00-\u9fff]{2,8}", chapter_goal):
            needed_concepts.add(concept)

    # 找出已有主题未覆盖的概念
    gaps = []
    existing_text = " ".join(existing_topics)
    for concept in needed_concepts:
        if concept not in existing_text:
            gaps.append(concept)

    return {
        "has_gaps": len(gaps) > 0,
        "gaps": gaps,
        "existing_topics": existing_topics,
        "needed_concepts": list(needed_concepts),
    }


def store_research_result(
    project_root: Path,
    category: str,
    content: str,
    source: str = "",
) -> str:
    """将调研结果结构化存储到知识库。

    根据类别存储到对应文件，采用增量追加模式。

    Returns:
        存储文件路径
    """
    kb_dir = project_root / "02_knowledge_base"
    ensure_dir(kb_dir)

    # 类别到文件的映射
    category_file_map = {
        "世界观": "10_worldbuilding.md",
        "历史": "11_research_data.md",
        "地理": "11_research_data.md",
        "制度": "11_research_data.md",
        "设定": "10_worldbuilding.md",
        "写作手法": "12_style_skills.md",
        "参考": "13_reference_materials.md",
    }

    # 匹配最佳文件
    target_file = "13_reference_materials.md"  # 默认
    for key, filename in category_file_map.items():
        if key in category:
            target_file = filename
            break

    filepath = kb_dir / target_file
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    # 增量追加
    existing = read_text(filepath) or f"# {target_file.replace('.md', '').replace('_', ' ')}\n"
    entry = f"\n\n## {category}（{timestamp}）\n\n{content.strip()}\n"
    if source:
        entry += f"\n> 来源：{source}\n"

    write_text(filepath, existing.rstrip() + entry)
    return str(filepath)


def log_research(
    project_root: Path,
    keyword: str,
    category: str,
    result_summary: str = "",
    source: str = "",
) -> None:
    """记录调研日志。"""
    log_path = project_root / "00_memory" / "retrieval" / "research_log.json"
    log_data = load_json(log_path, {"entries": []})

    entries = log_data.get("entries", [])
    if not isinstance(entries, list):
        entries = []

    entries.append({
        "keyword": keyword,
        "category": category,
        "result_summary": result_summary[:200],
        "source": source,
        "timestamp": dt.datetime.now().isoformat(),
    })

    # 限制日志大小
    if len(entries) > 500:
        entries = entries[-500:]

    log_data["entries"] = entries
    save_json(log_path, log_data)


def generate_research_plan(
    genre: str,
    topic: str,
    project_root: Optional[Path] = None,
    chapter_goal: str = "",
    depth: str = "standard",
) -> Dict[str, Any]:
    """生成完整的调研计划（供 AI 工具执行）。

    Args:
        genre: 题材
        topic: 主题/简介
        project_root: 项目根目录（用于检测已有知识库）
        chapter_goal: 当前章节目标（可选）
        depth: 调研深度 quick/standard/deep

    Returns:
        {"keywords": [...], "gaps": {...}, "instructions": "..."}
    """
    # 生成关键词
    existing_kw: Set[str] = set()
    if project_root:
        log_path = project_root / "00_memory" / "retrieval" / "research_log.json"
        log_data = load_json(log_path, {})
        for entry in log_data.get("entries", []):
            if isinstance(entry, dict):
                existing_kw.add(entry.get("keyword", ""))

    keywords = generate_search_keywords(genre, topic, chapter_goal, existing_kw)

    # 根据深度调整关键词数量
    depth_limits = {"quick": 5, "standard": 15, "deep": 30}
    max_kw = depth_limits.get(depth, 15)
    # 按优先级排序
    keywords.sort(key=lambda x: 0 if x["priority"] == "high" else 1)
    keywords = keywords[:max_kw]

    # 检测知识缺口
    gaps = {}
    if project_root:
        gaps = detect_knowledge_gaps(project_root, chapter_goal, genre)

    # 生成执行指令（供 SKILL.md 引导 AI 工具执行）
    instructions = _build_research_instructions(keywords, gaps, depth)

    return {
        "ok": True,
        "genre": genre,
        "topic": topic,
        "depth": depth,
        "keywords": keywords,
        "gaps": gaps,
        "instructions": instructions,
        "store_path": "02_knowledge_base/",
    }


def _build_research_instructions(keywords, gaps, depth):
    """构建人类/AI可读的调研执行指令。"""
    lines = ["## 调研执行指令\n"]
    lines.append(f"调研深度：{depth}\n")

    if gaps and gaps.get("has_gaps"):
        lines.append("### 知识缺口（优先补充）")
        for gap in gaps.get("gaps", []):
            lines.append(f"- [ ] {gap}")
        lines.append("")

    lines.append("### 搜索关键词列表")
    for i, kw in enumerate(keywords, 1):
        priority_mark = "!!!" if kw["priority"] == "high" else ""
        lines.append(f"{i}. [{kw['category']}] {kw['keyword']} {priority_mark}")

    lines.append("\n### 存储规则")
    lines.append("- 世界观设定 → 02_knowledge_base/10_worldbuilding.md")
    lines.append("- 历史/地理/制度 → 02_knowledge_base/11_research_data.md")
    lines.append("- 写作手法 → 02_knowledge_base/12_style_skills.md")
    lines.append("- 其他参考 → 02_knowledge_base/13_reference_materials.md")

    return "\n".join(lines)


# =========================================================
# CLI
# =========================================================

def main():
    parser = argparse.ArgumentParser(description="通用联网调研工具")
    sub = parser.add_subparsers(dest="command")

    # keywords 子命令：生成搜索关键词
    p_kw = sub.add_parser("keywords", help="生成搜索关键词列表")
    p_kw.add_argument("--genre", required=True, help="题材")
    p_kw.add_argument("--topic", required=True, help="主题/简介")
    p_kw.add_argument("--chapter-goal", default="", help="当前章节目标")
    p_kw.add_argument("--project-root", help="项目根目录")
    p_kw.add_argument("--depth", choices=["quick", "standard", "deep"], default="standard")

    # gaps 子命令：检测知识库缺口
    p_gaps = sub.add_parser("gaps", help="检测知识库缺口")
    p_gaps.add_argument("--project-root", required=True, help="项目根目录")
    p_gaps.add_argument("--chapter-goal", default="", help="当前章节目标")
    p_gaps.add_argument("--genre", default="", help="题材")

    # store 子命令：存储调研结果
    p_store = sub.add_parser("store", help="存储调研结果到知识库")
    p_store.add_argument("--project-root", required=True, help="项目根目录")
    p_store.add_argument("--category", required=True, help="资料类别")
    p_store.add_argument("--content", required=True, help="资料内容")
    p_store.add_argument("--source", default="", help="来源URL")

    # plan 子命令：生成完整调研计划
    p_plan = sub.add_parser("plan", help="生成调研计划")
    p_plan.add_argument("--genre", required=True, help="题材")
    p_plan.add_argument("--topic", required=True, help="主题/简介")
    p_plan.add_argument("--project-root", help="项目根目录")
    p_plan.add_argument("--chapter-goal", default="", help="当前章节目标")
    p_plan.add_argument("--depth", choices=["quick", "standard", "deep"], default="standard")

    args = parser.parse_args()

    if args.command == "keywords":
        pr = Path(args.project_root) if args.project_root else None
        keywords = generate_search_keywords(args.genre, args.topic, args.chapter_goal)
        print(json.dumps({"ok": True, "keywords": keywords}, ensure_ascii=False, indent=2))

    elif args.command == "gaps":
        pr = Path(args.project_root).expanduser().resolve()
        result = detect_knowledge_gaps(pr, args.chapter_goal, args.genre)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))

    elif args.command == "store":
        pr = Path(args.project_root).expanduser().resolve()
        filepath = store_research_result(pr, args.category, args.content, args.source)
        log_research(pr, "", args.category, args.content[:100], args.source)
        print(json.dumps({"ok": True, "stored_to": filepath}, ensure_ascii=False, indent=2))

    elif args.command == "plan":
        pr = Path(args.project_root).expanduser().resolve() if args.project_root else None
        result = generate_research_plan(args.genre, args.topic, pr, args.chapter_goal, args.depth)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

**Step 2: 验证运行**

Run: `cd /Users/wangbo/Desktop/novel-creator-skill && python3 scripts/research_agent.py keywords --genre 历史 --topic "唐朝安史之乱"`
Expected: JSON 输出包含分类搜索关键词

Run: `python3 scripts/research_agent.py plan --genre 历史 --topic "唐朝安史之乱" --depth standard`
Expected: JSON 输出包含完整调研计划

**Step 3: Commit**

```bash
git add scripts/research_agent.py
git commit -m "feat: 新增通用联网调研模块 research_agent.py"
```

---

## Task 5: 一键写书调度器 - auto_novel_writer.py

**Files:**
- Create: `scripts/auto_novel_writer.py`
- Test: `python3 scripts/auto_novel_writer.py plan --synopsis "..." --target-chars 50000`

**Step 1: 创建 auto_novel_writer.py**

```python
#!/usr/bin/env python3
"""一键写书调度器。

全自动完成：解析简介 → 联网调研 → 一键开书 → 循环(调研→写作→门禁) → 完成报告。
支持断点续写：状态持久化到 .flow/auto_write_state.json。
"""

import argparse
import datetime as dt
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from common import ensure_dir, read_text, write_text, load_json, save_json

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = "auto_write_state.json"


def compute_structure(target_chars: int, chars_per_chapter: int = 3500) -> Dict[str, int]:
    """根据目标字数计算卷/章结构。"""
    total_chapters = max(10, target_chars // chars_per_chapter)
    chars_per_volume = min(450000, max(100000, target_chars // 10))
    total_volumes = max(1, math.ceil(target_chars / chars_per_volume))
    chapters_per_volume = max(10, total_chapters // total_volumes)
    return {
        "total_chapters": total_chapters,
        "total_volumes": total_volumes,
        "chapters_per_volume": chapters_per_volume,
        "chars_per_chapter": chars_per_chapter,
    }


def load_state(project_root: Path) -> Dict[str, Any]:
    """加载执行状态（断点续写）。"""
    flow_dir = project_root / ".flow"
    state_path = flow_dir / STATE_FILE
    return load_json(state_path, {})


def save_state(project_root: Path, state: Dict[str, Any]) -> None:
    """保存执行状态。"""
    flow_dir = project_root / ".flow"
    ensure_dir(flow_dir)
    state["last_checkpoint"] = dt.datetime.now().isoformat()
    save_json(flow_dir / STATE_FILE, state)


def init_state(
    project_root: Path,
    synopsis: str,
    target_chars: int,
    genre: str,
    research_depth: str,
) -> Dict[str, Any]:
    """初始化一键写书状态。"""
    structure = compute_structure(target_chars)
    state = {
        "phase": "init",
        "synopsis": synopsis,
        "target_chars": target_chars,
        "genre": genre,
        "research_depth": research_depth,
        **structure,
        "current_volume": 0,
        "current_chapter": 0,
        "chars_written": 0,
        "chapters_written": 0,
        "gate_passes": 0,
        "gate_failures": 0,
        "auto_repairs": 0,
        "research_queries": 0,
        "started_at": dt.datetime.now().isoformat(),
        "last_checkpoint": dt.datetime.now().isoformat(),
        "completed": False,
        "error": None,
    }
    save_state(project_root, state)
    return state


def generate_progress_report(state: Dict[str, Any]) -> str:
    """生成进度报告。"""
    total = state.get("total_chapters", 1)
    written = state.get("chapters_written", 0)
    pct = round(written / total * 100, 1) if total > 0 else 0
    chars = state.get("chars_written", 0)
    target = state.get("target_chars", 0)
    chars_pct = round(chars / target * 100, 1) if target > 0 else 0

    passes = state.get("gate_passes", 0)
    failures = state.get("gate_failures", 0)
    total_gates = passes + failures
    pass_rate = round(passes / total_gates * 100, 1) if total_gates > 0 else 0

    lines = [
        "# 一键写书进度报告",
        "",
        f"- 当前卷：第{state.get('current_volume', 0)}卷 / 共{state.get('total_volumes', 0)}卷",
        f"- 章节进度：{written}/{total} ({pct}%)",
        f"- 字数进度：{chars:,}/{target:,} ({chars_pct}%)",
        f"- 门禁通过率：{pass_rate}% ({passes}/{total_gates})",
        f"- 自动修复次数：{state.get('auto_repairs', 0)}",
        f"- 联网调研次数：{state.get('research_queries', 0)}",
        f"- 开始时间：{state.get('started_at', 'N/A')}",
        f"- 最后检查点：{state.get('last_checkpoint', 'N/A')}",
    ]
    return "\n".join(lines)


def generate_plan(args: argparse.Namespace) -> Dict[str, Any]:
    """生成一键写书执行计划（不实际执行）。"""
    structure = compute_structure(args.target_chars)

    plan = {
        "ok": True,
        "command": "plan",
        "synopsis": args.synopsis,
        "genre": args.genre or "auto-detect",
        "target_chars": args.target_chars,
        **structure,
        "phases": [
            {"phase": "research", "desc": f"基础调研（{args.research_depth}深度）"},
            {"phase": "init", "desc": "一键开书（建模+建库+首章准备）"},
            {
                "phase": "writing",
                "desc": f"自动写作循环（{structure['total_chapters']}章）",
                "per_chapter": "调研缺口→联网补充→继续写→门禁→索引更新",
            },
            {"phase": "report", "desc": "完成报告"},
        ],
        "estimated_api_calls": structure["total_chapters"] * 2,  # 写作+门禁
        "note": "使用 'run' 子命令执行此计划，支持断点续写",
    }
    return plan


def run_auto_write(args: argparse.Namespace) -> Dict[str, Any]:
    """执行一键写书主循环。

    此函数输出执行指令到 stdout（JSON 格式），
    实际的 AI 写作和联网调研由调用方（AI 工具或脚本）执行。
    """
    project_root = Path(args.project_root).expanduser().resolve()
    ensure_dir(project_root)

    # 检查是否有断点
    state = load_state(project_root)
    if state and not state.get("completed") and state.get("phase") != "init":
        # 断点续写
        return {
            "ok": True,
            "command": "run",
            "mode": "resume",
            "project_root": str(project_root),
            "state": state,
            "progress": generate_progress_report(state),
            "next_action": _next_action(state),
        }

    # 全新开始
    state = init_state(
        project_root,
        args.synopsis,
        args.target_chars,
        args.genre or "",
        args.research_depth,
    )

    return {
        "ok": True,
        "command": "run",
        "mode": "fresh",
        "project_root": str(project_root),
        "state": state,
        "next_action": {
            "phase": "research",
            "instruction": "执行基础联网调研",
            "command": f"python3 scripts/research_agent.py plan --genre '{args.genre}' --topic '{args.synopsis[:100]}' --depth {args.research_depth}",
        },
    }


def _next_action(state: Dict[str, Any]) -> Dict[str, Any]:
    """根据当前状态计算下一步操作。"""
    phase = state.get("phase", "init")
    chapter = state.get("current_chapter", 0)
    total = state.get("total_chapters", 0)

    if phase == "research":
        return {"phase": "init", "instruction": "执行 /一键开书"}
    elif phase == "init":
        return {"phase": "writing", "instruction": "开始写作循环，执行第1章的 /继续写"}
    elif phase == "writing":
        if chapter >= total:
            return {"phase": "complete", "instruction": "生成完成报告"}
        vol = state.get("current_volume", 1)
        cpv = state.get("chapters_per_volume", 40)
        is_sprint_review = (chapter % 10 == 0) and chapter > 0
        is_volume_end = (chapter % cpv == 0) and chapter > 0
        instruction = f"执行第{chapter + 1}章的 /继续写"
        if is_sprint_review:
            instruction = f"第{chapter}章冲刺复盘 → 然后{instruction}"
        if is_volume_end:
            instruction = f"第{vol}卷结束汇报 → 然后{instruction}"
        return {"phase": "writing", "chapter": chapter + 1, "instruction": instruction}
    else:
        return {"phase": "complete", "instruction": "一键写书已完成"}


def update_progress(args: argparse.Namespace) -> Dict[str, Any]:
    """更新进度（供外部调用者报告章节完成）。"""
    project_root = Path(args.project_root).expanduser().resolve()
    state = load_state(project_root)
    if not state:
        return {"ok": False, "error": "no_active_session"}

    state["current_chapter"] = args.chapter
    state["chapters_written"] = args.chapter
    state["chars_written"] = state.get("chars_written", 0) + args.chars_added
    if args.gate_passed:
        state["gate_passes"] = state.get("gate_passes", 0) + 1
    else:
        state["gate_failures"] = state.get("gate_failures", 0) + 1

    # 计算当前卷
    cpv = state.get("chapters_per_volume", 40)
    state["current_volume"] = max(1, math.ceil(args.chapter / cpv))

    # 检查是否完成
    if args.chapter >= state.get("total_chapters", 0):
        state["phase"] = "complete"
        state["completed"] = True

    save_state(project_root, state)

    return {
        "ok": True,
        "state": state,
        "progress": generate_progress_report(state),
        "next_action": _next_action(state),
    }


def main():
    parser = argparse.ArgumentParser(description="一键写书调度器")
    sub = parser.add_subparsers(dest="command")

    # plan: 生成执行计划
    p_plan = sub.add_parser("plan", help="生成执行计划（不实际执行）")
    p_plan.add_argument("--synopsis", required=True, help="小说简介")
    p_plan.add_argument("--target-chars", type=int, default=2000000, help="目标字数（默认200万）")
    p_plan.add_argument("--genre", default="", help="题材（可选，从简介推断）")
    p_plan.add_argument("--research-depth", choices=["quick", "standard", "deep"], default="standard")

    # run: 执行一键写书
    p_run = sub.add_parser("run", help="执行一键写书（支持断点续写）")
    p_run.add_argument("--project-root", required=True, help="项目根目录")
    p_run.add_argument("--synopsis", default="", help="小说简介（新开始时必需）")
    p_run.add_argument("--target-chars", type=int, default=2000000, help="目标字数")
    p_run.add_argument("--genre", default="", help="题材")
    p_run.add_argument("--research-depth", choices=["quick", "standard", "deep"], default="standard")

    # progress: 查看/更新进度
    p_prog = sub.add_parser("progress", help="查看或更新进度")
    p_prog.add_argument("--project-root", required=True, help="项目根目录")
    p_prog.add_argument("--chapter", type=int, default=0, help="当前章节号（更新用）")
    p_prog.add_argument("--chars-added", type=int, default=0, help="新增字数")
    p_prog.add_argument("--gate-passed", action="store_true", help="门禁是否通过")

    # report: 生成进度报告
    p_report = sub.add_parser("report", help="生成进度报告")
    p_report.add_argument("--project-root", required=True, help="项目根目录")

    args = parser.parse_args()

    if args.command == "plan":
        result = generate_plan(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "run":
        result = run_auto_write(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "progress":
        if args.chapter > 0:
            result = update_progress(args)
        else:
            pr = Path(args.project_root).expanduser().resolve()
            state = load_state(pr)
            result = {"ok": True, "progress": generate_progress_report(state)} if state else {"ok": False, "error": "no_session"}
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "report":
        pr = Path(args.project_root).expanduser().resolve()
        state = load_state(pr)
        if state:
            print(generate_progress_report(state))
        else:
            print(json.dumps({"ok": False, "error": "no_session"}, ensure_ascii=False))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

**Step 2: 验证运行**

Run: `cd /Users/wangbo/Desktop/novel-creator-skill && python3 scripts/auto_novel_writer.py plan --synopsis "现代青年穿越到唐朝成为太子" --target-chars 50000 --genre 历史`
Expected: JSON 输出包含执行计划、卷章结构

**Step 3: Commit**

```bash
git add scripts/auto_novel_writer.py
git commit -m "feat: 新增一键写书调度器 auto_novel_writer.py"
```

---

## Task 6: 更新 SKILL.md - 新增 /联网调研 和 /一键写书 命令

**Files:**
- Modify: `SKILL.md`

**Step 1: 在 SKILL.md 的命令表中新增两个命令**

在 "## 7. 全命令表" 的表格中追加：

```markdown
| `/联网调研` | 通用联网调研，生成搜索关键词并补充知识库 | 写前调研、知识缺口补充、手动查询特定领域资料 |
| `/一键写书` | 全自动完成整本书：调研→开书→循环写作→完成 | 用户只需提供简介和目标字数，系统全自动完成 |
```

**Step 2: 在 SKILL.md 新增 /联网调研 执行流程**

在命令表之后新增一个段落：

```markdown
## 9. 联网调研（通用能力）

`/联网调研 [主题/关键词]` —— 在任何写作场景中可用。

执行流程：
1. 运行 `python3 scripts/research_agent.py plan --genre <题材> --topic "<主题>" --project-root <目录>` 获取搜索关键词和知识缺口
2. 按关键词列表逐条联网搜索（使用当前 AI 工具的搜索能力）
3. 将搜索结果通过 `python3 scripts/research_agent.py store --project-root <目录> --category "<类别>" --content "<内容>"` 存入知识库
4. 自动集成到 `/继续写` 流程：每章写前检测知识缺口并自动补充

调研深度：`quick`（5条关键词）| `standard`（15条）| `deep`（30条）
```

**Step 3: 在 SKILL.md 新增 /一键写书 执行流程**

```markdown
## 10. 一键写书（全自动模式）

`/一键写书 简介="..." [目标字数=200万] [调研深度=standard]`

执行流程：
1. 解析简介，提取题材、核心冲突、主角目标
2. 运行 `/联网调研` 进行基础调研
3. 自动执行 `/一键开书` 初始化项目
4. 循环执行（直到达到目标字数）：
   a. 分析本章知识需求，检测缺口
   b. `/联网调研` 补充缺失资料
   c. `/继续写` 完成写作+门禁
   d. 门禁失败 → 自动修复（最多3次）
   e. 每10章冲刺复盘
   f. 每卷结束输出进度报告
5. 生成完成报告

断点续写：中断后再次执行 `/一键写书`，系统自动从断点恢复。

状态查询：`python3 scripts/auto_novel_writer.py report --project-root <目录>`
```

**Step 4: Commit**

```bash
git add SKILL.md
git commit -m "feat: SKILL.md 新增 /联网调研 和 /一键写书 命令定义"
```

---

## Task 7: 整合 continue-write 支持自动调研

**Files:**
- Modify: `scripts/novel_flow_executor.py` (在 continue_write 函数中添加调研触发)

**Step 1: 在 continue_write 函数中添加调研检测**

在 `continue_write()` 函数的 RAG 查询之后、写作之前，添加知识缺口检测调用：

```python
# 在 q_code 检查之后，chapter_path 确定之后添加：
if args.auto_research:
    from research_agent import detect_knowledge_gaps, generate_search_keywords
    gaps = detect_knowledge_gaps(project_root, query)
    if gaps.get("has_gaps"):
        # 将缺口信息输出到结果中，供 AI 工具执行联网调研
        research_needed = gaps
```

在 argparse 部分新增参数：
```python
p_cw.add_argument("--auto-research", action="store_true", default=False,
                   help="写前自动检测知识缺口并提示调研")
```

**Step 2: 运行回归测试**

Run: `cd /Users/wangbo/Desktop/novel-creator-skill && PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_novel_flow_executor.py`
Expected: 所有测试通过

**Step 3: Commit**

```bash
git add scripts/novel_flow_executor.py
git commit -m "feat: continue-write 支持 --auto-research 知识缺口检测"
```

---

## Task 8: 编写详细使用说明文档

**Files:**
- Create: `references/user-guide.md`

**Step 1: 编写用户指南**

包含以下章节：
1. **快速上手（5分钟开始写书）** - 最简三步：安装→一键开书→继续写
2. **安装配置** - Claude Code / OpenCode / Codex / Gemini CLI 安装方法
3. **多LLM配置** - OpenAI / Claude / Kimi / GLM / MiniMax 配置示例
4. **新手三命令** - /一键开书、/继续写、/修复本章 详解
5. **联网调研** - 手动调研、自动调研、知识库管理
6. **一键写书** - 完整教程、断点续写、进度查看
7. **进阶用法** - 风格定制、批量写作、百万字路线图
8. **常见问题** - FAQ 和故障排查

**Step 2: Commit**

```bash
git add references/user-guide.md
git commit -m "docs: 新增详细使用说明文档 user-guide.md"
```

---

## Task 9: 更新 CLAUDE.md 和版本号

**Files:**
- Modify: `CLAUDE.md`
- Modify: `scripts/config.py`

**Step 1: 更新 CLAUDE.md 添加新脚本入口**

新增 research_agent.py 和 auto_novel_writer.py 的命令说明。

**Step 2: 更新版本号到 v8.0**

**Step 3: 运行全量回归测试**

Run: `cd /Users/wangbo/Desktop/novel-creator-skill && PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_novel_flow_executor.py`
Expected: 所有测试通过

**Step 4: Commit**

```bash
git add CLAUDE.md scripts/config.py
git commit -m "chore: 更新 CLAUDE.md 和版本号至 v8.0"
```
