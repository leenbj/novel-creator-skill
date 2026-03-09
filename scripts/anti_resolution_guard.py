#!/usr/bin/env python3
"""反向刹车校验器（Anti-Resolution Guard）。

检查章节是否违反了"非终局章节禁止解决核心冲突"的规则。
设计为门禁流程的增强校验项，可在 /检查一致性 后执行。

子命令：
1. check      — 校验单章是否违反反向刹车规则
2. constraint — 为即将写的章节生成约束 prompt
"""

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import ensure_dir, load_json, read_text, save_json

# ── 配置 ──────────────────────────────────────────────────────────

@dataclass
class AntiResConfig:
    anchor_rel_path: str = "00_memory/outline_anchors.json"
    plan_rel_path: str = "00_memory/novel_plan.md"
    tail_chars: int = 200  # 章末检查区域字符数
    default_indent: int = 2

    # 章末悬念关键词（命中任一即认为有悬念）
    suspense_keywords: List[str] = field(default_factory=lambda: [
        "?", "？", "……", "却", "突然", "竟", "谁知", "不料",
        "正要", "忽然", "然而", "可是", "怎料", "殊不知",
        "这才发现", "心中一凛", "暗道不好", "变了脸色",
        "一道身影", "来人竟是", "门外传来", "信封里",
    ])

    # 核心矛盾解决的信号词（出现多个可能意味着提前收束）
    resolution_signals: List[str] = field(default_factory=lambda: [
        "终于解决", "大功告成", "从此天下太平", "一切尘埃落定",
        "所有问题迎刃而解", "心中的石头终于落地", "再也不用担心",
        "彻底击败", "完全消灭", "一劳永逸", "最终胜利",
    ])


# ── 内部工具 ──────────────────────────────────────────────────────

def _load_anchors(root: Path, cfg: AntiResConfig) -> Dict[str, Any]:
    return load_json(root / cfg.anchor_rel_path, default={})


def _extract_core_conflicts(anchors: Dict[str, Any]) -> List[str]:
    """从锚点中提取当前卷及全局的核心冲突关键词。"""
    conflicts: List[str] = []
    node = anchors.get("current_node", {})
    forbidden = node.get("forbidden_reveals", [])
    if isinstance(forbidden, list):
        conflicts.extend(str(x) for x in forbidden)

    # 从卷信息中提取
    volumes = anchors.get("volumes", [])
    current_vol = int(node.get("volume", 0))
    for v in volumes:
        if int(v.get("volume", 0)) == current_vol:
            core = v.get("core_conflict", "")
            if core:
                conflicts.append(core)
    return conflicts


def _check_tail_suspense(text: str, cfg: AntiResConfig) -> Dict[str, Any]:
    """检查章末是否包含悬念元素。"""
    tail = text[-cfg.tail_chars:] if len(text) > cfg.tail_chars else text
    hits = [kw for kw in cfg.suspense_keywords if kw in tail]
    return {
        "has_suspense": len(hits) > 0,
        "hits": hits,
        "tail_length": len(tail),
    }


def _check_resolution_signals(text: str, cfg: AntiResConfig) -> Dict[str, Any]:
    """检查章节是否包含核心矛盾解决信号。"""
    hits = [sig for sig in cfg.resolution_signals if sig in text]
    return {
        "signal_count": len(hits),
        "signals": hits,
        "risk": "high" if len(hits) >= 2 else ("medium" if len(hits) == 1 else "low"),
    }


def _check_forbidden_reveals(text: str, forbidden: List[str]) -> Dict[str, Any]:
    """检查是否提前揭露了禁止揭露的内容。"""
    hits = [f for f in forbidden if f and f in text]
    return {
        "revealed_count": len(hits),
        "revealed": hits,
    }


# ── 子命令 ────────────────────────────────────────────────────────

