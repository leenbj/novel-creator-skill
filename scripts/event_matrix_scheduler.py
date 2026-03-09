#!/usr/bin/env python3
"""事件矩阵调度器。

管理事件类型的冷却机制，防止章节模式化。

子命令：
1. init      — 初始化事件矩阵状态
2. status    — 查询各事件类型的冷却状态
3. recommend — 为下一章推荐事件类型分配
4. record    — 记录本章使用的事件类型
"""

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import ensure_dir, load_json, save_json

# ── 常量 ──────────────────────────────────────────────────────────

EVENT_TYPES: Set[str] = {
    "conflict_thrill",     # 冲突爽点：打脸/捡漏/突破/逆转
    "bond_deepening",      # 人物羁绊：与配角互动/共患难
    "faction_building",    # 势力经营：产业/人情/招揽
    "world_painting",      # 风土人情：时代背景/民俗/技术
    "tension_escalation",  # 危机升级：暗线推进/反派布局
}

EVENT_LABELS: Dict[str, str] = {
    "conflict_thrill": "冲突爽点",
    "bond_deepening": "人物羁绊",
    "faction_building": "势力经营",
    "world_painting": "风土人情",
    "tension_escalation": "危机升级",
}

# ── 配置 ──────────────────────────────────────────────────────────

@dataclass
class EventMatrixConfig:
    state_rel_path: str = "00_memory/event_matrix_state.json"
    default_indent: int = 2
    history_limit: int = 500
    cooldowns: Dict[str, int] = field(default_factory=lambda: {
        "conflict_thrill": 2,
        "bond_deepening": 1,
        "faction_building": 2,
        "world_painting": 3,
        "tension_escalation": 2,
    })
    max_consecutive_conflict: int = 2
    gentle_window_size: int = 5  # 每N章至少一次 bond/world


# ── 内部工具 ──────────────────────────────────────────────────────

def _state_path(root: Path, cfg: EventMatrixConfig) -> Path:
    return root / cfg.state_rel_path


def _empty_state(cfg: EventMatrixConfig) -> Dict[str, Any]:
    types = {
        k: {"cooldown": v, "last_used_chapter": 0}
        for k, v in cfg.cooldowns.items()
    }
    return {
        "version": "1.0",
        "updated_at": dt.datetime.now().isoformat(),
        "types": types,
        "history": [],
    }


def _load_state(path: Path, cfg: EventMatrixConfig) -> Dict[str, Any]:
    st = load_json(path, default=_empty_state(cfg))
    if not isinstance(st.get("types"), dict):
        st["types"] = _empty_state(cfg)["types"]
    if not isinstance(st.get("history"), list):
        st["history"] = []
    # 确保所有事件类型都存在
    for k, cd in cfg.cooldowns.items():
        if k not in st["types"] or not isinstance(st["types"][k], dict):
            st["types"][k] = {"cooldown": cd, "last_used_chapter": 0}
        st["types"][k].setdefault("cooldown", cd)
        st["types"][k].setdefault("last_used_chapter", 0)
    return st


def _save_state(path: Path, st: Dict[str, Any], cfg: EventMatrixConfig) -> bool:
    st["updated_at"] = dt.datetime.now().isoformat()
    return save_json(path, st, indent=cfg.default_indent)


def _is_available(next_ch: int, last_used: int, cooldown: int) -> bool:
    if last_used <= 0:
        return True
    return (next_ch - last_used) > cooldown


def _recent_types(history: List[Dict[str, Any]], from_ch: int, to_ch: int) -> List[str]:
    out: List[str] = []
    for h in history:
        if not isinstance(h, dict):
            continue
        ch = int(h.get("chapter", 0) or 0)
        if from_ch <= ch <= to_ch:
            ts = h.get("types", [])
            if isinstance(ts, list):
                out.extend(str(x) for x in ts)
    return out


def _consecutive_conflict(history: List[Dict[str, Any]], next_ch: int) -> int:
    count = 0
    ch = next_ch - 1
    while ch > 0:
        rec = next((x for x in history if isinstance(x, dict) and int(x.get("chapter", 0) or 0) == ch), None)
        if not rec:
            break
        types = rec.get("types", [])
        if isinstance(types, list) and "conflict_thrill" in types:
            count += 1
            ch -= 1
        else:
            break
    return count


# ── 子命令 ────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace, cfg: EventMatrixConfig) -> Dict[str, Any]:
    root = Path(args.project_root).expanduser().resolve()
    path = _state_path(root, cfg)
    ensure_dir(path.parent)

    if path.exists() and not args.force:
        st = _load_state(path, cfg)
        return {
            "ok": True, "command": "init",
            "state_file": str(path), "created": False,
            "event_type_count": len(st.get("types", {})),
            "message": "状态已存在；如需覆盖请加 --force",
        }

    st = _empty_state(cfg)
    ok = _save_state(path, st, cfg)
    return {"ok": ok, "command": "init", "state_file": str(path), "created": ok}


def cmd_status(args: argparse.Namespace, cfg: EventMatrixConfig) -> Dict[str, Any]:
    root = Path(args.project_root).expanduser().resolve()
    path = _state_path(root, cfg)
    st = _load_state(path, cfg)

    chapter = int(args.chapter or 0)
    status: Dict[str, Any] = {}
    for et, meta in st.get("types", {}).items():
        cd = int(meta.get("cooldown", 0) or 0)
        last = int(meta.get("last_used_chapter", 0) or 0)
        available = _is_available(chapter, last, cd) if chapter > 0 else True
        remaining = max(0, cd - (chapter - last) + 1) if chapter > 0 and last > 0 else 0
        status[et] = {
            "label": EVENT_LABELS.get(et, et),
            "cooldown": cd,
            "last_used_chapter": last,
            "available": available,
            "remaining_chapters": remaining if chapter > 0 else None,
        }

    return {
        "ok": True, "command": "status",
        "state_file": str(path),
        "chapter": chapter if chapter > 0 else None,
        "types": status,
        "history_size": len(st.get("history", [])),
    }


