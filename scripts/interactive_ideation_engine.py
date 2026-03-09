#!/usr/bin/env python3
"""交互式脑洞引导引擎（F1 功能支撑脚本）。

将用户模糊的故事想法通过结构化提问逐步拓展为完整小说框架，
同时生成初始知识图谱和大纲文档。

该脚本不直接与用户交互（AI 层负责对话），
而是管理引导状态和生成阶段性产出物。

子命令：
1. init     — 初始化脑洞会话
2. status   — 查看当前引导进度
3. advance  — 推进到下一引导轮次
4. collect  — 收集用户在某轮的回答
5. generate — 根据收集到的信息生成最终产出物
"""

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import ensure_dir, load_json, read_text, save_json, write_text

# -- 常量 ------------------------------------------------------------------

ROUND_NAMES = {
    1: "核心种子提取",
    2: "世界观拓展",
    3: "角色网络构建",
    4: "剧情骨架搭建",
    5: "确认与收敛",
}

ROUND_PROMPTS = {
    1: [
        "你的主角最想达成的目标是什么？最大的阻碍呢？",
        "如果用一句话概括这本书最让人上瘾的点，你会怎么说？",
        "故事发生在什么样的世界？和现实世界有什么不同？",
        "这是什么情绪基调的故事？爽文、虐文、成长、还是其他？",
    ],
    2: [
        "这个世界的力量等级/科技水平/社会结构是怎么划分的？",
        "有没有参考过的作品或世界观？可以说说你想和它的区别。",
        "主角所在的世界，普通人和主角之间有什么核心差距？",
    ],
    3: [
        "主角的性格是什么样的？有什么明显的优点和弱点？",
        "除了主角，谁是读者最可能喜欢的角色？为什么？",
        "反派如果站在自己的立场，他觉得自己做的是对的吗？",
        "主角和最重要的配角之间，有什么情感上的纠葛或冲突？",
    ],
    4: [
        "故事大概分几个阶段？每个阶段的核心转折点是什么？",
        "你最想写的是哪个场景或剧情？",
        "有没有你特别不想写的内容或禁区？",
        "你偏向快节奏爽文，还是慢热沉浸式？",
    ],
    5: [
        "我整理了以上信息，请确认是否符合你的想法。",
        "还有什么你觉得重要的信息想补充？",
        "确认后我将生成正式大纲、知识图谱和各类文档。",
    ],
}

FALLBACK_OPTIONS = {
    1: {
        "genre": ["玄幻修仙", "历史权谋", "都市异能", "科幻星际", "古言言情"],
        "tone": ["爽文成长流", "虐心情感流", "权谋博弈流", "热血战斗流"],
        "hook": ["主角从弱小到无敌的逆袭", "乱世中的家国情怀", "现代人穿越古代改变命运"],
    },
    2: {
        "power_system": ["修炼等级体系", "异能觉醒体系", "科技武器体系", "魔法学院体系"],
        "world_type": ["东方玄幻世界", "类明清历史", "赛博朋克未来", "西方奇幻大陆"],
    },
    3: {
        "protagonist_type": ["有仇必报的强者", "温柔而坚定的守护者", "腹黑智谋型", "热血莽撞成长型"],
        "rival_relation": ["亦敌亦友的竞争者", "曾经的挚友后来的对手", "误解产生的仇恨"],
    },
    4: {
        "structure": ["三幕式（起承转合）", "五卷式（升级打怪路线）", "双线并行（主角与反派视角）"],
        "pacing": ["快节奏（每章必有爽点）", "中等节奏（三章一小高潮）", "慢热（前期铺垫扎实）"],
    },
}

# -- 配置 ------------------------------------------------------------------

@dataclass
class IdeationConfig:
    session_rel_path: str = "00_memory/ideation_session.json"
    idea_seed_rel_path: str = "00_memory/idea_seed.md"
    total_rounds: int = 5
    default_indent: int = 2


# -- 内部工具 ---------------------------------------------------------------