def cmd_check(args: argparse.Namespace, cfg: AntiResConfig) -> Dict[str, Any]:
    root = Path(args.project_root).expanduser().resolve()
    chapter_path = Path(args.chapter_file)
    if not chapter_path.is_absolute():
        chapter_path = root / chapter_path

    if not chapter_path.exists():
        return {"ok": False, "command": "check", "error": f"章节文件不存在: {chapter_path}"}

    text = read_text(chapter_path)
    anchors = _load_anchors(root, cfg)
    is_finale = args.is_finale

    # 如果是终局章节，跳过大部分检查
    if is_finale:
        return {
            "ok": True, "command": "check",
            "chapter_file": str(chapter_path),
            "is_finale": True,
            "message": "终局章节，反向刹车规则不适用",
            "checks": {},
        }

    # 执行三项检查
    core_conflicts = _extract_core_conflicts(anchors)
    forbidden = anchors.get("current_node", {}).get("forbidden_reveals", [])

    tail_result = _check_tail_suspense(text, cfg)
    resolution_result = _check_resolution_signals(text, cfg)
    reveal_result = _check_forbidden_reveals(text, forbidden)

    errors: List[str] = []
    warnings: List[str] = []

    # 规则1：核心矛盾解决信号
    if resolution_result["risk"] == "high":
        errors.append(f"检测到多个核心矛盾解决信号: {', '.join(resolution_result['signals'])}")
    elif resolution_result["risk"] == "medium":
        warnings.append(f"检测到核心矛盾解决信号: {resolution_result['signals'][0]}")

    # 规则2：禁止揭露
    if reveal_result["revealed_count"] > 0:
        errors.append(f"提前揭露了禁止揭露的内容: {', '.join(reveal_result['revealed'])}")

    # 规则3：章末悬念
    if not tail_result["has_suspense"]:
        warnings.append("章末未检测到悬念元素，建议添加钩子")

    passed = len(errors) == 0

    return {
        "ok": True, "command": "check",
        "chapter_file": str(chapter_path),
        "is_finale": False,
        "passed": passed,
        "errors": errors,
        "warnings": warnings,
        "checks": {
            "tail_suspense": tail_result,
            "resolution_signals": resolution_result,
            "forbidden_reveals": reveal_result,
        },
    }


def cmd_constraint(args: argparse.Namespace, cfg: AntiResConfig) -> Dict[str, Any]:
    """为即将写的章节生成反向刹车约束 prompt。"""
    root = Path(args.project_root).expanduser().resolve()
    anchors = _load_anchors(root, cfg)
    node = anchors.get("current_node", {})
    forbidden = node.get("forbidden_reveals", [])
    tension = node.get("mandatory_tension", cfg.plan_rel_path)

    core_conflicts = _extract_core_conflicts(anchors)
    core_str = "、".join(core_conflicts[:3]) if core_conflicts else "主线核心矛盾"

    prompt = (
        f"重要约束：不要在本章解决核心矛盾「{core_str}」。\n"
        f"必须保留悬念，制造新的次要障碍，让角色的短期目标落空或延后。\n"
        f"章末必须留下一个让读者想翻下一页的钩子。\n"
    )

    if forbidden:
        prompt += f"本章禁止揭露：{', '.join(forbidden)}。\n"

    prompt += f"张力要求：{tension}。"

    return {
        "ok": True, "command": "constraint",
        "constraint_prompt": prompt,
        "core_conflicts": core_conflicts[:3],
        "forbidden_reveals": forbidden,
    }


# ── CLI ───────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="反向刹车校验器")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("check", help="校验章节是否违反反向刹车规则")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter-file", required=True)
    s.add_argument("--is-finale", action="store_true", help="标记为终局章节（跳过检查）")

    s = sub.add_parser("constraint", help="生成写作约束 prompt")
    s.add_argument("--project-root", required=True)

    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = AntiResConfig()

    dispatch = {"check": cmd_check, "constraint": cmd_constraint}

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
