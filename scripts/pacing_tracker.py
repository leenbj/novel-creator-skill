#!/usr/bin/env python3
"""节奏档位追踪器（Pacing Tracker）。

维护每章的节奏档位历史（慢档/中档/快档），并在门禁时校验卷内
快档配额、慢档最低要求及连续快档上限。

子命令：
1. init   — 初始化状态文件
2. record — 记录章节档位
3. check  — 校验当前卷节奏分布
4. status — 查看节奏状态
"""

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import ensure_dir, load_json, save_json

# 有效档位
VALID_TIERS = {"slow", "medium", "fast"}

# 事件类型 → 档位映射（快档类型 / 慢档类型）
_FAST_TYPES = {"conflict_thrill", "tension_escalation"}
_SLOW_TYPES = {"bond_deepening", "world_painting"}


# ── 配置 ─────────────────────────────────────────────────────────────


@dataclass
class PacingConfig:
    history_rel_path: str = "00_memory/pacing_history.json"
    anchors_rel_path: str = "00_memory/outline_anchors.json"
    # 每卷快档章节数上限（Iron Law: ≤ 2-3 次）
    max_fast_per_volume: int = 3
    # 快档章节连续上限（连续超过此值即报错）
    max_consecutive_fast: int = 1
    # 每 N 章中至少 1 章慢档（慢档最低密度分母）
    slow_density_window: int = 4
    default_indent: int = 2


# ── 内部工具 ─────────────────────────────────────────────────────────


def _now_str() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _history_path(root: Path, cfg: PacingConfig) -> Path:
    return root / cfg.history_rel_path


def _empty_state(cfg: PacingConfig) -> Dict[str, Any]:
    return {
        "version": 1,
        "updated_at": _now_str(),
        "history": [],
        "volume_stats": {},
    }


def _load_state(root: Path, cfg: PacingConfig) -> Dict[str, Any]:
    state = load_json(_history_path(root, cfg), default=_empty_state(cfg))
    state.setdefault("version", 1)
    state.setdefault("updated_at", _now_str())
    state.setdefault("history", [])
    state.setdefault("volume_stats", {})
    return state


def _save_state(root: Path, state: Dict[str, Any], cfg: PacingConfig) -> bool:
    state["updated_at"] = _now_str()
    return save_json(_history_path(root, cfg), state, indent=cfg.default_indent)


