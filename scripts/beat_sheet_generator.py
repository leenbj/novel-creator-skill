#!/usr/bin/env python3
"""Beat Sheet 生成器（多步流水线写作 Step 1-2）。

将"写一章"拆解为多个 Beat（微场景），强制限制单次生成的剧情跨度，
让每个场景充分展开，避免 AI 为追求连贯性而压缩剧情。

子命令：
1. generate  — 根据章节目标生成 Beat Sheet（3-5 个微场景）
2. expand    — 为单个 Beat 生成扩写提示词
3. validate  — 校验 Beat Sheet 是否符合分布规则
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

from common import ensure_dir, load_json, read_text, save_json

# -- 常量 ------------------------------------------------------------------

BEAT_TYPES = {
    "conflict":       "冲突对抗",
    "bond":           "情感羁绊",
    "world_building": "世界描绘",
    "revelation":     "信息揭露",
    "transition":     "过渡衔接",
}

# -- 配置 ------------------------------------------------------------------

@dataclass
class BeatConfig:
    beats_rel_dir: str = "00_memory/beats"
    anchor_rel_path: str = "00_memory/outline_anchors.json"
    graph_rel_path: str = "00_memory/story_graph.json"
    min_beats: int = 3
    max_beats: int = 5
    word_target_range: tuple = (600, 1200)
    default_indent: int = 2


# -- 内部工具 ---------------------------------------------------------------

def _beats_dir(root: Path, cfg: BeatConfig) -> Path:
    return root / cfg.beats_rel_dir


def _beat_sheet_path(root: Path, chapter: int, cfg: BeatConfig) -> Path:
    return _beats_dir(root, cfg) / f"ch{chapter:04d}_beat_sheet.json"


def _beat_expand_path(root: Path, chapter: int, beat_id: int, cfg: BeatConfig) -> Path:
    return _beats_dir(root, cfg) / f"ch{chapter:04d}_beat{beat_id:02d}_expand.md"


def _load_anchors(root: Path, cfg: BeatConfig) -> Dict[str, Any]:
    return load_json(root / cfg.anchor_rel_path, default={})


def _default_beat(beat_id: int, beat_type: str, summary: str) -> Dict[str, Any]:
    return {
        "beat_id": beat_id,
        "type": beat_type,
        "summary": summary,
        "characters": [],
        "location": "",
        "micro_conflict": "",
        "emotion_target": "",
        "word_target": 800,
        "anti_resolution": beat_type == "conflict",
    }


def _validate_beat_distribution(beats: List[Dict[str, Any]]) -> List[str]:
    """校验 Beat 分布规则，返回错误列表。"""
    errors: List[str] = []

    if not beats:
        errors.append("beat_sheet_empty")
        return errors

    types = [b.get("type", "") for b in beats]

    # 规则1：至少 1 个冲突型
    if "conflict" not in types:
        errors.append("missing_conflict_beat: 每章至少需要 1 个冲突型 Beat")

    # 规则2：不得连续 2 个同类型
    for i in range(1, len(types)):
        if types[i] == types[i - 1]:
            errors.append(
                f"consecutive_same_type: Beat {i} 和 Beat {i + 1} "
                f"连续为 {types[i]} 类型"
            )

    # 规则3：最后一个 Beat 必须留悬念
    last = beats[-1]
    if last.get("type") == "transition" and not last.get("anti_resolution"):
        errors.append("last_beat_no_hook: 最后一个 Beat 应留下悬念或新问题")

    # 规则4：数量范围
    if len(beats) < 3:
        errors.append(f"too_few_beats: 最少 3 个，当前 {len(beats)} 个")
    if len(beats) > 5:
        errors.append(f"too_many_beats: 最多 5 个，当前 {len(beats)} 个")

    # 规则5：每个 Beat 必须有 summary
    for b in beats:
        if not b.get("summary"):
            errors.append(f"beat_{b.get('beat_id', '?')}_missing_summary")

    return errors


# -- 子命令 -----------------------------------------------------------------

def cmd_generate(args: argparse.Namespace, cfg: BeatConfig) -> Dict[str, Any]:
    """生成 Beat Sheet 骨架。

    这是一个模板生成器：根据章节目标和锚点约束，生成带有合理
    默认值的 Beat Sheet JSON，供 AI 填充具体内容后使用。
    """
    root = Path(args.project_root).expanduser().resolve()
    chapter = args.chapter
    beat_count = max(cfg.min_beats, min(args.beat_count, cfg.max_beats))

    anchors = _load_anchors(root, cfg)
    node = anchors.get("current_node", {})
    allowed_range = node.get("allowed_plot_range", "")
    forbidden = node.get("forbidden_reveals", [])

    # 构建 Beat 类型轮转序列（避免连续同类型）
    type_cycle = ["conflict", "bond", "world_building", "revelation", "conflict"]
    beat_types = [type_cycle[i % len(type_cycle)] for i in range(beat_count)]
    # 最后一个强制为冲突或揭露（留悬念）
    if beat_types[-1] == "transition":
        beat_types[-1] = "conflict"

    beats: List[Dict[str, Any]] = []
    word_per_beat = 3000 // beat_count  # 假设每章约 3000 字
    for i in range(beat_count):
        beat = _default_beat(i + 1, beat_types[i], f"[待填充] Beat {i + 1} 场景概要")
        beat["word_target"] = word_per_beat
        beats.append(beat)

    sheet = {
        "chapter": chapter,
        "chapter_goal": args.chapter_goal,
        "previous_ending": args.previous_ending or "",
        "allowed_plot_range": allowed_range,
        "forbidden_reveals": forbidden,
        "beat_count": beat_count,
        "beats": beats,
        "created_at": dt.datetime.now().isoformat(),
    }

    path = _beat_sheet_path(root, chapter, cfg)
    ensure_dir(path.parent)
    ok = save_json(path, sheet, indent=cfg.default_indent)

    return {
        "ok": ok, "command": "generate",
        "beat_sheet_file": str(path),
        "chapter": chapter,
        "beat_count": beat_count,
        "message": "Beat Sheet 骨架已生成，请填充每个 Beat 的具体内容后执行 validate",
    }


def cmd_expand(args: argparse.Namespace, cfg: BeatConfig) -> Dict[str, Any]:
    """为单个 Beat 生成扩写提示词。"""
    root = Path(args.project_root).expanduser().resolve()
    chapter = args.chapter
    beat_id = args.beat_id

    sheet_path = _beat_sheet_path(root, chapter, cfg)
    sheet = load_json(sheet_path, default={})
    beats = sheet.get("beats", [])

    target_beat = None
    for b in beats:
        if isinstance(b, dict) and b.get("beat_id") == beat_id:
            target_beat = b
            break

    if target_beat is None:
        return {
            "ok": False, "command": "expand",
            "error": f"Beat {beat_id} 不存在于章节 {chapter} 的 Beat Sheet 中",
        }

    beat_type_cn = BEAT_TYPES.get(target_beat.get("type", ""), "未知")
    characters = "、".join(target_beat.get("characters", [])) or "待定"
    location = target_beat.get("location", "待定")
    word_target = target_beat.get("word_target", 800)
    anti_res = target_beat.get("anti_resolution", False)

    prompt_lines = [
        f"## Beat {beat_id} 扩写指令（{beat_type_cn}）",
        "",
        f"**场景概要**: {target_beat.get('summary', '')}",
        f"**出场角色**: {characters}",
        f"**地点**: {location}",
        f"**微冲突**: {target_beat.get('micro_conflict', '待定')}",
        f"**情绪弧线**: {target_beat.get('emotion_target', '待定')}",
        f"**目标字数**: {word_target} 字",
        "",
        "### 扩写要求",
        "1. 环境描写：感官细节，不超过 3 句",
        "2. 角色动作与微表情：用动作展现情绪，不用直白描述",
        "3. 对话：带性格差异，避免'报菜名'式信息倾倒",
        "4. 内心独白：限主视角角色，简洁有力",
        "",
        "### 硬约束",
        "- 不得超出本 Beat 的剧情范围",
        "- 不得提前引入后续 Beat 的冲突",
    ]

    if anti_res:
        prompt_lines.append("- **反向刹车**: 不得解决核心矛盾，必须保留悬念")

    forbidden = sheet.get("forbidden_reveals", [])
    if forbidden:
        prompt_lines.append(f"- 禁止揭露: {', '.join(forbidden)}")

    prompt = "\n".join(prompt_lines)

    # 保存扩写提示词
    expand_path = _beat_expand_path(root, chapter, beat_id, cfg)
    ensure_dir(expand_path.parent)
    expand_path.write_text(prompt + "\n", encoding="utf-8")

    return {
        "ok": True, "command": "expand",
        "expand_file": str(expand_path),
        "beat_id": beat_id,
        "chapter": chapter,
        "word_target": word_target,
        "expand_prompt": prompt,
    }


def cmd_validate(args: argparse.Namespace, cfg: BeatConfig) -> Dict[str, Any]:
    """校验 Beat Sheet 是否符合分布规则。"""
    root = Path(args.project_root).expanduser().resolve()
    chapter = args.chapter

    sheet_path = _beat_sheet_path(root, chapter, cfg)
    sheet = load_json(sheet_path, default={})
    beats = sheet.get("beats", [])

    if not beats:
        return {
            "ok": False, "command": "validate",
            "error": f"Beat Sheet 不存在或为空: {sheet_path}",
        }

    errors = _validate_beat_distribution(beats)

    # 额外校验：字数目标总和
    total_words = sum(b.get("word_target", 0) for b in beats)
    if total_words < 2000:
        errors.append(f"total_word_target_low: 总目标字数 {total_words} 偏低（建议 >= 2000）")
    if total_words > 6000:
        errors.append(f"total_word_target_high: 总目标字数 {total_words} 偏高（建议 <= 6000）")

    return {
        "ok": len(errors) == 0,
        "command": "validate",
        "beat_sheet_file": str(sheet_path),
        "chapter": chapter,
        "beat_count": len(beats),
        "total_word_target": total_words,
        "errors": errors,
        "passed": len(errors) == 0,
    }


# -- CLI -------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Beat Sheet 生成器")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("generate", help="生成 Beat Sheet 骨架")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", type=int, required=True, help="章节号")
    s.add_argument("--chapter-goal", required=True, help="本章目标描述")
    s.add_argument("--previous-ending", default="", help="上章结尾摘要")
    s.add_argument("--beat-count", type=int, default=4, help="Beat 数量（3-5）")

    s = sub.add_parser("expand", help="生成单个 Beat 的扩写提示词")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", type=int, required=True)
    s.add_argument("--beat-id", type=int, required=True, help="Beat 编号")

    s = sub.add_parser("validate", help="校验 Beat Sheet 分布规则")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", type=int, required=True)

    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = BeatConfig()

    dispatch = {
        "generate": cmd_generate,
        "expand": cmd_expand,
        "validate": cmd_validate,
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
