#!/usr/bin/env python3
"""小说流程真实执行器。

目标：把 /一键开书 与 /继续写 从“流程描述”变为可执行脚本。
"""

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
TEMPLATE_DIR = SKILL_ROOT / "templates"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def run_python(script: Path, args: List[str]) -> Tuple[int, str, str, Optional[Dict[str, object]]]:
    cmd = [sys.executable, str(script), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = proc.stdout.strip()
    err = proc.stderr.strip()
    payload = None
    if out:
        try:
            payload = json.loads(out)
        except Exception:
            payload = None
    return proc.returncode, out, err, payload


def template(name: str, mapping: Dict[str, str]) -> str:
    p = TEMPLATE_DIR / name
    txt = read_text(p)
    for k, v in mapping.items():
        txt = txt.replace("{" + k + "}", v)
    return txt


def chapter_no_from_name(name: str) -> int:
    m = re.search(r"第(\d+)章", name)
    return int(m.group(1)) if m else 0


def latest_chapter(manuscript_dir: Path) -> Optional[Path]:
    files = sorted(manuscript_dir.glob("*.md"), key=lambda p: (chapter_no_from_name(p.name), p.name))
    return files[-1] if files else None


def next_chapter_filename(manuscript_dir: Path, title: str = "待写") -> str:
    cur = latest_chapter(manuscript_dir)
    next_no = chapter_no_from_name(cur.name) + 1 if cur else 1
    return f"第{next_no}章-{title}.md"


def slugify(text: str) -> str:
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", text).strip("-")
    return s or "chapter"


def write_if_needed(path: Path, content: str, overwrite: bool, changed: List[str], skipped: List[str]) -> None:
    if path.exists() and not overwrite:
        skipped.append(str(path))
        return
    write_text(path, content)
    changed.append(str(path))


def project_structure(project_root: Path) -> None:
    dirs = [
        "00_memory",
        "00_memory/chapter_summaries",
        "00_memory/chapter_summaries/archive",
        "00_memory/retrieval",
        "00_memory/style_profiles",
        "01_analysis",
        "02_knowledge_base",
        "03_manuscript",
        "04_editing/gate_artifacts",
        "05_assets",
    ]
    for d in dirs:
        ensure_dir(project_root / d)


def init_project_files(project_root: Path, args: argparse.Namespace, overwrite: bool) -> Dict[str, List[str]]:
    changed: List[str] = []
    skipped: List[str] = []
    now = dt.datetime.now().strftime("%Y-%m-%d")

    mapping = {
        "TITLE": args.title,
        "GENRE": args.genre,
        "CORE_HOOK": args.core_hook,
        "TARGET_WORDS": str(args.target_words),
        "ENDING": args.ending,
        "VOL1_NAME": "起势卷",
        "VOL1_EVENT": args.core_conflict,
        "VOL1_END": "120",
        "ACT1_GOAL": "建立主角目标与初始矛盾",
        "ACT2_CONFLICT": "冲突升级并引入多线压力",
        "ACT3_CLIMAX": "卷末反转并埋下跨卷悬念",
        "VOL2_NAME": "扩张卷",
        "VOL2_EVENT": "主线升级",
        "VOL2_START": "121",
        "VOL2_END": "240",
        "PROTAGONIST": args.protagonist,
        "START_STATE": "普通起点",
        "MID_TRANSFORM": "价值观重塑",
        "FINAL_STATE": "完成角色弧线",
        "HEROINE": "核心配角",
        "H_START": "初始立场",
        "H_MID": "立场变化",
        "H_FINAL": "关系定型",
        "POWER_LEVEL_1": "初阶",
        "POWER_LEVEL_2": "中阶",
        "POWER_LEVEL_3": "高阶",
        "POWER_LEVEL_MAX": "终阶",
        "RULE_1": "角色行为必须符合已建立动机",
        "RULE_2": "时间线不得自相矛盾",
        "RULE_3": "力量体系不得跳级失控",
        "DATE": now,
        "MAIN_PLOT": args.core_conflict,
        "START_LOCATION": "起始地点",
        "START_GOAL": args.protagonist_goal,
        "CHAPTER1_PLAN": "建立主角目标与核心冲突，留下章末钩子",
        "CHAPTER1_CHARACTERS": args.protagonist,
        "PROTAGONIST_NAME": args.protagonist,
        "POWER_LEVEL": "初阶",
        "LOCATION": "起始地点",
        "GOAL": args.protagonist_goal,
        "ITEMS": "暂无",
        "PERSONALITY": "待细化",
        "APPEARANCE": "待细化",
        "RELATION_1": "与核心配角：待建立",
        "RELATION_2": "与反派势力：待建立",
        "CHARACTER_A_NAME": "核心配角",
        "IDENTITY": "待设定",
        "RELATIONSHIP": "待设定",
        "STATUS": "待设定",
        "TIME_SYSTEM_DESCRIPTION": "以章节推进为主时间轴，可按天/周补充细化。",
        "POWER_SYSTEM_DESCRIPTION": "从初阶到终阶，逐步揭示规则与限制。",
        "PERSPECTIVE": "第三人称有限",
        "DISTANCE": "中等",
        "TENSE": "过去式",
        "AVG_SENTENCE_LENGTH": "24",
        "RATIO": "3:7",
        "AVG_PARAGRAPH_LENGTH": "4",
        "DIALOGUE_RATIO": "45",
        "WORD_STYLE": "口语与书面混合",
        "RHETORIC_DENSITY": "中",
        "SENSORY_PREFERENCE": "视觉为主",
        "HUMOR_LEVEL": "适中",
        "MAX_CLIMAX": "2",
        "MIN_BUFFER": "1",
        "RHYTHM_PATTERN": "升-升-爆-缓",
    }

    file_map = {
        "00_memory/idea_seed.md": template("idea_seed.template.md", mapping)
        + f"\n\n## 用户输入补充\n- 剧情种子：{args.idea}\n- 主角目标：{args.protagonist_goal}\n- 核心冲突：{args.core_conflict}\n",
        "00_memory/million_word_blueprint.md": template("million_word_blueprint.template.md", mapping),
        "00_memory/novel_plan.md": template("novel_plan.template.md", mapping),
        "00_memory/novel_state.md": template("novel_state.template.md", mapping),
        "00_memory/novel_findings.md": template("novel_findings.template.md", mapping),
        "00_memory/character_tracker.md": template("character_tracker.template.md", mapping),
        "00_memory/timeline.md": template("timeline.template.md", mapping),
        "00_memory/foreshadowing_tracker.md": template("foreshadowing_tracker.template.md", mapping),
        "00_memory/world_state.md": template("world_state.template.md", mapping),
        "00_memory/style_anchor.md": template("style_anchor.template.md", mapping),
        "00_memory/chapter_summaries/recent.md": template("chapter_summaries_recent.template.md", mapping),
        "02_knowledge_base/12_style_skills.md": "# 风格技能库\n\n- 初始化：待补充项目风格技能。\n",
    }

    for rel, content in file_map.items():
        write_if_needed(project_root / rel, content, overwrite, changed, skipped)

    first_chapter = project_root / "03_manuscript" / "第1章-开篇待写.md"
    first_stub = f"""# 第1章 开篇

<!-- NOVEL_FLOW_STUB -->

## 本章目标
- 建立主角目标：{args.protagonist_goal}
- 落地核心冲突：{args.core_conflict}

## 场景草图
- 起始地点：
- 冲突触发点：
- 章末钩子：

## 正文
[待写]
"""
    write_if_needed(first_chapter, first_stub, overwrite, changed, skipped)

    next_task = project_root / "00_memory" / "next_chapter_task.md"
    next_task_txt = f"""# 下一步写作任务

1. 先执行：`/继续写`
2. 当前建议章节：`{first_chapter.name}`
3. 当前剧情输入：{args.idea}
"""
    write_if_needed(next_task, next_task_txt, overwrite, changed, skipped)

    return {"changed": changed, "skipped": skipped}


def one_click(args: argparse.Namespace) -> Dict[str, object]:
    project_root = Path(args.project_root).expanduser().resolve()
    project_structure(project_root)
    files = init_project_files(project_root, args, overwrite=args.overwrite)

    build_code, build_out, build_err, build_payload = run_python(
        SCRIPT_DIR / "plot_rag_retriever.py",
        ["build", "--project-root", str(project_root)],
    )

    return {
        "ok": build_code == 0,
        "command": "one-click",
        "project_root": str(project_root),
        "created_or_updated_files": files["changed"],
        "skipped_files": files["skipped"],
        "index_result": build_payload if build_payload is not None else {"stdout": build_out, "stderr": build_err},
        "next_step": "/继续写",
    }


def chapter_is_draft_stub(path: Path) -> bool:
    txt = read_text(path)
    if "<!-- NOVEL_FLOW_STUB -->" in txt:
        return True
    return "[待写]" in txt


def continue_write(args: argparse.Namespace) -> Dict[str, object]:
    project_root = Path(args.project_root).expanduser().resolve()
    project_structure(project_root)
    manuscript_dir = project_root / "03_manuscript"
    ensure_dir(manuscript_dir)

    query = args.query.strip() if args.query else "推进下一章剧情"
    query_cmd = [
        "query",
        "--project-root",
        str(project_root),
        "--query",
        query,
        "--top-k",
        str(args.top_k),
        "--auto-build",
    ]
    if args.force_retrieval:
        query_cmd.append("--force")
    query_code, query_out, query_err, query_payload = run_python(SCRIPT_DIR / "plot_rag_retriever.py", query_cmd)

    if args.chapter_file:
        chapter_path = Path(args.chapter_file)
        if not chapter_path.is_absolute():
            chapter_path = project_root / chapter_path
        chapter_path = chapter_path.resolve()
    else:
        name = next_chapter_filename(manuscript_dir, title=args.chapter_title)
        chapter_path = (manuscript_dir / name).resolve()

    created_chapter_stub = False
    if not chapter_path.exists():
        created_chapter_stub = True
        stub = f"""# {chapter_path.stem.replace('-', ' ')}

<!-- NOVEL_FLOW_STUB -->

## 本章输入
- 剧情描述：{query}

## 正文
[待写]
"""
        write_text(chapter_path, stub)

    chapter_id = slugify(chapter_path.stem)
    gate_dir = project_root / "04_editing" / "gate_artifacts" / chapter_id
    ensure_dir(gate_dir)
    todo_file = gate_dir / "pipeline_todo.md"
    if not todo_file.exists():
        todo_txt = """# 章节流程待办

- [ ] /更新记忆 → 生成 memory_update.md
- [ ] /检查一致性 → 生成 consistency_report.md
- [ ] /风格校准 → 生成 style_calibration.md
- [ ] /校稿 → 生成 copyedit_report.md + publish_ready.md
- [ ] /门禁检查 → 生成 gate_result.json
- [ ] /更新剧情索引
"""
        write_text(todo_file, todo_txt)

    draft_mode = chapter_is_draft_stub(chapter_path)
    gate_payload = None
    repair_payload = None

    if not draft_mode:
        gate_code, gate_out, gate_err, gate_payload = run_python(
            SCRIPT_DIR / "chapter_gate_check.py",
            ["--project-root", str(project_root), "--chapter-file", str(chapter_path)],
        )
        passed = bool(gate_payload.get("passed")) if isinstance(gate_payload, dict) else False
        if gate_code != 0 or not passed:
            _, _, _, repair_payload = run_python(
                SCRIPT_DIR / "gate_repair_plan.py",
                ["--project-root", str(project_root), "--chapter-file", str(chapter_path)],
            )
    else:
        passed = False

    build_code, build_out, build_err, build_payload = run_python(
        SCRIPT_DIR / "plot_rag_retriever.py",
        ["build", "--project-root", str(project_root)],
    )

    result = {
        "ok": query_code == 0 and build_code == 0,
        "command": "continue-write",
        "project_root": str(project_root),
        "chapter_file": str(chapter_path),
        "created_chapter_stub": created_chapter_stub,
        "awaiting_draft": draft_mode,
        "query_result": query_payload if query_payload is not None else {"stdout": query_out, "stderr": query_err},
        "gate_result": gate_payload,
        "repair_result": repair_payload,
        "index_result": build_payload if build_payload is not None else {"stdout": build_out, "stderr": build_err},
        "todo_file": str(todo_file),
    }

    if draft_mode:
        result["next_step"] = "请先完成章节正文，再执行 /继续写（或指定 --chapter-file）触发门禁。"
    elif gate_payload and gate_payload.get("passed"):
        result["next_step"] = "章节已通过门禁，可进入下一章。"
    else:
        result["next_step"] = "章节未通过门禁，请执行 /修复本章 或查看 repair_plan.md。"

    return result


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="小说流程真实执行器：一键开书 / 继续写")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_one = sub.add_parser("one-click", help="执行 /一键开书")
    p_one.add_argument("--project-root", required=True, help="小说项目根目录")
    p_one.add_argument("--title", default="未命名小说")
    p_one.add_argument("--genre", default="待定题材")
    p_one.add_argument("--idea", default="待补充剧情种子")
    p_one.add_argument("--protagonist", default="主角")
    p_one.add_argument("--protagonist-goal", default="明确主角核心目标")
    p_one.add_argument("--core-conflict", default="主线冲突待细化")
    p_one.add_argument("--core-hook", default="高概念卖点待补充")
    p_one.add_argument("--ending", default="开放式结局（可后续修改）")
    p_one.add_argument("--target-words", type=int, default=3000000)
    p_one.add_argument("--overwrite", action="store_true", help="覆盖已存在的初始化文件")
    p_one.add_argument("--emit-json", help="额外输出 JSON 到指定路径")

    p_cont = sub.add_parser("continue-write", help="执行 /继续写")
    p_cont.add_argument("--project-root", required=True, help="小说项目根目录")
    p_cont.add_argument("--query", default="推进下一章剧情")
    p_cont.add_argument("--chapter-file", help="章节文件路径（可相对 project-root）")
    p_cont.add_argument("--chapter-title", default="待写")
    p_cont.add_argument("--top-k", type=int, default=4)
    p_cont.add_argument("--force-retrieval", action="store_true", help="强制执行剧情检索")
    p_cont.add_argument("--emit-json", help="额外输出 JSON 到指定路径")

    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.cmd == "one-click":
        payload = one_click(args)
    else:
        payload = continue_write(args)

    if args.emit_json:
        jp = Path(args.emit_json).expanduser().resolve()
        ensure_dir(jp.parent)
        jp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