def _session_path(root: Path, cfg: IdeationConfig) -> Path:
    return root / cfg.session_rel_path


def _load_session(root: Path, cfg: IdeationConfig) -> Dict[str, Any]:
    return load_json(
        _session_path(root, cfg),
        default={
            "current_round": 0,
            "completed": False,
            "answers": {},
            "fallback_chosen": {},
            "created_at": "",
            "updated_at": "",
        },
    )


def _save_session(root: Path, session: Dict[str, Any], cfg: IdeationConfig) -> bool:
    session["updated_at"] = dt.datetime.now().isoformat()
    return save_json(_session_path(root, cfg), session, indent=cfg.default_indent)


def _build_idea_seed(session: Dict[str, Any]) -> str:
    """根据会话信息构建创意种子文档。"""
    answers = session.get("answers", {})
    fallbacks = session.get("fallback_chosen", {})

    lines = [
        "# 创意种子",
        f"_生成时间：{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}_",
        "",
        "## 第一轮：核心设定",
    ]

    for key, label in [
        ("protagonist_goal", "主角目标"),
        ("core_conflict", "核心冲突"),
        ("genre", "题材"),
        ("tone", "情绪基调"),
        ("hook", "最大卖点"),
    ]:
        val = answers.get(1, {}).get(key) or fallbacks.get(key, "待定")
        lines.append(f"- **{label}**：{val}")

    lines.extend(["", "## 第二轮：世界观"])
    for key, label in [
        ("world_setting", "世界背景"),
        ("power_system", "力量体系"),
        ("world_type", "世界类型"),
    ]:
        val = answers.get(2, {}).get(key) or fallbacks.get(key, "待定")
        lines.append(f"- **{label}**：{val}")

    lines.extend(["", "## 第三轮：角色"])
    for key, label in [
        ("protagonist_personality", "主角性格"),
        ("protagonist_weakness", "主角弱点"),
        ("key_ally", "关键盟友"),
        ("antagonist_motivation", "反派动机"),
    ]:
        val = answers.get(3, {}).get(key) or fallbacks.get(key, "待定")
        lines.append(f"- **{label}**：{val}")

    lines.extend(["", "## 第四轮：剧情骨架"])
    for key, label in [
        ("structure", "故事结构"),
        ("key_turning_points", "核心转折点"),
        ("pacing", "节奏偏好"),
        ("taboos", "禁忌内容"),
    ]:
        val = answers.get(4, {}).get(key) or fallbacks.get(key, "待定")
        lines.append(f"- **{label}**：{val}")

    return "\n".join(lines)


# -- 子命令 -----------------------------------------------------------------

def cmd_init(args: argparse.Namespace, cfg: IdeationConfig) -> Dict[str, Any]:
    """初始化脑洞引导会话。"""
    root = Path(args.project_root).expanduser().resolve()
    path = _session_path(root, cfg)

    if path.exists() and not args.force:
        session = _load_session(root, cfg)
        return {
            "ok": True, "command": "init", "created": False,
            "current_round": session.get("current_round", 0),
            "message": "会话已存在。使用 --force 重置，或用 status 查看进度。",
        }

    session = {
        "current_round": 1,
        "completed": False,
        "answers": {},
        "fallback_chosen": {},
        "genre": args.genre or "",
        "title_hint": args.title_hint or "",
        "created_at": dt.datetime.now().isoformat(),
        "updated_at": dt.datetime.now().isoformat(),
    }
    ensure_dir(path.parent)
    _save_session(root, session, cfg)

    # 返回第1轮的引导问题
    prompts = ROUND_PROMPTS[1]
    fallbacks = FALLBACK_OPTIONS.get(1, {})

    return {
        "ok": True, "command": "init", "created": True,
        "current_round": 1,
        "round_name": ROUND_NAMES[1],
        "prompts": prompts,
        "fallback_options": fallbacks,
        "message": "脑洞引导会话已初始化。请根据以下问题进行引导，收集到用户答案后执行 collect 命令。",
    }