def _parse_event_types(raw: str) -> List[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def _load_volumes(root: Path, cfg: PacingConfig) -> List[Dict[str, Any]]:
    anchors = load_json(root / cfg.anchors_rel_path, default={})
    vols = anchors.get("volumes", [])
    return vols if isinstance(vols, list) else []


def _volume_for_chapter(volumes: List[Dict[str, Any]], chapter: int) -> int:
    """从 outline_anchors volumes 推断章节所属卷号；无法推断时返回 1。"""
    for vol in volumes:
        ch_range = vol.get("chapter_range", [])
        if isinstance(ch_range, list) and len(ch_range) == 2:
            if int(ch_range[0]) <= chapter <= int(ch_range[1]):
                return int(vol.get("volume", 1))
    return int(volumes[-1].get("volume", 1)) if volumes else 1


def infer_tier_from_event_types(event_types: List[str]) -> str:
    """从事件类型列表推断节奏档位。

    规则：
    - 同时含快档和慢档事件 → medium（混合场景）
    - 仅含快档事件 → fast
    - 仅含慢档事件 → slow
    - 其他（faction_building 等）→ medium
    """
    event_set = set(event_types)
    has_fast = bool(event_set & _FAST_TYPES)
    has_slow = bool(event_set & _SLOW_TYPES)
    if has_fast and has_slow:
        return "medium"
    if has_fast:
        return "fast"
    if has_slow:
        return "slow"
    return "medium"


def _rebuild_volume_stats(history: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    stats: Dict[str, Dict[str, int]] = {}
    for item in history:
        vk = str(int(item.get("volume", 1)))
        tier = str(item.get("tier", "medium"))
        bucket = stats.setdefault(vk, {"slow": 0, "medium": 0, "fast": 0})
        bucket[tier] = bucket.get(tier, 0) + 1
    return stats


def _upsert_entry(
    history: List[Dict[str, Any]],
    chapter: int,
    tier: str,
    volume: int,
    event_types: List[str],
) -> List[Dict[str, Any]]:
    """幂等插入/替换章节记录，按章号排序。"""
    filtered = [h for h in history if int(h.get("chapter", -1)) != chapter]
    filtered.append(
        {"chapter": chapter, "tier": tier, "volume": volume, "event_types": event_types}
    )
    return sorted(filtered, key=lambda h: int(h.get("chapter", 0)))


def _volume_entries(
    history: List[Dict[str, Any]], volume: int, up_to_chapter: int
) -> List[Dict[str, Any]]:
    """返回指定卷、章号 ≤ up_to_chapter 的所有记录（按章号排序）。"""
    return sorted(
        [
            h for h in history
            if int(h.get("volume", 1)) == volume
            and int(h.get("chapter", 0)) <= up_to_chapter
        ],
        key=lambda h: int(h.get("chapter", 0)),
    )


def _required_slow_chapters(total: int, window: int) -> int:
    """按"每 window 章至少 1 章慢档"计算最低慢档数。"""
    if total < window:
        return 0
    return total // window


def _max_consecutive_fast(entries: List[Dict[str, Any]]) -> int:
    """返回连续快档章节的最长连续长度。"""
    max_streak = 0
    streak = 0
    for entry in entries:
        if str(entry.get("tier", "")) == "fast":
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


# ── 子命令 ───────────────────────────────────────────────────────────


def cmd_init(args: argparse.Namespace, cfg: PacingConfig) -> Dict[str, Any]:
    root = Path(args.project_root).expanduser().resolve()
    path = _history_path(root, cfg)
    ensure_dir(path.parent)
    state = _empty_state(cfg)
    if not _save_state(root, state, cfg):
        return {"ok": False, "command": "init", "error": f"无法写入: {path}"}
    return {"ok": True, "command": "init", "path": str(path)}


def cmd_record(args: argparse.Namespace, cfg: PacingConfig) -> Dict[str, Any]:
    root = Path(args.project_root).expanduser().resolve()
    chapter = int(args.chapter)
    if chapter <= 0:
        return {"ok": False, "command": "record", "error": "章节号必须 > 0"}

    event_types = _parse_event_types(getattr(args, "event_types", "") or "")
    # 档位：CLI 显式指定优先，否则从事件类型推断
    raw_tier = (getattr(args, "tier", None) or "").strip()
    tier = raw_tier if raw_tier in VALID_TIERS else infer_tier_from_event_types(event_types)

    volumes = _load_volumes(root, cfg)
    volume = _volume_for_chapter(volumes, chapter)

    state = _load_state(root, cfg)
    history = _upsert_entry(state["history"], chapter, tier, volume, event_types)
    state["history"] = history
    state["volume_stats"] = _rebuild_volume_stats(history)

    if not _save_state(root, state, cfg):
        return {"ok": False, "command": "record", "error": "写入 pacing_history.json 失败"}

    vol_stats = state["volume_stats"].get(str(volume), {"slow": 0, "medium": 0, "fast": 0})
    return {
        "ok": True, "command": "record",
        "chapter": chapter, "tier": tier,
        "volume": volume, "event_types": event_types,
        "volume_stats": vol_stats,
    }


def cmd_check(args: argparse.Namespace, cfg: PacingConfig) -> Dict[str, Any]:
    root = Path(args.project_root).expanduser().resolve()
    chapter = int(args.chapter)
    max_fast = int(getattr(args, "max_fast_per_volume", cfg.max_fast_per_volume))

    if chapter <= 0:
        return {
            "ok": True, "command": "check", "passed": True,
            "errors": [], "warnings": ["章节号无效，跳过节奏校验"],
            "volume": None, "stats": {},
        }

    # 当前章预期档位：门禁时 record 还未执行，需传入预期档位做预演
    raw_tier = str(getattr(args, "current_tier", "") or "").strip()
    current_event_types = _parse_event_types(getattr(args, "current_event_types", "") or "")
    if raw_tier in VALID_TIERS:
        current_tier: Optional[str] = raw_tier
    elif current_event_types:
        current_tier = infer_tier_from_event_types(current_event_types)
    else:
        current_tier = None  # 无法预演，只校验历史

    state = _load_state(root, cfg)
    history: List[Dict[str, Any]] = state.get("history", [])

    if not history and current_tier is None:
        return {
            "ok": True, "command": "check", "passed": True,
            "errors": [], "warnings": ["尚无节奏记录，跳过档位分布校验"],
            "volume": None, "stats": {},
        }

    volumes = _load_volumes(root, cfg)
    volume = _volume_for_chapter(volumes, chapter)

    # 将当前章预期档位临时插入历史做预演（不写磁盘）
    preview_history = history
    if current_tier is not None:
        preview_history = _upsert_entry(history, chapter, current_tier, volume, current_event_types)

    entries = _volume_entries(preview_history, volume, chapter)
    total = len(entries)

    # 从预演历史重算 vol_stats（不依赖磁盘缓存）
    vol_stats: Dict[str, int] = {"slow": 0, "medium": 0, "fast": 0}
    for entry in entries:
        t = str(entry.get("tier", "medium"))
        vol_stats[t] = vol_stats.get(t, 0) + 1

    errors: List[str] = []
    warnings: List[str] = []

    # 规则1：快档配额硬上限
    fast_count = vol_stats.get("fast", 0)
    if fast_count > max_fast:
        errors.append(
            f"第{volume}卷快档章节数超限（{fast_count} > {max_fast}），"
            "快档配额耗尽，本章不可为快档"
        )

    # 规则2：慢档最低密度（每 slow_density_window 章至少 1 章慢档）
    required_slow = _required_slow_chapters(total, cfg.slow_density_window)
    slow_count = vol_stats.get("slow", 0)
    if required_slow > 0 and slow_count < required_slow:
        errors.append(
            f"第{volume}卷慢档章节不足（{slow_count} < {required_slow}），"
            f"每{cfg.slow_density_window}章至少1章慢档"
        )

    # 规则3：连续快档上限（含本章预演）
    max_streak = _max_consecutive_fast(entries)
    if max_streak > cfg.max_consecutive_fast:
        errors.append(
            f"第{volume}卷连续 {max_streak} 章快档，"
            f"上限为 {cfg.max_consecutive_fast} 章，快档后必须插入慢/中档缓冲"
        )

    # 软提示：快档配额接近耗尽
    if 0 < max_fast - fast_count <= 1:
        warnings.append(f"第{volume}卷快档配额仅剩 {max_fast - fast_count} 次，请谨慎使用")

    return {
        "ok": True, "command": "check",
        "passed": len(errors) == 0,
        "errors": errors, "warnings": warnings,
        "volume": volume, "stats": vol_stats,
        "current_tier": current_tier,
    }


def cmd_status(args: argparse.Namespace, cfg: PacingConfig) -> Dict[str, Any]:
    root = Path(args.project_root).expanduser().resolve()
    state = _load_state(root, cfg)
    payload: Dict[str, Any] = {
        "ok": True, "command": "status",
        "updated_at": state.get("updated_at"),
        "history": state.get("history", []),
        "volume_stats": state.get("volume_stats", {}),
    }
    chapter: Optional[int] = getattr(args, "chapter", None)
    if chapter is not None and int(chapter) > 0:
        volumes = _load_volumes(root, cfg)
        volume = _volume_for_chapter(volumes, int(chapter))
        payload["chapter"] = int(chapter)
        payload["volume"] = volume
        payload["stats"] = state.get("volume_stats", {}).get(
            str(volume), {"slow": 0, "medium": 0, "fast": 0}
        )
    return payload


# ── CLI ──────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="节奏档位追踪器")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="初始化节奏状态文件")
    s.add_argument("--project-root", required=True)

    s = sub.add_parser("record", help="记录章节节奏档位")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", required=True, type=int)
    s.add_argument("--tier", choices=list(VALID_TIERS), help="档位（缺省时从事件类型推断）")
    s.add_argument("--event-types", default="", help="逗号分隔事件类型列表")

    s = sub.add_parser("check", help="校验当前卷节奏分布")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", required=True, type=int)
    s.add_argument("--max-fast-per-volume", type=int, default=3)
    s.add_argument("--current-tier", choices=list(VALID_TIERS),
                   help="当前章预期档位（门禁时 record 未执行，传入做预演）")
    s.add_argument("--current-event-types", default="",
                   help="当前章事件类型，逗号分隔（档位推断用）")

    s = sub.add_parser("status", help="查看节奏历史")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", type=int, help="指定章节时附加卷统计")

    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = PacingConfig()
    dispatch = {
        "init": cmd_init, "record": cmd_record,
        "check": cmd_check, "status": cmd_status,
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
