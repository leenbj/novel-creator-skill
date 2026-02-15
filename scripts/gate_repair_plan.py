#!/usr/bin/env python3
"""门禁失败修复计划生成器。

用途：读取 gate_result.json，输出最短修复步骤，供 /修复本章 使用。
"""

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List


def slugify(text: str) -> str:
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", text).strip("-")
    return s or "chapter"


def resolve_chapter(project_root: Path, chapter_file: str) -> Path:
    p = Path(chapter_file)
    if not p.is_absolute():
        p = project_root / p
    return p.resolve()


def map_failure_to_steps(failure: str) -> List[str]:
    f = failure.lower()

    if "chapter_storage_policy" in f:
        return [
            "将章节文件移动到 03_manuscript/ 目录，且扩展名为 .md。",
            "重新执行 /门禁检查。",
        ]

    if "knowledge_base_contains_chapter_files" in f:
        return [
            "将 02_knowledge_base/ 中误放的章节文件迁移到 03_manuscript/。",
            "重新执行 /门禁检查。",
        ]

    if f.startswith("memory_update"):
        return [
            "重新执行 /更新记忆，生成并补全 memory_update.md。",
            "继续执行 /检查一致性 -> /风格校准 -> /校稿 -> /门禁检查。",
        ]

    if f.startswith("consistency_report"):
        return [
            "重新执行 /检查一致性，修复冲突后更新 consistency_report.md。",
            "继续执行 /风格校准 -> /校稿 -> /门禁检查。",
        ]

    if f.startswith("style_calibration"):
        return [
            "重新执行 /风格校准，更新 style_calibration.md。",
            "继续执行 /校稿 -> /门禁检查。",
        ]

    if f.startswith("copyedit_report"):
        return [
            "重新执行 /校稿，生成 copyedit_report.md。",
            "继续执行 /门禁检查。",
        ]

    if f.startswith("publish_ready"):
        return [
            "重新执行 /校稿，生成 publish_ready.md 且确保为最终发布稿。",
            "检查 publish_ready.md 包含可发布关键词（可发布/通过/PASS）。",
            "继续执行 /门禁检查。",
        ]

    if "publish_ready_keyword" in f:
        return [
            "在 publish_ready.md 中补充发布判定关键词（可发布/通过/PASS）。",
            "重新执行 /门禁检查。",
        ]

    return [
        f"检查失败项：{failure}",
        "按失败项补齐对应产物后，重新执行 /门禁检查。",
    ]


def dedupe_steps(steps: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for s in steps:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="根据 gate_result.json 生成章节修复计划")
    p.add_argument("--project-root", required=True, help="小说项目根目录")
    p.add_argument("--chapter-file", required=True, help="章节文件路径（可相对 project-root）")
    p.add_argument("--chapter-id", help="章节标识，默认从章节文件名推导")
    p.add_argument("--emit-json", help="额外输出 JSON 文件路径")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    chapter_path = resolve_chapter(project_root, args.chapter_file)
    chapter_id = slugify(args.chapter_id or chapter_path.stem)

    gate_dir = project_root / "04_editing" / "gate_artifacts" / chapter_id
    gate_file = gate_dir / "gate_result.json"

    result: Dict[str, object] = {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_root": str(project_root),
        "chapter_file": str(chapter_path),
        "chapter_id": chapter_id,
        "gate_result_file": str(gate_file),
        "can_publish": False,
        "failures": [],
        "repair_steps": [],
    }

    if not gate_file.exists():
        result["repair_steps"] = [
            "未找到 gate_result.json，请先执行 /门禁检查。",
            "若仍无结果，请检查章节路径与 chapter_id 是否一致。",
        ]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    gate = json.loads(gate_file.read_text(encoding="utf-8"))
    failures = gate.get("failures", []) if isinstance(gate, dict) else []
    passed = bool(gate.get("passed")) if isinstance(gate, dict) else False

    result["can_publish"] = passed
    result["failures"] = failures

    if passed:
        result["repair_steps"] = [
            "当前章节已通过门禁，无需修复。",
            "可继续 /更新剧情索引 或进入下一章写作。",
        ]
    else:
        steps: List[str] = []
        for f in failures:
            steps.extend(map_failure_to_steps(str(f)))
        steps.append("修复完成后再执行 /更新剧情索引。")
        result["repair_steps"] = dedupe_steps(steps)

    md_path = gate_dir / "repair_plan.md"
    lines = []
    lines.append("# 章节修复计划")
    lines.append("")
    lines.append(f"- 生成时间：{result['generated_at']}")
    lines.append(f"- 章节：{chapter_path}")
    lines.append(f"- 门禁结果：{'通过' if result['can_publish'] else '未通过'}")
    lines.append("")
    if failures:
        lines.append("## 失败项")
        for i, f in enumerate(failures, 1):
            lines.append(f"{i}. {f}")
        lines.append("")
    lines.append("## 修复步骤（最短路径）")
    for i, s in enumerate(result["repair_steps"], 1):
        lines.append(f"{i}. {s}")
    lines.append("")
    lines.append("## 建议命令")
    lines.append("```bash")
    lines.append(f"python3 scripts/gate_repair_plan.py --project-root {project_root} --chapter-file '{chapter_path}'")
    lines.append(f"python3 scripts/chapter_gate_check.py --project-root {project_root} --chapter-file '{chapter_path}'")
    lines.append("```")
    md_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    if args.emit_json:
        jp = Path(args.emit_json).expanduser().resolve()
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "repair_plan": str(md_path),
                "result": result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