def cmd_status(args: argparse.Namespace, cfg: IdeationConfig) -> Dict[str, Any]:
    """查看当前引导进度。"""
    root = Path(args.project_root).expanduser().resolve()
    session = _load_session(root, cfg)

    current_round = session.get("current_round", 0)
    completed = session.get("completed", False)
    answers = session.get("answers", {})

    completed_rounds = [r for r in range(1, current_round) if str(r) in answers or r in answers]

    return {
        "ok": True, "command": "status",
        "current_round": current_round,
        "total_rounds": cfg.total_rounds,
        "completed": completed,
        "completed_rounds": completed_rounds,
        "current_round_name": ROUND_NAMES.get(current_round, "完成"),
        "answers_collected": {str(r): bool(answers.get(r) or answers.get(str(r))) for r in range(1, 6)},
        "next_prompts": ROUND_PROMPTS.get(current_round, []) if not completed else [],
    }


def cmd_collect(args: argparse.Namespace, cfg: IdeationConfig) -> Dict[str, Any]:
    """收集用户在某轮次的回答。"""
    root = Path(args.project_root).expanduser().resolve()
    session = _load_session(root, cfg)

    round_no = args.round or session.get("current_round", 1)

    try:
        answer_data = json.loads(args.answers)
    except (json.JSONDecodeError, TypeError):
        return {
            "ok": False, "command": "collect",
            "error": "answers 必须是 JSON 格式的字典，如 '{\"protagonist_goal\": \"...\"}'"
        }

    if not isinstance(answer_data, dict):
        return {"ok": False, "command": "collect", "error": "answers 必须是 JSON 对象"}

    # 保存答案（使用整数键）
    answers = session.get("answers", {})
    answers[round_no] = answer_data
    session["answers"] = answers

    # 如果用户选了 fallback，记录
    if args.use_fallback:
        fallbacks = session.get("fallback_chosen", {})
        fallbacks.update(answer_data)
        session["fallback_chosen"] = fallbacks

    _save_session(root, session, cfg)

    return {
        "ok": True, "command": "collect",
        "round": round_no,
        "keys_collected": list(answer_data.keys()),
        "message": f"第 {round_no} 轮答案已保存。执行 advance 进入下一轮。",
    }


def cmd_advance(args: argparse.Namespace, cfg: IdeationConfig) -> Dict[str, Any]:
    """推进到下一引导轮次。"""
    root = Path(args.project_root).expanduser().resolve()
    session = _load_session(root, cfg)

    current_round = session.get("current_round", 1)

    if session.get("completed"):
        return {
            "ok": True, "command": "advance",
            "message": "所有轮次已完成，请执行 generate 生成最终产出物。",
            "completed": True,
        }

    next_round = current_round + 1
    if next_round > cfg.total_rounds:
        session["completed"] = True
        _save_session(root, session, cfg)
        return {
            "ok": True, "command": "advance",
            "current_round": current_round,
            "completed": True,
            "message": "引导完成！请执行 generate 生成大纲、知识图谱等产出物。",
        }

    session["current_round"] = next_round
    _save_session(root, session, cfg)

    next_prompts = ROUND_PROMPTS.get(next_round, [])
    next_fallbacks = FALLBACK_OPTIONS.get(next_round, {})

    return {
        "ok": True, "command": "advance",
        "previous_round": current_round,
        "current_round": next_round,
        "round_name": ROUND_NAMES.get(next_round, ""),
        "prompts": next_prompts,
        "fallback_options": next_fallbacks,
        "message": f"已进入第 {next_round} 轮：{ROUND_NAMES.get(next_round, '')}",
    }


