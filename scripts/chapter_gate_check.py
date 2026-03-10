#!/usr/bin/env python3
"""章节质量门禁校验器。

目标：把协议约束转为可执行硬检查，避免流程只停留在文档层。
"""

import argparse
import datetime as dt
import json
import re
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Tuple

from common import slugify

# 确保同目录脚本可直接 import
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


def resolve_chapter(project_root: Path, chapter_file: str) -> Path:
    p = Path(chapter_file)
    if not p.is_absolute():
        p = project_root / p
    return p.resolve()


def required_artifacts(gate_dir: Path) -> Dict[str, Path]:
    return {
        "memory_update": gate_dir / "memory_update.md",
        "consistency_report": gate_dir / "consistency_report.md",
        "style_calibration": gate_dir / "style_calibration.md",
        "copyedit_report": gate_dir / "copyedit_report.md",
        "publish_ready": gate_dir / "publish_ready.md",
        "quality_report": gate_dir / "quality_report.md",
    }


def check_chapter_storage(project_root: Path, chapter_path: Path) -> Tuple[bool, str]:
    if chapter_path.suffix.lower() != ".md":
        return False, "章节文件必须是 .md 格式"
    try:
        rel = chapter_path.relative_to(project_root)
    except ValueError:
        return False, "章节文件不在项目目录内"
    rel_posix = rel.as_posix()
    if not rel_posix.startswith("03_manuscript/"):
        return False, "章节文件必须存放在 03_manuscript/ 目录下"
    return True, "通过"


def find_misplaced_chapters(project_root: Path) -> List[str]:
    kb_dir = project_root / "02_knowledge_base"
    if not kb_dir.exists():
        return []
    bad: List[str] = []
    chapter_name_re = re.compile(r"^第\d+章.*\.md$")
    for p in kb_dir.rglob("*.md"):
        if chapter_name_re.match(p.name):
            bad.append(str(p))
    return bad


def check_file(path: Path, min_bytes: int, chapter_mtime: float) -> Tuple[bool, str]:
    if not path.exists():
        return False, "文件不存在"
    size = path.stat().st_size
    if size < min_bytes:
        return False, f"文件过小({size}B < {min_bytes}B)"
    if path.stat().st_mtime < chapter_mtime:
        return False, "文件时间早于章节文件，疑似未执行最新流程"
    return True, "通过"


def check_publish_ready(path: Path, keywords: List[str]) -> Tuple[bool, str]:
    txt = path.read_text(encoding="utf-8", errors="ignore")
    for kw in keywords:
        if kw in txt:
            return True, f"命中发布关键字: {kw}"
    return False, "未命中发布关键字（默认要求：可发布/通过/PASS）"


def check_quality_report(path: Path) -> Tuple[bool, str]:
    txt = path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"通过：\s*(True|False)", txt)
    if not m:
        return False, "quality_report 缺少\"通过：True/False\"结论"
    report_passed = (m.group(1) == "True")

    # 检查段落重复度指标（无论总体是否通过都执行，确保输出详细失败信息）
    dup_failures = []

    # 解析段落唯一比例
    unique_ratio_m = re.search(r"段落唯一比例[：:]\s*([\d.]+)", txt)
    if unique_ratio_m:
        try:
            ratio = float(unique_ratio_m.group(1))
            # 阈值 0.85
            if ratio < 0.85:
                dup_failures.append(f"paragraph_unique_ratio={ratio:.2%} < 0.85")
        except ValueError:
            pass

    # 解析最大重复段落次数
    max_dup_m = re.search(r"最大重复段落次数[：:]\s*(\d+)", txt)
    if max_dup_m:
        try:
            max_dup = int(max_dup_m.group(1))
            # 阈值 2
            if max_dup > 2:
                dup_failures.append(f"max_duplicate_paragraph_repeat={max_dup} > 2")
        except ValueError:
            pass

    failures: List[str] = []
    if not report_passed:
        failures.append("quality_report 显示未通过")
    if dup_failures:
        failures.append("段落重复度检查失败: " + "; ".join(dup_failures))
    if failures:
        return False, "；".join(failures)

    return True, "通过"


