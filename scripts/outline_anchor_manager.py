#!/usr/bin/env python3
"""大纲锚点管理器。

子命令：
1. init        — 根据 novel_plan.md 初始化锚点
2. check       — 检查章节推进范围并输出约束 prompt
3. advance     — 推进到下一章/指定章
4. recalculate — 改纲后重算所有锚点
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

# ── 中文数字 → 阿拉伯数字 ────────────────────────────────────────

_CN_NUM = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
           "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
           "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20}


def _cn_to_int(s: str) -> int:
    """尽力将中文数字转为 int，失败返回 0。"""
    if s in _CN_NUM:
        return _CN_NUM[s]
    try:
        return int(s)
    except (ValueError, TypeError):
        return 0


# ── 配置 ──────────────────────────────────────────────────────────

@dataclass
class AnchorConfig:
    plan_rel_path: str = "00_memory/novel_plan.md"
    anchor_rel_path: str = "00_memory/outline_anchors.json"
    default_total_chapters: int = 600
    default_total_volumes: int = 10
    default_indent: int = 2
    default_forbidden_reveals: List[str] = field(default_factory=lambda: ["终极BOSS身份"])
    default_mandatory_tension: str = "至少保留一个未解决冲突进入下一章"


# ── 内部工具 ──────────────────────────────────────────────────────

def _anchor_path(root: Path, cfg: AnchorConfig) -> Path:
    return root / cfg.anchor_rel_path


def _plan_path(root: Path, cfg: AnchorConfig) -> Path:
    return root / cfg.plan_rel_path


# 支持多种常见大纲格式：
# "第一卷：起势 - 核心冲突 (第1-120章)"
# "第1卷 起势（第1章-第120章）"
# "## 卷一 起势  第1-120章"
_VOL_RE = re.compile(
    r"(?:第|卷)\s*([一二三四五六七八九十\d]+)\s*卷?[：:\s]*"
    r"([^\n\-（(]+?)\s*(?:-|—|：|:)\s*([^\n（(]+?)\s*"
    r"[（(]?第?(\d+)\s*[-~至到]\s*第?(\d+)\s*章[）)]?"
)

_VOL_SIMPLE_RE = re.compile(
    r"第\s*([一二三四五六七八九十\d]+)\s*卷[：:\s]+([^\n]+)"
)


def _parse_volumes(plan_text: str, cfg: AnchorConfig) -> List[Dict[str, Any]]:
    vols: List[Dict[str, Any]] = []

    for m in _VOL_RE.finditer(plan_text):
        vol_num = _cn_to_int(m.group(1)) or (len(vols) + 1)
        title = m.group(2).strip()
        core = m.group(3).strip()
        start = int(m.group(4))
        end = int(m.group(5))
        vols.append({
            "volume": vol_num, "title": title,
            "chapter_range": [start, end],
            "core_conflict": core,
            "must_not_reveal": [], "must_achieve": [],
            "foreshadows_to_plant": [],
        })

    if vols:
        return vols

    # 回退：尝试简单格式
    for i, m in enumerate(_VOL_SIMPLE_RE.finditer(plan_text), start=1):
        vols.append({
            "volume": _cn_to_int(m.group(1)) or i,
            "title": m.group(2).strip()[:30],
            "chapter_range": [0, 0],
            "core_conflict": "待补充",
            "must_not_reveal": [], "must_achieve": [],
            "foreshadows_to_plant": [],
        })

    if vols:
        # 均分章节
        per = max(1, cfg.default_total_chapters // len(vols))
        for i, v in enumerate(vols):
            v["chapter_range"] = [i * per + 1, (i + 1) * per if i < len(vols) - 1 else cfg.default_total_chapters]
        return vols

    # 最终回退：均匀分卷
    per = max(1, cfg.default_total_chapters // cfg.default_total_volumes)
    for i in range(1, cfg.default_total_volumes + 1):
        s = (i - 1) * per + 1
        e = i * per if i < cfg.default_total_volumes else cfg.default_total_chapters
        vols.append({
            "volume": i, "title": f"第{i}卷",
            "chapter_range": [s, e],
            "core_conflict": "待补充",
            "must_not_reveal": [], "must_achieve": [],
            "foreshadows_to_plant": [],
        })
    return vols


def _volume_for_chapter(volumes: List[Dict[str, Any]], chapter: int) -> Dict[str, Any]:
    for v in volumes:
        r = v.get("chapter_range", [1, 1])
        if isinstance(r, list) and len(r) == 2 and int(r[0]) <= chapter <= int(r[1]):
            return v
    return volumes[-1] if volumes else {"volume": 1, "title": "第一卷", "chapter_range": [1, chapter]}


def _progress(chapter: int, total: int) -> float:
    return round((chapter / total) * 100, 2) if total > 0 else 0.0


def _build_current_node(anchors: Dict[str, Any], chapter: int) -> Dict[str, Any]:
    volumes = anchors.get("volumes", [])
    vol = _volume_for_chapter(volumes, chapter)
    start, end = vol.get("chapter_range", [1, chapter])
    forbidden = list(vol.get("must_not_reveal") or []) + list(anchors.get("global_forbidden_reveals") or [])
    return {
        "volume": int(vol.get("volume", 1)),
        "chapter": chapter,
        "allowed_plot_range": f"当前卷允许推进区间：第{start}-{end}章的卷内冲突，不得提前收束终局主线",
        "forbidden_reveals": sorted(set(forbidden)),
        "mandatory_tension": anchors.get("mandatory_tension") or "至少保留一个未解决冲突进入下一章",
    }


def _load_anchors(path: Path) -> Dict[str, Any]:
    return load_json(path, default={
        "total_chapters_target": 0, "total_volumes": 0,
        "current_chapter": 1, "current_volume": 1,
        "progress_percent": 0.0, "volumes": [], "current_node": {},
    })


# ── 子命令 ────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace, cfg: AnchorConfig) -> Dict[str, Any]:
    root = Path(args.project_root).expanduser().resolve()
    plan = read_text(_plan_path(root, cfg), default="")
    volumes = _parse_volumes(plan, cfg)

    total = args.total_chapters_target or (
        max(int(v["chapter_range"][1]) for v in volumes) if volumes else cfg.default_total_chapters
    )
    cur = max(1, args.current_chapter)
    vol = _volume_for_chapter(volumes, cur)

    anchors: Dict[str, Any] = {
        "version": "1.0",
        "updated_at": dt.datetime.now().isoformat(),
        "total_chapters_target": total,
        "total_volumes": len(volumes),
        "current_chapter": cur,
        "current_volume": int(vol.get("volume", 1)),
        "progress_percent": _progress(cur, total),
        "volumes": volumes,
        "global_forbidden_reveals": cfg.default_forbidden_reveals,
        "mandatory_tension": cfg.default_mandatory_tension,
    }
    anchors["current_node"] = _build_current_node(anchors, cur)

    path = _anchor_path(root, cfg)
    ensure_dir(path.parent)
    ok = save_json(path, anchors, indent=cfg.default_indent)
    return {
        "ok": ok, "command": "init",
        "anchor_file": str(path),
        "current_chapter": cur,
        "total_chapters_target": total,
        "volume_count": len(volumes),
    }


def cmd_check(args: argparse.Namespace, cfg: AnchorConfig) -> Dict[str, Any]:
    root = Path(args.project_root).expanduser().resolve()
    path = _anchor_path(root, cfg)
    anchors = _load_anchors(path)

    chapter = args.chapter if args.chapter is not None else int(anchors.get("current_chapter", 1))
    total = int(anchors.get("total_chapters_target", 0))
    volumes = anchors.get("volumes", [])
    vol = _volume_for_chapter(volumes, chapter)
    start, end = vol.get("chapter_range", [1, chapter])
    current_node = _build_current_node(anchors, chapter)

    prompt = (
        f"当前是第 {chapter} 章（共 {total} 章），进度 {_progress(chapter, total)}%。\n"
        f"当前卷：{vol.get('title', '未命名卷')}（第{start}-{end}章）。\n"
        f"本章推进范围：{current_node['allowed_plot_range']}。\n"
        f"本章禁止揭露：{', '.join(current_node['forbidden_reveals']) or '无'}。\n"
        f"本章必须保留：{current_node['mandatory_tension']}。"
    )

    return {
        "ok": True, "command": "check",
        "anchor_file": str(path),
        "chapter": chapter,
        "in_range": int(start) <= chapter <= int(end),
        "constraints_prompt": prompt,
        "current_node": current_node,
    }


def cmd_advance(args: argparse.Namespace, cfg: AnchorConfig) -> Dict[str, Any]:
    root = Path(args.project_root).expanduser().resolve()
    path = _anchor_path(root, cfg)
    anchors = _load_anchors(path)

    if not anchors.get("volumes"):
        return {"ok": False, "command": "advance", "error": "锚点未初始化，请先执行 init"}

    cur = int(anchors.get("current_chapter", 1))
    to_ch = int(args.to_chapter) if args.to_chapter is not None else (cur + 1)
    to_ch = max(1, to_ch)

    vol = _volume_for_chapter(anchors["volumes"], to_ch)
    total = int(anchors.get("total_chapters_target", 0))
    anchors.update({
        "current_chapter": to_ch,
        "current_volume": int(vol.get("volume", 1)),
        "progress_percent": _progress(to_ch, total),
        "updated_at": dt.datetime.now().isoformat(),
    })
    anchors["current_node"] = _build_current_node(anchors, to_ch)

    ok = save_json(path, anchors, indent=cfg.default_indent)
    return {
        "ok": ok, "command": "advance",
        "from_chapter": cur, "to_chapter": to_ch,
        "current_volume": anchors["current_volume"],
        "progress_percent": anchors["progress_percent"],
    }


def cmd_recalculate(args: argparse.Namespace, cfg: AnchorConfig) -> Dict[str, Any]:
    root = Path(args.project_root).expanduser().resolve()
    path = _anchor_path(root, cfg)
    anchors = _load_anchors(path)
    cur = int(anchors.get("current_chapter", 1))

    plan = read_text(_plan_path(root, cfg), default="")
    volumes = _parse_volumes(plan, cfg)
    total = max(int(v["chapter_range"][1]) for v in volumes) if volumes else cfg.default_total_chapters
    vol = _volume_for_chapter(volumes, cur)

    anchors.update({
        "volumes": volumes,
        "total_volumes": len(volumes),
        "total_chapters_target": total,
        "current_volume": int(vol.get("volume", 1)),
        "progress_percent": _progress(cur, total),
        "updated_at": dt.datetime.now().isoformat(),
    })
    anchors["current_node"] = _build_current_node(anchors, cur)

    ok = save_json(path, anchors, indent=cfg.default_indent)
    return {
        "ok": ok, "command": "recalculate",
        "current_chapter": cur,
        "total_chapters_target": total,
        "volume_count": len(volumes),
    }


# ── CLI ───────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="大纲锚点管理器")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="根据 novel_plan 初始化锚点")
    s.add_argument("--project-root", required=True)
    s.add_argument("--current-chapter", type=int, default=1)
    s.add_argument("--total-chapters-target", type=int, default=0)

    s = sub.add_parser("check", help="检查章节推进范围并输出约束 prompt")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", type=int, default=None)

    s = sub.add_parser("advance", help="推进到下一章/指定章")
    s.add_argument("--project-root", required=True)
    s.add_argument("--to-chapter", type=int, default=None)

    s = sub.add_parser("recalculate", help="改纲后重算锚点")
    s.add_argument("--project-root", required=True)

    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = AnchorConfig()

    dispatch = {
        "init": cmd_init, "check": cmd_check,
        "advance": cmd_advance, "recalculate": cmd_recalculate,
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
