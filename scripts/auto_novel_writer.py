#!/usr/bin/env python3
"""一键写书调度器 - 全自动完成小说创作全流程。

功能：
1. 解析简介 -> 联网调研 -> 一键开书 -> 循环(调研->写作->门禁) -> 完成报告
2. 支持断点续写（状态持久化到 .flow/auto_write_state.json）
3. 输出 JSON 到 stdout，顶层有 ok: true/false 字段

零外部依赖：只使用标准库 + common.py
"""

import argparse
import datetime as dt
import json
import sys
from math import ceil
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import ensure_dir, read_text, write_text, load_json, save_json

# =============================================================================
# 常量
# =============================================================================

STATE_FILE_NAME = "auto_write_state.json"
FLOW_DIR_NAME = ".flow"
VERSION = "1.0.0"


# =============================================================================
# 卷/章结构计算
# =============================================================================


def compute_structure(
    target_chars: int, chars_per_chapter: int = 3500
) -> Dict[str, int]:
    """根据目标字数计算卷/章结构。

    Args:
        target_chars: 目标总字数
        chars_per_chapter: 每章预估字数

    Returns:
        包含 total_chapters, total_volumes, chapters_per_volume, chars_per_volume 的字典
    """
    total_chapters = max(10, target_chars // chars_per_chapter)
    chars_per_volume = min(450000, max(100000, target_chars // 10))
    total_volumes = max(1, ceil(target_chars / chars_per_volume))
    chapters_per_volume = max(10, total_chapters // total_volumes)
    return {
        "total_chapters": total_chapters,
        "total_volumes": total_volumes,
        "chapters_per_volume": chapters_per_volume,
        "chars_per_volume": chars_per_volume,
        "chars_per_chapter": chars_per_chapter,
    }


# =============================================================================
# 状态持久化
# =============================================================================


def _state_path(project_root: Path) -> Path:
    """获取状态文件路径。"""
    return project_root / FLOW_DIR_NAME / STATE_FILE_NAME


def load_state(project_root: Path) -> Optional[Dict[str, Any]]:
    """从 .flow/auto_write_state.json 加载状态。

    Args:
        project_root: 项目根目录

    Returns:
        状态字典，不存在则返回 None
    """
    sp = _state_path(project_root)
    if not sp.exists():
        return None
    data = load_json(sp)
    if not data:
        return None
    return data


def save_state(project_root: Path, state: Dict[str, Any]) -> bool:
    """保存状态到 .flow/auto_write_state.json。

    Args:
        project_root: 项目根目录
        state: 状态字典

    Returns:
        是否保存成功
    """
    sp = _state_path(project_root)
    ensure_dir(sp.parent)
    state["last_checkpoint"] = dt.datetime.now().isoformat()
    return save_json(sp, state)


def init_state(
    synopsis: str,
    target_chars: int,
    genre: str,
    research_depth: str = "normal",
    chars_per_chapter: int = 3500,
) -> Dict[str, Any]:
    """初始化写书状态。

    Args:
        synopsis: 小说简介/剧情种子
        target_chars: 目标总字数
        genre: 题材
        research_depth: 调研深度 (light/normal/deep)
        chars_per_chapter: 每章预估字数

    Returns:
        初始化后的状态字典
    """
    structure = compute_structure(target_chars, chars_per_chapter)
    now = dt.datetime.now().isoformat()
    return {
        "version": VERSION,
        "phase": "research",
        "synopsis": synopsis,
        "target_chars": target_chars,
        "genre": genre,
        "research_depth": research_depth,
        # 结构信息
        "total_chapters": structure["total_chapters"],
        "total_volumes": structure["total_volumes"],
        "chapters_per_volume": structure["chapters_per_volume"],
        "chars_per_volume": structure["chars_per_volume"],
        "chars_per_chapter": structure["chars_per_chapter"],
        # 进度追踪
        "current_volume": 1,
        "current_chapter": 0,
        "chars_written": 0,
        "chapters_written": 0,
        # 门禁统计
        "gate_passes": 0,
        "gate_failures": 0,
        "auto_repairs": 0,
        # 调研记录
        "research_queries": [],
        # 时间戳
        "started_at": now,
        "last_checkpoint": now,
        "completed": False,
        "error": None,
    }


# =============================================================================
# 进度报告
# =============================================================================


def generate_progress_report(state: Dict[str, Any]) -> str:
    """生成人类可读的进度报告。

    Args:
        state: 当前状态字典

    Returns:
        格式化的进度报告字符串
    """
    if not state:
        return "暂无写书状态。"

    target = state.get("target_chars", 0)
    written = state.get("chars_written", 0)
    pct = (written / target * 100) if target > 0 else 0

    total_ch = state.get("total_chapters", 0)
    done_ch = state.get("chapters_written", 0)
    ch_pct = (done_ch / total_ch * 100) if total_ch > 0 else 0

    passes = state.get("gate_passes", 0)
    failures = state.get("gate_failures", 0)
    total_gate = passes + failures
    gate_rate = (passes / total_gate * 100) if total_gate > 0 else 0

    cur_vol = state.get("current_volume", 1)
    total_vol = state.get("total_volumes", 1)

    lines = [
        f"# 一键写书进度报告",
        f"",
        f"## 基本信息",
        f"- 题材: {state.get('genre', '未知')}",
        f"- 简介: {state.get('synopsis', '无')[:80]}{'...' if len(state.get('synopsis', '')) > 80 else ''}",
        f"- 当前阶段: {state.get('phase', '未知')}",
        f"- 开始时间: {state.get('started_at', '未知')}",
        f"- 上次检查点: {state.get('last_checkpoint', '未知')}",
        f"",
        f"## 进度",
        f"- 字数: {written:,} / {target:,} ({pct:.1f}%)",
        f"- 章节: {done_ch} / {total_ch} ({ch_pct:.1f}%)",
        f"- 卷: 第{cur_vol}卷 / 共{total_vol}卷",
        f"- 每卷章数: {state.get('chapters_per_volume', 0)}",
        f"",
        f"## 门禁统计",
        f"- 通过: {passes}",
        f"- 失败: {failures}",
        f"- 通过率: {gate_rate:.1f}%",
        f"- 自动修复: {state.get('auto_repairs', 0)} 次",
        f"",
        f"## 状态",
        f"- 已完成: {'是' if state.get('completed') else '否'}",
    ]

    if state.get("error"):
        lines.append(f"- 最近错误: {state['error']}")

    research_queries = state.get("research_queries", [])
    if research_queries:
        lines.append(f"")
        lines.append(f"## 调研记录 (最近5条)")
        for q in research_queries[-5:]:
            lines.append(f"- {q}")

    return "\n".join(lines)


# =============================================================================
# 下一步动作计算
# =============================================================================


def _next_action(state: Dict[str, Any]) -> Dict[str, Any]:
    """根据当前状态计算下一步操作。

    Args:
        state: 当前状态

    Returns:
        下一步动作描述字典
    """
    phase = state.get("phase", "research")
    current_chapter = state.get("current_chapter", 0)
    total_chapters = state.get("total_chapters", 10)
    chapters_per_volume = state.get("chapters_per_volume", 10)
    current_volume = state.get("current_volume", 1)
    total_volumes = state.get("total_volumes", 1)

    if phase == "research":
        return {
            "action": "research",
            "description": "联网调研题材背景和世界观",
            "commands": [
                f"根据简介「{state.get('synopsis', '')}」和题材「{state.get('genre', '')}」进行联网调研",
                "收集时代背景、人物原型、地理环境、社会制度等素材",
                "调研完成后执行 progress --chapter 0 进入初始化阶段",
            ],
            "next_phase": "init",
        }

    if phase == "init":
        return {
            "action": "init",
            "description": "执行一键开书初始化项目",
            "commands": [
                f"python3 {SCRIPT_DIR / 'novel_flow_executor.py'} one-click "
                f"--project-root <PROJECT_ROOT> "
                f"--title <书名> --genre {state.get('genre', '待定')} "
                f"--idea \"{state.get('synopsis', '')}\"",
                "初始化完成后执行 progress --chapter 0 进入写作阶段",
            ],
            "next_phase": "writing",
        }

    if phase == "writing":
        if current_chapter >= total_chapters:
            return {
                "action": "complete",
                "description": "全书写作完成",
                "commands": [
                    "执行 report 子命令生成最终报告",
                ],
                "next_phase": "complete",
            }

        next_ch = current_chapter + 1
        action: Dict[str, Any] = {
            "action": "write_chapter",
            "description": f"写作第{next_ch}章（第{current_volume}卷）",
            "chapter": next_ch,
            "volume": current_volume,
            "commands": [],
        }

        # 每10章冲刺复盘
        if next_ch > 1 and (next_ch - 1) % 10 == 0:
            action["sprint_review"] = True
            action["commands"].append(
                f"[冲刺复盘] 回顾前10章(第{next_ch - 10}-{next_ch - 1}章)的节奏、伏笔和角色弧"
            )

        # 每卷结束汇报
        chapter_in_volume = next_ch - (current_volume - 1) * chapters_per_volume
        if chapter_in_volume > chapters_per_volume and current_volume < total_volumes:
            action["volume_complete"] = True
            action["commands"].append(
                f"[卷末汇报] 第{current_volume}卷完成，共{chapters_per_volume}章，准备进入第{current_volume + 1}卷"
            )

        # 写作指令
        action["commands"].extend([
            f"python3 {SCRIPT_DIR / 'novel_flow_executor.py'} continue-write "
            f"--project-root <PROJECT_ROOT> --query \"<第{next_ch}章剧情>\"",
            f"写作完成后执行: python3 {SCRIPT_DIR / 'auto_novel_writer.py'} progress "
            f"--project-root <PROJECT_ROOT> --chapter {next_ch} --chars-added <字数> --gate-passed",
        ])

        return action

    if phase == "complete":
        return {
            "action": "done",
            "description": "全书已完成",
            "commands": [],
        }

    return {
        "action": "unknown",
        "description": f"未知阶段: {phase}",
        "commands": [],
    }


# =============================================================================
# 子命令实现
# =============================================================================


def generate_plan(args: argparse.Namespace) -> Dict[str, Any]:
    """生成执行计划（plan 子命令），不实际执行。

    Args:
        args: 命令行参数

    Returns:
        执行计划 JSON
    """
    synopsis = args.synopsis
    target_chars = args.target_chars
    genre = args.genre
    research_depth = args.research_depth
    chars_per_chapter = getattr(args, "chars_per_chapter", 3500)

    structure = compute_structure(target_chars, chars_per_chapter)

    # 预估写作时间（按每章15分钟估算）
    total_chapters = structure["total_chapters"]
    est_hours = total_chapters * 15 / 60

    plan = {
        "ok": True,
        "command": "plan",
        "synopsis": synopsis,
        "target_chars": target_chars,
        "genre": genre,
        "research_depth": research_depth,
        "structure": structure,
        "estimated_hours": round(est_hours, 1),
        "phases": [
            {
                "phase": "research",
                "description": "联网调研题材背景",
                "estimated_time": "10-30分钟",
                "depth": research_depth,
            },
            {
                "phase": "init",
                "description": "一键开书初始化项目",
                "estimated_time": "1-2分钟",
            },
            {
                "phase": "writing",
                "description": f"循环写作{total_chapters}章",
                "chapters": total_chapters,
                "volumes": structure["total_volumes"],
                "sprint_reviews": max(0, total_chapters // 10),
                "estimated_time": f"约{est_hours:.0f}小时",
            },
            {
                "phase": "complete",
                "description": "生成完成报告",
                "estimated_time": "1分钟",
            },
        ],
        "gate_check_per_chapter": True,
        "auto_retry_on_gate_failure": True,
        "breakpoint_resume_supported": True,
    }
    return plan


def run_auto_write(args: argparse.Namespace) -> Dict[str, Any]:
    """执行一键写书主循环（run 子命令）。

    检查是否有断点状态，有则返回 resume 信息；
    全新开始则 init_state 并返回第一步指令。

    Args:
        args: 命令行参数

    Returns:
        执行状态和下一步指令 JSON
    """
    project_root = Path(args.project_root).expanduser().resolve()
    ensure_dir(project_root / FLOW_DIR_NAME)

    # 检查断点
    existing_state = load_state(project_root)
    if existing_state and not existing_state.get("completed", False):
        next_act = _next_action(existing_state)
        return {
            "ok": True,
            "command": "run",
            "mode": "resume",
            "project_root": str(project_root),
            "state_summary": {
                "phase": existing_state.get("phase"),
                "current_chapter": existing_state.get("current_chapter", 0),
                "total_chapters": existing_state.get("total_chapters", 0),
                "chapters_written": existing_state.get("chapters_written", 0),
                "chars_written": existing_state.get("chars_written", 0),
                "target_chars": existing_state.get("target_chars", 0),
                "last_checkpoint": existing_state.get("last_checkpoint"),
            },
            "next_action": next_act,
            "message": "检测到断点状态，从上次中断处继续。",
        }

    # 全新开始
    synopsis = getattr(args, "synopsis", "") or ""
    target_chars = getattr(args, "target_chars", 100000) or 100000
    genre = getattr(args, "genre", "待定") or "待定"
    research_depth = getattr(args, "research_depth", "normal") or "normal"

    if not synopsis:
        return {
            "ok": False,
            "command": "run",
            "error": "missing_synopsis",
            "message": "缺少 --synopsis 参数，请提供小说简介/剧情种子。",
        }

    state = init_state(synopsis, target_chars, genre, research_depth)
    save_state(project_root, state)

    next_act = _next_action(state)
    return {
        "ok": True,
        "command": "run",
        "mode": "new",
        "project_root": str(project_root),
        "state_summary": {
            "phase": state["phase"],
            "target_chars": state["target_chars"],
            "total_chapters": state["total_chapters"],
            "total_volumes": state["total_volumes"],
        },
        "next_action": next_act,
        "message": "已初始化写书状态，请按 next_action 中的指令执行第一步。",
    }


def update_progress(args: argparse.Namespace) -> Dict[str, Any]:
    """更新写作进度（progress 子命令）。

    外部调用者通过此命令报告章节完成情况。

    Args:
        args: 命令行参数

    Returns:
        更新后的状态和下一步指令 JSON
    """
    project_root = Path(args.project_root).expanduser().resolve()
    state = load_state(project_root)

    if not state:
        return {
            "ok": False,
            "command": "progress",
            "error": "no_state",
            "message": "未找到写书状态，请先执行 run 子命令初始化。",
        }

    chapter = getattr(args, "chapter", None)
    chars_added = getattr(args, "chars_added", 0) or 0
    gate_passed = getattr(args, "gate_passed", False)

    # 更新章节进度
    if chapter is not None:
        if chapter == 0:
            # 特殊值：用于阶段切换
            if state["phase"] == "research":
                state["phase"] = "init"
            elif state["phase"] == "init":
                state["phase"] = "writing"
        else:
            state["current_chapter"] = chapter
            state["chapters_written"] = chapter
            state["chars_written"] = state.get("chars_written", 0) + chars_added

            if gate_passed:
                state["gate_passes"] = state.get("gate_passes", 0) + 1
            else:
                state["gate_failures"] = state.get("gate_failures", 0) + 1

            # 检查卷切换
            cpv = state.get("chapters_per_volume", 10)
            expected_volume = (chapter - 1) // cpv + 1
            if expected_volume > state.get("current_volume", 1):
                state["current_volume"] = expected_volume

            # 检查完成
            if chapter >= state.get("total_chapters", 0):
                state["phase"] = "complete"
                state["completed"] = True

    save_state(project_root, state)
    next_act = _next_action(state)

    return {
        "ok": True,
        "command": "progress",
        "project_root": str(project_root),
        "updated_fields": {
            "chapter": chapter,
            "chars_added": chars_added,
            "gate_passed": gate_passed,
        },
        "state_summary": {
            "phase": state.get("phase"),
            "current_chapter": state.get("current_chapter", 0),
            "chapters_written": state.get("chapters_written", 0),
            "chars_written": state.get("chars_written", 0),
            "current_volume": state.get("current_volume", 1),
            "gate_passes": state.get("gate_passes", 0),
            "gate_failures": state.get("gate_failures", 0),
            "completed": state.get("completed", False),
        },
        "next_action": next_act,
    }


def report(args: argparse.Namespace) -> Dict[str, Any]:
    """生成进度报告（report 子命令）。

    Args:
        args: 命令行参数

    Returns:
        报告内容 JSON
    """
    project_root = Path(args.project_root).expanduser().resolve()
    state = load_state(project_root)

    if not state:
        return {
            "ok": False,
            "command": "report",
            "error": "no_state",
            "message": "未找到写书状态，请先执行 run 子命令初始化。",
        }

    report_text = generate_progress_report(state)
    return {
        "ok": True,
        "command": "report",
        "project_root": str(project_root),
        "report": report_text,
        "state": state,
    }


# =============================================================================
# CLI 解析
# =============================================================================


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    p = argparse.ArgumentParser(
        description="一键写书调度器 - 全自动完成小说创作全流程",
        epilog="示例: auto_novel_writer.py plan --synopsis '穿越唐朝' --target-chars 50000 --genre 历史",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # plan 子命令
    p_plan = sub.add_parser("plan", help="生成执行计划（不实际执行）")
    p_plan.add_argument("--synopsis", required=True, help="小说简介/剧情种子")
    p_plan.add_argument(
        "--target-chars", type=int, default=100000, help="目标总字数（默认10万）"
    )
    p_plan.add_argument("--genre", default="待定", help="题材（如：历史、玄幻、都市）")
    p_plan.add_argument(
        "--research-depth",
        default="normal",
        choices=["light", "normal", "deep"],
        help="调研深度",
    )
    p_plan.add_argument(
        "--chars-per-chapter", type=int, default=3500, help="每章预估字数（默认3500）"
    )

    # run 子命令
    p_run = sub.add_parser("run", help="执行一键写书（支持断点续写）")
    p_run.add_argument("--project-root", required=True, help="项目根目录")
    p_run.add_argument("--synopsis", default="", help="小说简介/剧情种子")
    p_run.add_argument(
        "--target-chars", type=int, default=100000, help="目标总字数（默认10万）"
    )
    p_run.add_argument("--genre", default="待定", help="题材")
    p_run.add_argument(
        "--research-depth",
        default="normal",
        choices=["light", "normal", "deep"],
        help="调研深度",
    )

    # progress 子命令
    p_progress = sub.add_parser("progress", help="查看/更新进度")
    p_progress.add_argument("--project-root", required=True, help="项目根目录")
    p_progress.add_argument(
        "--chapter", type=int, default=None, help="当前完成章节号（0 表示阶段切换）"
    )
    p_progress.add_argument(
        "--chars-added", type=int, default=0, help="本章新增字数"
    )
    p_progress.add_argument(
        "--gate-passed",
        action="store_true",
        default=False,
        help="本章是否通过门禁",
    )

    # report 子命令
    p_report = sub.add_parser("report", help="生成进度报告")
    p_report.add_argument("--project-root", required=True, help="项目根目录")

    return p.parse_args()


# =============================================================================
# 入口
# =============================================================================


def main() -> int:
    """主入口函数。"""
    args = parse_args()
    cmd = args.cmd

    if cmd == "plan":
        payload = generate_plan(args)
    elif cmd == "run":
        payload = run_auto_write(args)
    elif cmd == "progress":
        payload = update_progress(args)
    elif cmd == "report":
        payload = report(args)
    else:
        payload = {"ok": False, "error": f"unknown_command: {cmd}"}

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