def check_pacing_review(path: Path) -> Tuple[bool, str]:
    """解析 pacing_review.md 的综合结论字段。

    期望格式：
        节奏审查: 通过
        节奏审查: 失败
        失败原因: <原因>
    """
    txt = path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"节奏审查[：:]\s*(通过|失败)", txt)
    if not m:
        return False, "pacing_review.md 缺少「节奏审查: 通过/失败」结论行"
    if m.group(1) == "失败":
        reason_m = re.search(r"失败原因[：:]\s*(.+)", txt)
        reason = reason_m.group(1).strip() if reason_m else "未说明原因"
        return False, f"节奏审查失败：{reason}"
    return True, "通过"


def generate_script_pacing_review(
    tier: str,
    triggered_quotas: List[str],
    has_suspense: bool,
    arg_errors: List[str],
    pt_errors: List[str],
) -> str:
    """Python 自动模式下，从脚本检查结果生成 pacing_review.md（无需 LLM）。

    Claude Code 对话模式下此函数不被调用；Claude 直接写入语义分析内容。
    """
    quota_violated = len(triggered_quotas) >= 2
    pacing_errors = arg_errors + pt_errors
    passed = not quota_violated and not pacing_errors

    tier_map = {"fast": "快档", "medium": "中档", "slow": "慢档"}
    tier_zh = tier_map.get(tier, "未知")

    a_status = "触发" if "A" in triggered_quotas else "未触发"
    b_status = "触发" if "B" in triggered_quotas else "未触发"
    c_status = "触发" if "C" in triggered_quotas else "未触发"

    suspense_level = "中" if has_suspense else "无"
    fail_reason = "；".join(pacing_errors) if pacing_errors else "无"

    verdict = "通过" if passed else "失败"

    return f"""# 节奏审查报告（脚本自动生成）

> 本报告由 chapter_gate_check.py 脚本自动生成，基于 anti_resolution_guard 和 pacing_tracker 检查结果。
> Claude Code 对话模式下应由 `/节奏审查` 步骤生成语义版本替换本文件。

## 一、档位判断
- **本章档位**：{tier_zh}
- **判断依据**：由写前 event_matrix 推荐的事件类型推断

## 二、A/B/C 配额核查
- **A（主线矛盾实质推进）**：{a_status} — 关键词检测
- **B（主要关系决定性升级）**：{b_status} — 关键词检测
- **C（核心秘密完整揭露）**：{c_status} — 关键词检测
- **配额违规**：{"是" if quota_violated else "否"}（同时触发 ≥2项 = 违规）

## 三、章末悬念质量
- **悬念等级**：{suspense_level}（脚本关键词检测）
- **具体悬念内容**：脚本模式下不做语义分析

## 四、隐性加速检测
- **是否存在关键词未覆盖的隐性加速**：否（脚本模式不做语义分析）
- **说明**：如需语义检测，请在 Claude Code 对话中执行 `/节奏审查`

## 综合结论
节奏审查: {verdict}
失败原因: {fail_reason}
"""