def cmd_generate(args: argparse.Namespace, cfg: IdeationConfig) -> Dict[str, Any]:
    """根据收集到的信息生成最终产出物。"""
    root = Path(args.project_root).expanduser().resolve()
    session = _load_session(root, cfg)

    answers = session.get("answers", {})
    if not answers:
        return {
            "ok": False, "command": "generate",
            "error": "尚未收集到任何答案，请先完成引导轮次",
        }

    # 生成 idea_seed.md
    idea_seed = _build_idea_seed(session)
    seed_path = root / cfg.idea_seed_rel_path
    ensure_dir(seed_path.parent)
    write_text(seed_path, idea_seed)

    # 生成图谱初始化指令摘要（供 AI 执行）
    graph_init_hints: List[str] = []
    r3 = answers.get(3) or answers.get("3") or {}
    if isinstance(r3, dict):
        if r3.get("protagonist_name"):
            graph_init_hints.append(
                f"story_graph_builder add-node --type character --name {r3['protagonist_name']} "
                f"--attrs {{\"role\":\"protagonist\"}}"
            )
        if r3.get("antagonist_name"):
            graph_init_hints.append(
                f"story_graph_builder add-node --type character --name {r3['antagonist_name']} "
                f"--attrs {{\"role\":\"antagonist\"}}"
            )

    # 生成 novel_plan 提示（供 AI 填充）
    r1 = answers.get(1) or answers.get("1") or {}
    r4 = answers.get(4) or answers.get("4") or {}

    plan_prompt = (
        f"请基于以下创意种子生成正式的 novel_plan.md：\n\n"
        f"{idea_seed}\n\n"
        f"要求：\n"
        f"1. 包含卷章结构规划（至少3卷）\n"
        f"2. 每卷列出核心事件和转折点\n"
        f"3. 标注主要伏笔线（3-5条）\n"
        f"4. 明确核心冲突的解决时间节点\n"
    )

    plan_prompt_path = root / "00_memory" / "plan_generation_prompt.md"
    write_text(plan_prompt_path, plan_prompt)

    generated_files = [str(seed_path), str(plan_prompt_path)]

    return {
        "ok": True, "command": "generate",
        "generated_files": generated_files,
        "graph_init_hints": graph_init_hints,
        "plan_prompt_file": str(plan_prompt_path),
        "rounds_completed": len(answers),
        "message": (
            f"已生成 {len(generated_files)} 个产出文件。\n"
            f"下一步：\n"
            f"1. 审核 idea_seed.md 并修改\n"
            f"2. 让 AI 读取 plan_generation_prompt.md 并生成 novel_plan.md\n"
            f"3. 执行 story_graph_builder init 初始化知识图谱\n"
            f"4. 执行 /一键开书 正式开始写作"
        ),
    }


# -- CLI -------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="交互式脑洞引导引擎")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="初始化引导会话")
    s.add_argument("--project-root", required=True)
    s.add_argument("--genre", default="", help="预设题材（可选）")
    s.add_argument("--title-hint", default="", help="书名提示（可选）")
    s.add_argument("--force", action="store_true", help="覆盖已有会话")

    s = sub.add_parser("status", help="查看引导进度")
    s.add_argument("--project-root", required=True)

    s = sub.add_parser("collect", help="收集用户答案")
    s.add_argument("--project-root", required=True)
    s.add_argument("--round", type=int, default=0, help="轮次号（默认当前轮）")
    s.add_argument("--answers", required=True, help='答案 JSON，如 \'{"protagonist_goal":"..."}\'')
    s.add_argument("--use-fallback", action="store_true", help="标记为使用预设选项")

    s = sub.add_parser("advance", help="推进到下一轮")
    s.add_argument("--project-root", required=True)

    s = sub.add_parser("generate", help="生成最终产出物")
    s.add_argument("--project-root", required=True)

    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = IdeationConfig()

    dispatch = {
        "init": cmd_init,
        "status": cmd_status,
        "collect": cmd_collect,
        "advance": cmd_advance,
        "generate": cmd_generate,
    }

    handler = dispatch.get(args.cmd)
    if handler is None:
        payload: Dict[str, Any] = {"ok": False, "error": f"unknown_command:{args.cmd}"}
    else:
        try:
            payload = handler(args, cfg)
        except Exception as exc:
            payload = {"ok": False, "command": args.cmd, "error": repr(exc)}

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
