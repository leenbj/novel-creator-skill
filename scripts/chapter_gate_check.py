#!/usr/bin/env python3
"""章节质量门禁校验器。

目标：把协议约束转为可执行硬检查，避免流程只停留在文档层。
"""

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple


def slugify(text: str) -> str:
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", text).strip("-")
    return s or "chapter"


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
