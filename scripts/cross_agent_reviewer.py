#!/usr/bin/env python3
"""跨 Agent 双智能体审核编排器。

引入独立外部 Agent 作为审稿官，避免"自己写自己审"的盲区。
通过不同 AI 工具的交叉审核提升质量把关可靠性。

子命令：
1. review     — 生成单章审核任务（含审核官人设和三维度报告模板）
2. batch-review — 生成批处理审核任务（每 10 章）
3. record     — 记录审核结果并判定是否需要重审
4. unresolved — 查看未解决问题
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

REVIEWER_PERSONA = (
    "你是一位拥有十年网文阅读经验、对设定极其敏感的资深编辑。"
    "你的唯一任务就是找茬。你绝不会说'写得不错'——你只关注问题。\n"
    "你对以下问题零容忍：\n"
    "- 时间线错乱和空间瞬移\n"
    "- 设定吃书（前后矛盾）\n"
    "- 历史/专业常识错误\n"
    "- 节奏拖沓或爽点缺失\n"
    "- AI味过重（翻译腔、过度总结、缺乏人物性格差异的对话）"
)

REVIEW_TEMPLATE = """## 审核报告

### 维度一：逻辑与连续性硬伤
| 章节 | 位置 | 问题描述 | 严重等级 |
|------|------|---------|---------|
| | | | P0/P1/P2 |

### 维度二：阅读体验与节奏把控
- 爽点密度：
- 水字数段落：
- 情绪曲线：
- 章末钩子质量：

### 维度三：文笔去AI化
- 翻译腔检测：
- 过度总结：
- 对话同质化：
- 描写空洞：
- 情感直白：