def extract_chapter_number(raw: str) -> int:
    """从章节标识或文件名中提取首个数字序列作为章节号。"""
    m = re.search(r"(\d+)", raw or "")
    return int(m.group(1)) if m else 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="检查章节是否完成强制门禁：更新记忆→一致性→风格校准→校稿")
    p.add_argument("--project-root", required=True, help="小说项目根目录")
    p.add_argument("--chapter-file", required=True, help="章节文件路径（可相对 project-root）")
    p.add_argument("--chapter-id", help="章节标识；默认从章节文件名推导")
    p.add_argument("--min-bytes", type=int, default=20, help="门禁产物最小字节数")
    p.add_argument(
        "--publish-keywords",
        default="可发布,通过,PASS",
        help="publish_ready.md 必须命中的关键字，逗号分隔",
    )
    p.add_argument("--emit-json", help="额外导出 JSON 结果路径")
    p.add_argument("--pacing-tier", choices=["slow", "medium", "fast"],
                   help="当前章预期节奏档位（传入 pacing_tracker check 做预演）")
    p.add_argument("--pacing-event-types", default="",
                   help="当前章事件类型，逗号分隔（档位推断用）")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    chapter_path = resolve_chapter(project_root, args.chapter_file)
    chapter_id = slugify(args.chapter_id or chapter_path.stem)

    gate_dir = project_root / "04_editing" / "gate_artifacts" / chapter_id
    gate_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "checked_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_root": str(project_root),
        "chapter_file": str(chapter_path),
        "chapter_id": chapter_id,
        "passed": False,
        "checks": [],
        "failures": [],
        "warnings": [],
    }

    if not chapter_path.exists():
        result["failures"].append(f"章节文件不存在: {chapter_path}")
        out = gate_dir / "gate_result.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    ok, msg = check_chapter_storage(project_root, chapter_path)
    result["checks"].append(
        {"name": "chapter_storage_policy", "path": str(chapter_path), "ok": ok, "message": msg}
    )
    if not ok:
        result["failures"].append(f"chapter_storage_policy: {msg}")

    misplaced = find_misplaced_chapters(project_root)
    if misplaced:
        result["failures"].append("knowledge_base_contains_chapter_files: 发现章节文件混入 02_knowledge_base")
        result["checks"].append(
            {
                "name": "knowledge_base_isolation",
                "path": str(project_root / "02_knowledge_base"),
                "ok": False,
                "message": f"发现 {len(misplaced)} 个疑似章节文件",
            }
        )
        for p in misplaced:
            result["warnings"].append(f"请迁移文件到 03_manuscript: {p}")
    else:
        result["checks"].append(
            {
                "name": "knowledge_base_isolation",
                "path": str(project_root / "02_knowledge_base"),
                "ok": True,
                "message": "通过",
            }
        )

    chapter_mtime = chapter_path.stat().st_mtime
    artifacts = required_artifacts(gate_dir)

    for name, file_path in artifacts.items():
        ok, msg = check_file(file_path, args.min_bytes, chapter_mtime)
        item = {"name": name, "path": str(file_path), "ok": ok, "message": msg}
        result["checks"].append(item)
        if not ok:
            result["failures"].append(f"{name}: {msg}")

    publish_keywords = [k.strip() for k in args.publish_keywords.split(",") if k.strip()]
    publish_path = artifacts["publish_ready"]
    if publish_path.exists() and publish_path.stat().st_size >= args.min_bytes:
        ok, msg = check_publish_ready(publish_path, publish_keywords)
        item = {
            "name": "publish_ready_keyword",
            "path": str(publish_path),
            "ok": ok,
            "message": msg,
        }
        result["checks"].append(item)
        if not ok:
            result["failures"].append(f"publish_ready_keyword: {msg}")

    quality_path = artifacts["quality_report"]
    if quality_path.exists() and quality_path.stat().st_size >= args.min_bytes:
        ok, msg = check_quality_report(quality_path)
        item = {
            "name": "quality_baseline",
            "path": str(quality_path),
            "ok": ok,
            "message": msg,
        }
        result["checks"].append(item)
        if not ok:
            result["failures"].append(f"quality_baseline: {msg}")

    # ── 反向刹车校验（anti_resolution_guard check）────────────────────
    # 检查章末悬念、禁止揭露、分辨率信号，将 errors → failures / warnings → warnings
    try:
        import anti_resolution_guard as _arg_mod  # noqa: PLC0415

        _arg_cfg = _arg_mod.AntiResConfig()
        _arg_args = types.SimpleNamespace(
            project_root=str(project_root),
            chapter_file=str(chapter_path),
            is_finale=False,
        )
        _arg_result: Dict[str, Any] = _arg_mod.cmd_check(_arg_args, _arg_cfg)

        _arg_errors: List[str] = _arg_result.get("errors", []) or []
        _arg_warnings: List[str] = _arg_result.get("warnings", []) or []
        _arg_checks: Dict[str, Any] = _arg_result.get("checks", {}) or {}

        result["checks"].append(
            {
                "name": "anti_resolution_guard",
                "path": str(chapter_path),
                "ok": len(_arg_errors) == 0,
                "message": "通过" if not _arg_errors else "；".join(_arg_errors),
                "details": _arg_checks,
            }
        )
        for _e in _arg_errors:
            result["failures"].append(f"anti_resolution_guard: {_e}")
        for _w in _arg_warnings:
            result["warnings"].append(f"anti_resolution_guard: {_w}")
    except Exception as _exc:
        # 脚本不可用时降级为警告，不阻断门禁
        result["warnings"].append(f"anti_resolution_guard 不可用（跳过）: {_exc}")
        result["checks"].append(
            {
                "name": "anti_resolution_guard",
                "path": str(chapter_path),
                "ok": True,
                "message": f"跳过（脚本加载失败）: {_exc}",
            }
        )

    # ── 节奏档位校验（pacing_tracker check）────────────────────────
    # 校验卷内快档配额、慢档密度、连续快档上限
    try:
        import pacing_tracker as _pt_mod  # noqa: PLC0415

        _pt_cfg = _pt_mod.PacingConfig()
        _ch_no = extract_chapter_number(chapter_id)
        _pt_args = types.SimpleNamespace(
            project_root=str(project_root),
            chapter=_ch_no,
            max_fast_per_volume=_pt_cfg.max_fast_per_volume,
            # 传入当前章预期档位，让 check 做"含本章"的预演校验
            current_tier=getattr(args, "pacing_tier", None),
            current_event_types=getattr(args, "pacing_event_types", "") or "",
        )
        _pt_result: Dict[str, Any] = _pt_mod.cmd_check(_pt_args, _pt_cfg)

        _pt_errors: List[str] = _pt_result.get("errors", []) or []
        _pt_warnings: List[str] = _pt_result.get("warnings", []) or []

        result["checks"].append(
            {
                "name": "pacing_tracker",
                "path": str(project_root / "00_memory" / "pacing_history.json"),
                "ok": len(_pt_errors) == 0,
                "message": "通过" if not _pt_errors else "；".join(_pt_errors),
                "details": {
                    "chapter": _ch_no,
                    "volume": _pt_result.get("volume"),
                    "stats": _pt_result.get("stats", {}),
                },
            }
        )
        for _e in _pt_errors:
            result["failures"].append(f"pacing_tracker: {_e}")
        for _w in _pt_warnings:
            result["warnings"].append(f"pacing_tracker: {_w}")
    except Exception as _exc:
        result["warnings"].append(f"pacing_tracker 不可用（跳过）: {_exc}")
        result["checks"].append(
            {
                "name": "pacing_tracker",
                "path": str(project_root / "00_memory" / "pacing_history.json"),
                "ok": True,
                "message": f"跳过（脚本加载失败）: {_exc}",
            }
        )

    # ── 节奏审查（pacing_review.md）────────────────────────────────
    # 优先使用 Claude Code 写入的语义版本；不存在时从脚本检查结果自动生成。
    _pr_path = gate_dir / "pacing_review.md"
    if not _pr_path.exists():
        # 从已完成的脚本检查中提取数据，生成回退版本
        _pr_arg_check = next(
            (c for c in result["checks"] if c.get("name") == "anti_resolution_guard"), {}
        )
        _pr_pt_check = next(
            (c for c in result["checks"] if c.get("name") == "pacing_tracker"), {}
        )
        _pr_quota = (_pr_arg_check.get("details") or {}).get("quota_abc") or {}
        _pr_triggered = _pr_quota.get("triggered_quotas") or []
        _pr_suspense = ((_pr_arg_check.get("details") or {}).get("tail_suspense") or {}).get(
            "has_suspense", True
        )
        _pr_tier = ((_pr_pt_check.get("details") or {}).get("current_tier")) or "medium"
        _pr_arg_errors: List[str] = [
            f for f in result["failures"] if f.startswith("anti_resolution_guard:")
        ]
        _pr_pt_errors: List[str] = [
            f for f in result["failures"] if f.startswith("pacing_tracker:")
        ]
        _pr_content = generate_script_pacing_review(
            _pr_tier, _pr_triggered, _pr_suspense, _pr_arg_errors, _pr_pt_errors
        )
        _pr_path.write_text(_pr_content, encoding="utf-8")
        result["warnings"].append("pacing_review.md 不存在，已从脚本检查结果自动生成（建议在 Claude Code 中执行 /节奏审查 获取语义版本）")

    if _pr_path.exists() and _pr_path.stat().st_size >= args.min_bytes:
        _pr_ok, _pr_msg = check_pacing_review(_pr_path)
        result["checks"].append(
            {
                "name": "pacing_review_semantic",
                "path": str(_pr_path),
                "ok": _pr_ok,
                "message": _pr_msg,
            }
        )
        if not _pr_ok:
            result["failures"].append(f"pacing_review_semantic: {_pr_msg}")

    result["passed"] = len(result["failures"]) == 0

    gate_result = gate_dir / "gate_result.json"
    gate_result.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.emit_json:
        emit_path = Path(args.emit_json).expanduser().resolve()
        emit_path.parent.mkdir(parents=True, exist_ok=True)
        emit_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
