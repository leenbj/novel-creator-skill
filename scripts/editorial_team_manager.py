#!/usr/bin/env python3
"""编辑团队管理器 - 为 Claude Code Agent Teams 提供状态追踪与协调辅助。

本脚本不直接调用 AI；它负责：
1. 生成团队工作所需的上下文快照（team_context.json）
2. 记录每轮审核结果，构建章节审核历史
3. 检测是否触发「人工介入」条件（连续3章P0未解决）
4. 输出供总编辑 Agent 读取的结构化状态

用法：
  python3 scripts/editorial_team_manager.py snapshot --project-root <路径>
  python3 scripts/editorial_team_manager.py record-review --project-root <路径> \\
      --chapter N --stage <stage> --verdict <pass|conditional|rewrite> \\
      [--p0 X] [--p1 Y] [--p2 Z]
  python3 scripts/editorial_team_manager.py status --project-root <路径>
  python3 scripts/editorial_team_manager.py need-human --project-root <路径>
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import ensure_dir, load_json, save_json, read_text

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

TEAM_DIR_NAME = ".editorial_team"
CONTEXT_FILE = "team_context.json"
REVIEW_LOG_FILE = "review_log.json"
MAX_P0_REWRITE_ROUNDS = 2          # 单章最大重写次数
MAX_CONDITIONAL_CHAPTERS = 3       # 连续有条件通过超过此数强制人工介入


# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------

def _team_dir(project_root: Path) -> Path:
    d = project_root / TEAM_DIR_NAME
    ensure_dir(d)
    return d


def _load_review_log(project_root: Path) -> List[Dict[str, Any]]:
    f = _team_dir(project_root) / REVIEW_LOG_FILE
    data = load_json(f)
    return data if isinstance(data, list) else []


def _save_review_log(project_root: Path, log: List[Dict[str, Any]]) -> None:
    save_json(_team_dir(project_root) / REVIEW_LOG_FILE, log)


# ---------------------------------------------------------------------------
# snapshot：生成上下文快照供 chief-editor 读取
# ---------------------------------------------------------------------------

def cmd_snapshot(project_root: Path) -> Dict[str, Any]:
    """读取关键记忆文件，输出结构化的上下文快照。"""
    mem = project_root / "00_memory"

    def _read(rel: str) -> str:
        p = mem / rel
        return read_text(p) if p.exists() else ""

    novel_plan = _read("novel_plan.md")
    novel_state = _read("novel_state.md")
    char_tracker = _read("character_tracker.md")
    foreshadow = _read("foreshadowing_tracker.md")
    timeline = _read("timeline.md")

    # 解析当前章节号
    chapter_no = 1
    import re
    m = re.search(r"当前章节[：:]\s*第?(\d+)章?", novel_state)
    if m:
        chapter_no = int(m.group(1))

    snapshot = {
        "project_root": str(project_root),
        "snapshot_time": dt.datetime.now().isoformat(timespec="seconds"),
        "current_chapter_no": chapter_no,
        "novel_plan_excerpt": novel_plan[:1500],
        "novel_state_excerpt": novel_state[:1000],
        "character_tracker_excerpt": char_tracker[:2000],
        "foreshadowing_excerpt": foreshadow[:800] if foreshadow else "",
        "timeline_excerpt": timeline[:600] if timeline else "",
        "files": {
            "novel_plan": str(mem / "novel_plan.md"),
            "novel_state": str(mem / "novel_state.md"),
            "character_tracker": str(mem / "character_tracker.md"),
            "foreshadowing_tracker": str(mem / "foreshadowing_tracker.md"),
            "timeline": str(mem / "timeline.md"),
        },
    }

    out_path = _team_dir(project_root) / CONTEXT_FILE
    save_json(out_path, snapshot)

    print(json.dumps({"ok": True, "context_file": str(out_path),
                      "chapter_no": chapter_no}, ensure_ascii=False))
    return snapshot


# ---------------------------------------------------------------------------
# record-review：记录一次审核结果
# ---------------------------------------------------------------------------

def cmd_record_review(
    project_root: Path,
    chapter_no: int,
    stage: str,         # planning | writing | antiAI | consistency | final
    verdict: str,       # pass | conditional | rewrite
    p0: int = 0,
    p1: int = 0,
    p2: int = 0,
    notes: str = "",
) -> None:
    log = _load_review_log(project_root)
    entry: Dict[str, Any] = {
        "chapter_no": chapter_no,
        "stage": stage,
        "verdict": verdict,
        "p0": p0,
        "p1": p1,
        "p2": p2,
        "notes": notes,
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
    }
    log.append(entry)
    _save_review_log(project_root, log)
    print(json.dumps({"ok": True, "recorded": entry}, ensure_ascii=False))


# ---------------------------------------------------------------------------
# status：查看最近若干章的审核汇总
# ---------------------------------------------------------------------------

def cmd_status(project_root: Path, last_n: int = 10) -> None:
    log = _load_review_log(project_root)
    if not log:
        print(json.dumps({"ok": True, "message": "暂无审核记录"}, ensure_ascii=False))
        return

    recent = log[-last_n * 5:]  # 最多每章5步，取最近N章数据
    by_chapter: Dict[int, List[Dict]] = {}
    for entry in recent:
        cn = entry["chapter_no"]
        by_chapter.setdefault(cn, []).append(entry)

    summary: List[Dict[str, Any]] = []
    for cn in sorted(by_chapter.keys())[-last_n:]:
        entries = by_chapter[cn]
        final = next((e for e in reversed(entries) if e["stage"] == "final"), None)
        max_p0 = max(e["p0"] for e in entries)
        summary.append({
            "chapter_no": cn,
            "final_verdict": final["verdict"] if final else "pending",
            "max_p0_in_session": max_p0,
            "stages_completed": [e["stage"] for e in entries],
        })

    print(json.dumps({"ok": True, "summary": summary}, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# need-human：检测是否需要人工介入
# ---------------------------------------------------------------------------

def cmd_need_human(project_root: Path) -> None:
    log = _load_review_log(project_root)

    # 规则1：单章重写次数超上限
    rewrite_counts: Dict[int, int] = {}
    for entry in log:
        if entry["verdict"] == "rewrite":
            cn = entry["chapter_no"]
            rewrite_counts[cn] = rewrite_counts.get(cn, 0) + 1
    excessive = {cn: cnt for cn, cnt in rewrite_counts.items()
                 if cnt > MAX_P0_REWRITE_ROUNDS}

    # 规则2：连续N章有条件通过或重写
    final_verdicts: List[Dict[str, Any]] = [
        e for e in log if e["stage"] == "final"
    ]
    recent_finals = final_verdicts[-(MAX_CONDITIONAL_CHAPTERS):]
    consecutive_unclean = (
        len(recent_finals) >= MAX_CONDITIONAL_CHAPTERS
        and all(e["verdict"] in ("conditional", "rewrite")
                for e in recent_finals)
    )

    need_human = bool(excessive) or consecutive_unclean
    reasons: List[str] = []
    if excessive:
        for cn, cnt in excessive.items():
            reasons.append(
                f"第{cn}章重写 {cnt} 次仍未通过（上限 {MAX_P0_REWRITE_ROUNDS} 次）"
            )
    if consecutive_unclean:
        chapters = [str(e["chapter_no"]) for e in recent_finals]
        reasons.append(
            f"连续 {MAX_CONDITIONAL_CHAPTERS} 章（第{'、'.join(chapters)}章）"
            "未完全通过，存在积累性问题"
        )

    print(json.dumps({
        "ok": True,
        "need_human": need_human,
        "reasons": reasons,
    }, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="编辑团队管理器")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # snapshot
    p_snap = sub.add_parser("snapshot", help="生成上下文快照")
    p_snap.add_argument("--project-root", required=True)

    # record-review
    p_rec = sub.add_parser("record-review", help="记录审核结果")
    p_rec.add_argument("--project-root", required=True)
    p_rec.add_argument("--chapter", type=int, required=True)
    p_rec.add_argument("--stage", required=True,
                       choices=["planning", "writing", "antiAI", "consistency", "final"])
    p_rec.add_argument("--verdict", required=True,
                       choices=["pass", "conditional", "rewrite"])
    p_rec.add_argument("--p0", type=int, default=0)
    p_rec.add_argument("--p1", type=int, default=0)
    p_rec.add_argument("--p2", type=int, default=0)
    p_rec.add_argument("--notes", default="")

    # status
    p_stat = sub.add_parser("status", help="查看审核状态")
    p_stat.add_argument("--project-root", required=True)
    p_stat.add_argument("--last", type=int, default=10)

    # need-human
    p_nh = sub.add_parser("need-human", help="检测是否需要人工介入")
    p_nh.add_argument("--project-root", required=True)

    args = parser.parse_args()
    root = Path(args.project_root).resolve()

    if args.cmd == "snapshot":
        cmd_snapshot(root)
    elif args.cmd == "record-review":
        cmd_record_review(
            root, args.chapter, args.stage, args.verdict,
            args.p0, args.p1, args.p2, args.notes,
        )
    elif args.cmd == "status":
        cmd_status(root, args.last)
    elif args.cmd == "need-human":
        cmd_need_human(root)


if __name__ == "__main__":
    main()
