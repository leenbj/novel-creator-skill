#!/usr/bin/env python3
"""通用联网调研工具。

职责：
1. 根据题材和剧情生成搜索关键词列表
2. 知识库缺口检测（已有 vs 需要）
3. 资料结构化存储到 02_knowledge_base/
4. 调研日志记录

搜索由 AI 工具（Claude Code/OpenCode/Codex）执行，本模块不含搜索 API 调用。
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# 添加脚本目录到路径
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

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
    "言情": [
        "情感心理与关系发展", "社交礼仪与约会文化", "职场背景知识",
        "时尚美妆与生活方式", "婚恋观与家庭关系", "同题材甜宠/虐恋手法",
    ],
    "军事": [
        "军事编制与指挥体系", "武器装备与战术战略", "军事历史与战役分析",
        "军营生活与训练体系", "情报与特种作战", "同题材经典作品参考",
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
    """检测知识库中的缺口。"""
    kb_dir = project_root / "02_knowledge_base"
    existing_topics: List[str] = []

    if kb_dir.exists():
        for f in kb_dir.glob("*.md"):
            content = read_text(f) or ""
            for match in re.finditer(r"^#+\s+(.+)$", content, re.MULTILINE):
                existing_topics.append(match.group(1).strip())

    needed_concepts = set()
    if chapter_goal:
        for concept in re.findall(r"[\u4e00-\u9fff]{2,8}", chapter_goal):
            needed_concepts.add(concept)

    gaps = []
    existing_text = " ".join(existing_topics)
    for concept in needed_concepts:
        if concept not in existing_text:
            gaps.append(concept)

    return {
        "has_gaps": len(gaps) > 0,
        "gaps": gaps,
        "existing_topics": existing_topics[:50],
        "needed_concepts": list(needed_concepts),
    }


def store_research_result(
    project_root: Path,
    category: str,
    content: str,
    source: str = "",
) -> str:
    """将调研结果结构化存储到知识库。"""
    kb_dir = project_root / "02_knowledge_base"
    ensure_dir(kb_dir)

    category_file_map = {
        "世界观": "10_worldbuilding.md",
        "历史": "11_research_data.md",
        "地理": "11_research_data.md",
        "制度": "11_research_data.md",
        "背景": "11_research_data.md",
        "设定": "10_worldbuilding.md",
        "体系": "10_worldbuilding.md",
        "写作": "12_style_skills.md",
        "手法": "12_style_skills.md",
        "风格": "12_style_skills.md",
        "参考": "13_reference_materials.md",
        "分析": "13_reference_materials.md",
    }

    target_file = "13_reference_materials.md"
    for key, filename in category_file_map.items():
        if key in category:
            target_file = filename
            break

    filepath = kb_dir / target_file
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    existing = read_text(filepath) or f"# {target_file.replace('.md', '').replace('_', ' ').title()}\n"
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
    """生成完整的调研计划（供 AI 工具执行）。"""
    existing_kw: Set[str] = set()
    if project_root:
        log_path = project_root / "00_memory" / "retrieval" / "research_log.json"
        log_data = load_json(log_path, {})
        for entry in log_data.get("entries", []):
            if isinstance(entry, dict):
                existing_kw.add(entry.get("keyword", ""))

    keywords = generate_search_keywords(genre, topic, chapter_goal, existing_kw)

    depth_limits = {"quick": 5, "standard": 15, "deep": 30}
    max_kw = depth_limits.get(depth, 15)
    keywords.sort(key=lambda x: 0 if x["priority"] == "high" else 1)
    keywords = keywords[:max_kw]

    gaps = {}
    if project_root:
        gaps = detect_knowledge_gaps(project_root, chapter_goal, genre)

    instructions = _build_research_instructions(keywords, gaps, depth)

    return {
        "ok": True,
        "genre": genre,
        "topic": topic,
        "depth": depth,
        "keyword_count": len(keywords),
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
        priority_mark = " !!!" if kw["priority"] == "high" else ""
        lines.append(f"{i}. [{kw['category']}] {kw['keyword']}{priority_mark}")

    lines.append("\n### 存储规则")
    lines.append("- 世界观/体系/设定 → 02_knowledge_base/10_worldbuilding.md")
    lines.append("- 历史/地理/制度/背景 → 02_knowledge_base/11_research_data.md")
    lines.append("- 写作手法/风格 → 02_knowledge_base/12_style_skills.md")
    lines.append("- 其他参考/分析 → 02_knowledge_base/13_reference_materials.md")
    lines.append("\n### 执行方式")
    lines.append("1. 按优先级(!!!)逐条搜索关键词")
    lines.append("2. 提取搜索结果中的关键信息")
    lines.append("3. 使用以下命令存储到知识库：")
    lines.append('   python3 scripts/research_agent.py store --project-root <目录> --category "<类别>" --content "<内容>" --source "<来源>"')

    return "\n".join(lines)


# =========================================================
# CLI
# =========================================================

def main():
    parser = argparse.ArgumentParser(
        description="通用联网调研工具 - 生成搜索关键词、检测知识缺口、存储调研结果",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 生成搜索关键词
  python3 research_agent.py keywords --genre 历史 --topic "唐朝安史之乱"

  # 生成完整调研计划
  python3 research_agent.py plan --genre 历史 --topic "唐朝安史之乱" --depth standard

  # 检测知识库缺口
  python3 research_agent.py gaps --project-root ./my_novel --chapter-goal "主角面临兵变危机"

  # 存储调研结果
  python3 research_agent.py store --project-root ./my_novel --category "历史背景" --content "安史之乱发生于..." --source "https://..."
        """,
    )
    sub = parser.add_subparsers(dest="command")

    p_kw = sub.add_parser("keywords", help="生成搜索关键词列表")
    p_kw.add_argument("--genre", required=True, help="题材（历史/玄幻/科幻/都市/仙侠/游戏/悬疑/言情/军事）")
    p_kw.add_argument("--topic", required=True, help="主题/简介")
    p_kw.add_argument("--chapter-goal", default="", help="当前章节目标（可选）")
    p_kw.add_argument("--project-root", default="", help="项目根目录（用于去重已查询关键词）")

    p_gaps = sub.add_parser("gaps", help="检测知识库缺口")
    p_gaps.add_argument("--project-root", required=True, help="项目根目录")
    p_gaps.add_argument("--chapter-goal", default="", help="当前章节目标")
    p_gaps.add_argument("--genre", default="", help="题材")

    p_store = sub.add_parser("store", help="存储调研结果到知识库")
    p_store.add_argument("--project-root", required=True, help="项目根目录")
    p_store.add_argument("--category", required=True, help="资料类别")
    p_store.add_argument("--content", required=True, help="资料内容")
    p_store.add_argument("--source", default="", help="来源URL或说明")

    p_plan = sub.add_parser("plan", help="生成完整调研计划")
    p_plan.add_argument("--genre", required=True, help="题材")
    p_plan.add_argument("--topic", required=True, help="主题/简介")
    p_plan.add_argument("--project-root", default="", help="项目根目录")
    p_plan.add_argument("--chapter-goal", default="", help="当前章节目标")
    p_plan.add_argument("--depth", choices=["quick", "standard", "deep"], default="standard", help="调研深度")

    args = parser.parse_args()

    if args.command == "keywords":
        existing_kw: Set[str] = set()
        if args.project_root:
            pr = Path(args.project_root).expanduser().resolve()
            log_path = pr / "00_memory" / "retrieval" / "research_log.json"
            log_data = load_json(log_path, {})
            for entry in log_data.get("entries", []):
                if isinstance(entry, dict):
                    existing_kw.add(entry.get("keyword", ""))

        keywords = generate_search_keywords(args.genre, args.topic, args.chapter_goal, existing_kw)
        print(json.dumps({"ok": True, "keywords": keywords, "count": len(keywords)}, ensure_ascii=False, indent=2))

    elif args.command == "gaps":
        pr = Path(args.project_root).expanduser().resolve()
        result = detect_knowledge_gaps(pr, args.chapter_goal, args.genre)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))

    elif args.command == "store":
        pr = Path(args.project_root).expanduser().resolve()
        filepath = store_research_result(pr, args.category, args.content, args.source)
        log_research(pr, args.content[:50], args.category, args.content[:100], args.source)
        print(json.dumps({"ok": True, "stored_to": filepath}, ensure_ascii=False, indent=2))

    elif args.command == "plan":
        pr = Path(args.project_root).expanduser().resolve() if args.project_root else None
        result = generate_research_plan(args.genre, args.topic, pr, args.chapter_goal, args.depth)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