### 总结
- P0 问题数：
- P1 问题数：
- P2 问题数：
- 判定：通过 / 有条件通过 / 需重写
"""

AGENT_ROUTES = {
    "claude-code": "codex",
    "codex": "claude-code",
    "opencode": "claude-code",
    "gemini": "claude-code",
}

# -- 配置 ------------------------------------------------------------------

@dataclass
class ReviewConfig:
    review_rel_dir: str = "04_editing/cross_reviews"
    unresolved_rel_path: str = "04_editing/unresolved_issues.json"
    max_rounds: int = 3
    conditional_pass_limit: int = 3  # 连续N章有条件通过则暂停
    batch_interval: int = 10
    default_indent: int = 2


# -- 内部工具 ---------------------------------------------------------------

def _review_dir(root: Path, cfg: ReviewConfig) -> Path:
    return root / cfg.review_rel_dir


def _chapter_review_path(
    root: Path, chapter: int, round_no: int, cfg: ReviewConfig,
) -> Path:
    return _review_dir(root, cfg) / f"ch{chapter:04d}_round{round_no}.json"


def _unresolved_path(root: Path, cfg: ReviewConfig) -> Path:
    return root / cfg.unresolved_rel_path


def _load_unresolved(root: Path, cfg: ReviewConfig) -> Dict[str, Any]:
    return load_json(
        _unresolved_path(root, cfg),
        default={"issues": [], "conditional_passes": []},
    )


def _save_unresolved(root: Path, data: Dict[str, Any], cfg: ReviewConfig) -> bool:
    return save_json(_unresolved_path(root, cfg), data, indent=cfg.default_indent)


def _get_review_history(
    root: Path, chapter: int, cfg: ReviewConfig,
) -> List[Dict[str, Any]]:
    """获取某章的全部审核历史。"""
    history: List[Dict[str, Any]] = []
    for r in range(1, cfg.max_rounds + 1):
        path = _chapter_review_path(root, chapter, r, cfg)
        if path.exists():
            history.append(load_json(path, default={}))
    return history


def _select_reviewer(writer_tool: str) -> str:
    """根据写作工具选择审核工具。"""
    return AGENT_ROUTES.get(writer_tool.lower(), "codex")


def _build_review_prompt(
    chapter_text: str,
    chapter: int,
    previous_issues: List[str],
) -> str:
    """构建发送给审核 Agent 的完整 prompt。"""
    lines = [
        "# 章节审核任务",
        "",
        f"## 审核官人设",
        REVIEWER_PERSONA,
        "",
        f"## 待审内容：第 {chapter} 章",
        "",
        chapter_text[:8000],  # 截断防止 prompt 过长
        "",
    ]

    if previous_issues:
        lines.append("## 上一轮未解决的问题")
        for issue in previous_issues:
            lines.append(f"- {issue}")
        lines.append("")
        lines.append("请重点检查上述问题是否已修复。")
        lines.append("")

    lines.extend([
        "## 输出格式要求",
        "请严格按以下三维度输出结构化报告：",
        REVIEW_TEMPLATE,
    ])

    return "\n".join(lines)


# -- 子命令 -----------------------------------------------------------------

def cmd_review(args: argparse.Namespace, cfg: ReviewConfig) -> Dict[str, Any]:
    """生成单章审核任务。

    不直接调用外部 Agent（那是 AI 编排层的职责），
    而是生成审核 prompt 和元数据，供上层流程调度。
    """
    root = Path(args.project_root).expanduser().resolve()
    chapter = args.chapter

    chapter_path = Path(args.chapter_file)
    if not chapter_path.is_absolute():
        chapter_path = root / chapter_path

    if not chapter_path.exists():
        return {
            "ok": False, "command": "review",
            "error": f"章节文件不存在: {chapter_path}",
        }

    chapter_text = read_text(chapter_path)
    history = _get_review_history(root, chapter, cfg)
    current_round = len(history) + 1

    if current_round > cfg.max_rounds:
        return {
            "ok": False, "command": "review",
            "error": f"已达最大审核轮次 {cfg.max_rounds}，请使用 record --force-pass 强制通过",
            "chapter": chapter,
            "rounds_completed": len(history),
        }

    # 收集上轮未解决问题
    previous_issues: List[str] = []
    if history:
        last = history[-1]
        previous_issues = last.get("unresolved_issues", [])

    # 收敛判定：第2轮和第3轮 P0 问题相同则停机
    if current_round >= 3 and len(history) >= 2:
        r2_p0 = set(history[-2].get("p0_issues", []))
        r1_p0 = set(history[-1].get("p0_issues", []))
        if r2_p0 and r2_p0 == r1_p0:
            return {
                "ok": False, "command": "review",
                "error": "收敛判定：连续两轮 P0 问题相同，无法修复。建议人工介入。",
                "chapter": chapter,
                "stuck_p0": list(r2_p0),
            }

    reviewer = _select_reviewer(args.writer_tool)
    prompt = _build_review_prompt(chapter_text, chapter, previous_issues)

    # 保存审核任务
    task = {
        "chapter": chapter,
        "round": current_round,
        "reviewer_tool": reviewer,
        "writer_tool": args.writer_tool,
        "chapter_file": str(chapter_path),
        "previous_issues": previous_issues,
        "created_at": dt.datetime.now().isoformat(),
        "status": "pending",
    }

    task_path = _review_dir(root, cfg) / f"ch{chapter:04d}_round{current_round}_task.json"
    ensure_dir(task_path.parent)
    save_json(task_path, task, indent=cfg.default_indent)

    # 保存 prompt
    prompt_path = _review_dir(root, cfg) / f"ch{chapter:04d}_round{current_round}_prompt.md"
    write_text(prompt_path, prompt)

    return {
        "ok": True, "command": "review",
        "task_file": str(task_path),
        "prompt_file": str(prompt_path),
        "chapter": chapter,
        "round": current_round,
        "reviewer_tool": reviewer,
        "previous_issues_count": len(previous_issues),
        "message": f"审核任务已生成（第 {current_round} 轮）。"
                   f"请将 prompt 文件发送给 {reviewer} 执行审核。",
    }


def cmd_batch_review(args: argparse.Namespace, cfg: ReviewConfig) -> Dict[str, Any]:
    """生成批处理审核任务。"""
    root = Path(args.project_root).expanduser().resolve()
    start, end = args.chapter_start, args.chapter_end

    manuscript_dir = root / "03_manuscript"
    chapters_found: List[Dict[str, Any]] = []

    for ch in range(start, end + 1):
        # 尝试多种文件名格式
        candidates = list(manuscript_dir.glob(f"第{ch}章*.md"))
        if candidates:
            chapters_found.append({
                "chapter": ch,
                "file": str(candidates[0]),
            })

    if not chapters_found:
        return {
            "ok": False, "command": "batch-review",
            "error": f"未找到第 {start}-{end} 章的任何章节文件",
        }

    reviewer = _select_reviewer(args.writer_tool)

    # 构建批处理 prompt
    lines = [
        "# 批处理审核任务",
        "",
        f"## 审核官人设",
        REVIEWER_PERSONA,
        "",
        f"## 审核范围：第 {start}-{end} 章（共 {len(chapters_found)} 章）",
        "",
        "### 批处理额外检查项",
        f"- {end - start + 1} 章跨度内的节奏曲线是否合理",
        "- 支线推进是否均衡",
        "- 伏笔密度是否合理（是否有积压或遗忘）",
        "- 角色出场频率是否符合其重要性",
        "",
        "### 各章摘要",
        "",
    ]

    for ch_info in chapters_found:
        text = read_text(Path(ch_info["file"]))
        preview = text[:300].replace("\n", " ")
        lines.append(f"**第 {ch_info['chapter']} 章**: {preview}...")
        lines.append("")

    lines.extend([
        "## 输出格式",
        "请按三维度输出结构化报告，并额外包含跨章节分析。",
        REVIEW_TEMPLATE,
    ])

    prompt = "\n".join(lines)

    # 保存批处理任务
    task_path = _review_dir(root, cfg) / f"batch_ch{start:04d}-{end:04d}_task.json"
    prompt_path = _review_dir(root, cfg) / f"batch_ch{start:04d}-{end:04d}_prompt.md"
    ensure_dir(task_path.parent)

    task = {
        "type": "batch",
        "chapter_range": [start, end],
        "chapters_found": len(chapters_found),
        "reviewer_tool": reviewer,
        "created_at": dt.datetime.now().isoformat(),
        "status": "pending",
    }
    save_json(task_path, task, indent=cfg.default_indent)
    write_text(prompt_path, prompt)

    return {
        "ok": True, "command": "batch-review",
        "task_file": str(task_path),
        "prompt_file": str(prompt_path),
        "chapter_range": [start, end],
        "chapters_found": len(chapters_found),
        "reviewer_tool": reviewer,
        "message": f"批处理审核任务已生成。请将 prompt 发送给 {reviewer}。",
    }


def cmd_record(args: argparse.Namespace, cfg: ReviewConfig) -> Dict[str, Any]:
    """记录审核结果，判定是否需要重审。"""
    root = Path(args.project_root).expanduser().resolve()
    chapter = args.chapter
    round_no = args.round

    result = {
        "chapter": chapter,
        "round": round_no,
        "p0_issues": [s.strip() for s in (args.p0 or "").split("|") if s.strip()],
        "p1_issues": [s.strip() for s in (args.p1 or "").split("|") if s.strip()],
        "p2_issues": [s.strip() for s in (args.p2 or "").split("|") if s.strip()],
        "verdict": args.verdict,  # passed / conditional / rewrite
        "recorded_at": dt.datetime.now().isoformat(),
    }

    all_issues = result["p0_issues"] + result["p1_issues"]
    result["unresolved_issues"] = all_issues

    # 保存本轮结果
    path = _chapter_review_path(root, chapter, round_no, cfg)
    ensure_dir(path.parent)
    save_json(path, result, indent=cfg.default_indent)

    # 判定后续动作
    action = "continue"
    if result["p0_issues"] and not args.force_pass:
        if round_no >= cfg.max_rounds:
            action = "halt_max_rounds"
            # 记录到未解决问题
            unresolved = _load_unresolved(root, cfg)
            unresolved["issues"].append({
                "chapter": chapter,
                "p0_issues": result["p0_issues"],
                "rounds": round_no,
                "recorded_at": result["recorded_at"],
            })
            unresolved["conditional_passes"].append(chapter)
            _save_unresolved(root, unresolved, cfg)

            # 连续有条件通过检查
            cp = unresolved["conditional_passes"]
            recent = cp[-cfg.conditional_pass_limit:]
            if (len(recent) >= cfg.conditional_pass_limit
                    and all(recent[i] + 1 == recent[i + 1] for i in range(len(recent) - 1))):
                action = "halt_consecutive"
        else:
            action = "rewrite_needed"
    elif args.verdict == "conditional":
        action = "conditional_pass"
        unresolved = _load_unresolved(root, cfg)
        unresolved["conditional_passes"].append(chapter)
        _save_unresolved(root, unresolved, cfg)

    return {
        "ok": True, "command": "record",
        "chapter": chapter,
        "round": round_no,
        "verdict": args.verdict,
        "p0_count": len(result["p0_issues"]),
        "p1_count": len(result["p1_issues"]),
        "p2_count": len(result["p2_issues"]),
        "action": action,
        "message": {
            "continue": "审核通过，可继续下一章",
            "rewrite_needed": f"存在 P0 问题，需重写后进入第 {round_no + 1} 轮审核",
            "conditional_pass": "有条件通过，问题已记录到 unresolved_issues",
            "halt_max_rounds": f"已达最大审核轮次 {cfg.max_rounds}，标记为有条件通过",
            "halt_consecutive": f"连续 {cfg.conditional_pass_limit} 章有条件通过，强制暂停请求人工介入",
        }.get(action, action),
    }


def cmd_unresolved(args: argparse.Namespace, cfg: ReviewConfig) -> Dict[str, Any]:
    """查看未解决问题。"""
    root = Path(args.project_root).expanduser().resolve()
    data = _load_unresolved(root, cfg)

    issues = data.get("issues", [])
    cp = data.get("conditional_passes", [])

    return {
        "ok": True, "command": "unresolved",
        "total_issues": len(issues),
        "conditional_pass_chapters": cp,
        "issues": issues,
    }


# -- CLI -------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="跨 Agent 审核编排器")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("review", help="生成单章审核任务")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", type=int, required=True)
    s.add_argument("--chapter-file", required=True, help="章节文件路径")
    s.add_argument("--writer-tool", default="claude-code", help="写作工具名称")

    s = sub.add_parser("batch-review", help="生成批处理审核任务")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter-start", type=int, required=True)
    s.add_argument("--chapter-end", type=int, required=True)
    s.add_argument("--writer-tool", default="claude-code")

    s = sub.add_parser("record", help="记录审核结果")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", type=int, required=True)
    s.add_argument("--round", type=int, required=True)
    s.add_argument("--verdict", required=True, choices=["passed", "conditional", "rewrite"])
    s.add_argument("--p0", default="", help="P0 问题，用 | 分隔")
    s.add_argument("--p1", default="", help="P1 问题，用 | 分隔")
    s.add_argument("--p2", default="", help="P2 问题，用 | 分隔")
    s.add_argument("--force-pass", action="store_true", help="强制通过（忽略 P0）")

    s = sub.add_parser("unresolved", help="查看未解决问题")
    s.add_argument("--project-root", required=True)

    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = ReviewConfig()

    dispatch = {
        "review": cmd_review,
        "batch-review": cmd_batch_review,
        "record": cmd_record,
        "unresolved": cmd_unresolved,
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