def cmd_recommend(args: argparse.Namespace, cfg: EventMatrixConfig) -> Dict[str, Any]:
    root = Path(args.project_root).expanduser().resolve()
    path = _state_path(root, cfg)
    st = _load_state(path, cfg)

    chapter = int(args.chapter)
    if chapter <= 0:
        return {"ok": False, "command": "recommend", "error": "章节号必须大于0"}

    types_meta = st.get("types", {})
    history = st.get("history", [])

    # 1. 计算冷却可用池（按距离上次使用排序，越久越优先）
    available: List[Tuple[str, int]] = []
    blocked: List[str] = []
    for et in sorted(EVENT_TYPES):
        meta = types_meta.get(et, {})
        last = int(meta.get("last_used_chapter", 0) or 0)
        cd = int(meta.get("cooldown", cfg.cooldowns.get(et, 1)) or 0)
        if _is_available(chapter, last, cd):
            score = chapter - last if last > 0 else 10**6
            available.append((et, score))
        else:
            blocked.append(et)

    # 2. 冲突爽点连续限制
    if _consecutive_conflict(history, chapter) >= cfg.max_consecutive_conflict:
        available = [(et, sc) for et, sc in available if et != "conflict_thrill"]
        if "conflict_thrill" not in blocked:
            blocked.append("conflict_thrill")

    # 3. 柔和事件强制（每N章至少一次 bond/world）
    force_gentle = False
    win_start = max(1, chapter - cfg.gentle_window_size + 1)
    recent = _recent_types(history, win_start, chapter - 1)
    if "bond_deepening" not in recent and "world_painting" not in recent:
        force_gentle = True
        gentle = [x for x in available if x[0] in {"bond_deepening", "world_painting"}]
        others = [x for x in available if x[0] not in {"bond_deepening", "world_painting"}]
        if gentle:
            available = gentle + others

    # 4. 按久未使用排序
    available.sort(key=lambda x: x[1], reverse=True)
    primary = available[0][0] if available else ""
    secondary = [x[0] for x in available[1:3]]

    recommended = [primary] if primary else []
    for s in secondary:
        if s and s not in recommended:
            recommended.append(s)

    return {
        "ok": True, "command": "recommend",
        "chapter": chapter,
        "primary_type": primary,
        "primary_label": EVENT_LABELS.get(primary, ""),
        "secondary_types": secondary,
        "recommended_types": recommended,
        "blocked_types": sorted(set(blocked)),
        "force_gentle_event": force_gentle,
        "notes": [
            f"冲突爽点不得连续超过{cfg.max_consecutive_conflict}章",
            f"每{cfg.gentle_window_size}章至少出现一次 人物羁绊 或 风土人情",
        ],
    }


def cmd_record(args: argparse.Namespace, cfg: EventMatrixConfig) -> Dict[str, Any]:
    root = Path(args.project_root).expanduser().resolve()
    path = _state_path(root, cfg)
    st = _load_state(path, cfg)

    chapter = int(args.chapter)
    if chapter <= 0:
        return {"ok": False, "command": "record", "error": "章节号必须大于0"}

    raw_types = [x.strip() for x in args.types.split(",") if x.strip()]
    if not raw_types:
        return {"ok": False, "command": "record", "error": "至少指定一个事件类型"}

    invalid = [x for x in raw_types if x not in EVENT_TYPES]
    if invalid:
        return {"ok": False, "command": "record", "error": f"非法事件类型: {', '.join(invalid)}"}

    # 去重保序
    seen: Set[str] = set()
    uniq: List[str] = []
    for t in raw_types:
        if t not in seen:
            uniq.append(t)
            seen.add(t)

    # 更新 last_used_chapter
    for t in uniq:
        st["types"][t]["last_used_chapter"] = chapter

    # 更新历史（按章号 upsert）
    history: List[Dict[str, Any]] = []
    replaced = False
    for rec in st.get("history", []):
        if isinstance(rec, dict) and int(rec.get("chapter", 0) or 0) == chapter:
            history.append({"chapter": chapter, "types": uniq})
            replaced = True
        else:
            history.append(rec)
    if not replaced:
        history.append({"chapter": chapter, "types": uniq})

    history = sorted(
        [h for h in history if isinstance(h, dict) and int(h.get("chapter", 0) or 0) > 0],
        key=lambda x: int(x["chapter"]),
    )[-cfg.history_limit:]
    st["history"] = history

    ok = _save_state(path, st, cfg)
    return {
        "ok": ok, "command": "record",
        "chapter": chapter,
        "recorded_types": uniq,
        "recorded_labels": [EVENT_LABELS.get(t, t) for t in uniq],
        "history_size": len(history),
    }


# ── CLI ───────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="事件矩阵调度器")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="初始化事件矩阵状态")
    s.add_argument("--project-root", required=True)
    s.add_argument("--force", action="store_true")

    s = sub.add_parser("status", help="查询事件冷却状态")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", type=int, default=0)

    s = sub.add_parser("recommend", help="推荐下一章事件类型")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", required=True, type=int)

    s = sub.add_parser("record", help="记录本章已使用事件类型")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", required=True, type=int)
    s.add_argument("--types", required=True, help="逗号分隔事件类型列表")

    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = EventMatrixConfig()

    dispatch = {
        "init": cmd_init, "status": cmd_status,
        "recommend": cmd_recommend, "record": cmd_record,
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
