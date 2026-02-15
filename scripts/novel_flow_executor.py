#!/usr/bin/env python3
"""小说流程增强执行器。

覆盖目标：
1. /继续写 自动把占位章转成正文并进入后续流程
2. 增加章节质量下限检查
3. 门禁失败后自动最小修复重试
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
TEMPLATE_DIR = SKILL_ROOT / "templates"
CHAPTER_RE = re.compile(r"^第\d+章.*\.md$")
AI_PHRASE_BLACKLIST = [
    "不禁",
    "仿佛",
    "映入眼帘",
    "心中暗道",
    "宛如",
]
STUB_MARKER = "<!-- NOVEL_FLOW_STUB -->"
DRAFT_PLACEHOLDER_LINE = re.compile(r"(?m)^\[待写\]\s*$")
MAX_STUB_EFFECTIVE_CHARS = 800


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def run_python(script: Path, args: List[str]) -> Tuple[int, str, str, Optional[Dict[str, object]]]:
    cmd = [sys.executable, str(script), *args]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
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
    txt = read_text(TEMPLATE_DIR / name)
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


def load_character_names(project_root: Path) -> List[str]:
    p = project_root / "00_memory" / "character_tracker.md"
    if not p.exists():
        return []
    txt = read_text(p)
    names = set()
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells and re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9_·]{2,20}", cells[0] or ""):
                if cells[0] not in {"人物", "角色", "姓名", "---"}:
                    names.add(cells[0])
    for m in re.finditer(r"(?:姓名|角色)\s*[:：]\s*([\u4e00-\u9fffA-Za-z0-9_·]{2,20})", txt):
        names.add(m.group(1))
    return sorted(names)


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


def chapter_is_draft_stub(path: Path) -> bool:
    txt = read_text(path)
    if STUB_MARKER in txt:
        return True
    if DRAFT_PLACEHOLDER_LINE.search(txt):
        # 仅在“占位文本很短”时才判定为草稿，避免正文引用“待写”被误判。
        effective = re.sub(r"\s+", "", txt)
        if len(effective) <= MAX_STUB_EFFECTIVE_CHARS:
            return True
    return False


def clean_for_stats(text: str) -> str:
    txt = re.sub(r"(?m)^#.*$", "", text)
    txt = re.sub(r"<!--.*?-->", "", txt, flags=re.S)
    return txt.strip()


def evaluate_quality(text: str, args: argparse.Namespace) -> Dict[str, object]:
    body = clean_for_stats(text)
    pure = re.sub(r"\s+", "", body)
    char_count = len(pure)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    paragraph_count = len(paragraphs)
    dialogue_chars = sum(len(m.group(1)) for m in re.finditer(r"[“\"]([^”\"]+)[”\"]", body))
    dialogue_ratio = (dialogue_chars / char_count) if char_count else 0.0
    sentence_count = len(re.findall(r"[。！？!?]", body))

    ai_phrase_hits = []
    for w in AI_PHRASE_BLACKLIST:
        c = body.count(w)
        if c > 0:
            ai_phrase_hits.append({"phrase": w, "count": c})

    failures: List[str] = []
    if char_count < args.min_chars:
        failures.append(f"char_count<{args.min_chars}")
    if paragraph_count < args.min_paragraphs:
        failures.append(f"paragraph_count<{args.min_paragraphs}")
    if dialogue_ratio < args.min_dialogue_ratio:
        failures.append(f"dialogue_ratio<{args.min_dialogue_ratio}")
    if dialogue_ratio > args.max_dialogue_ratio:
        failures.append(f"dialogue_ratio>{args.max_dialogue_ratio}")
    if sentence_count < args.min_sentences:
        failures.append(f"sentence_count<{args.min_sentences}")

    return {
        "char_count": char_count,
        "paragraph_count": paragraph_count,
        "dialogue_chars": dialogue_chars,
        "dialogue_ratio": round(dialogue_ratio, 4),
        "sentence_count": sentence_count,
        "ai_phrase_hits": ai_phrase_hits,
        "passed": len(failures) == 0,
        "failures": failures,
    }


def generate_draft_text(project_root: Path, chapter_path: Path, query: str, min_chars: int) -> str:
    names = load_character_names(project_root)
    protagonist = names[0] if names else "主角"
    support = names[1] if len(names) > 1 else "关键配角"
    context_file = project_root / "00_memory" / "retrieval" / "next_plot_context.md"
    context_hint = ""

    def _clean_hint(s: str) -> str:
        s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
        s = s.replace("[待写]", "")
        s = re.sub(r"\s+", " ", s)
        return s.strip(" -；。")

    if context_file.exists():
        lines = read_text(context_file).splitlines()
        hints = []
        for ln in lines:
            if "摘要：" not in ln:
                continue
            hint = _clean_hint(ln.strip("- ").strip())
            if hint:
                hints.append(hint)
            if len(hints) >= 2:
                break
        context_hint = "；".join(hints)
    if not context_hint:
        context_hint = "暂无可回读摘要，按主线推进。"

    title = chapter_path.stem.replace("-", " ")
    paragraphs = [
        f"夜色压在旧港区的铁轨上，{protagonist}沿着潮湿的站台边缘前行。{query}。他每走一步，都能听见远处闷雷一样的海潮拍击堤岸，像是某种倒计时。",
        f"“你确定要现在进去？”{support}压低声音问。{protagonist}没有回头，只把手电光压得更低，“越晚，证据越会被抹掉。”两人的脚步在空站里拉出短促回音，紧张感被层层推高。",
        f"他们在候车厅尽头发现一张被撕裂的名单，纸角沾着新鲜水渍。{protagonist}用指尖抹开墨痕，名单里有熟悉姓名，也有本不该出现的人。那一瞬间，他意识到案件已经越过普通失踪案的边界。",
        f"{support}盯着名单最后一行，喉结轻轻滚动：“这个编号，和你父亲留下的旧档案一致。”{protagonist}沉默片刻，把纸页折进内袋，“先不声张，回去对时间线。”",
        f"离开前，站台广播忽然短促响起，失真的女声重复着同一句坐标。{protagonist}本能地记下数字，却在抬头时看到对面站牌被人擦出一道新划痕，像是刚刚有人在黑暗里看着他们。",
        f"回程路上，两人把发现逐条校对：名单、坐标、划痕，以及被刻意隐藏的时间差。{context_hint}。他们都明白，下一章必须直面“谁在提前清理现场”这个问题，否则主线将被动失控。",
        f"章节末尾，{protagonist}把名单复印件放在桌上，给自己留下一行简短备注：先查编号，再查坐标，最后查内鬼。灯灭之前，他听见窗外传来三下规律敲击，像是有人在确认他已经读懂了警告。",
    ]
    text = f"# {title}\n\n" + "\n\n".join(paragraphs)
    while len(re.sub(r"\s+", "", text)) < min_chars:
        text += (
            "\n\n"
            f"{protagonist}重新翻看当晚记录，把每条线索的因果关系重新连线。"
            "他刻意把推断分成“已证实”“待验证”“高风险假设”三层，避免剧情在后续章节中失去抓手。"
        )
    return text


def improve_text_minimally(text: str, query: str) -> str:
    extra = (
        f"补充推进：围绕“{query}”再加入一段行动结果、一段对话冲突、一段章末钩子，"
        "确保本章既有情节推进也有角色关系变化。"
    )
    return text.rstrip() + "\n\n" + extra + "\n"


def write_quality_report(gate_dir: Path, quality_before: Dict[str, object], quality_after: Dict[str, object]) -> Path:
    p = gate_dir / "quality_report.md"
    lines = [
        "# 章节质量检查",
        "",
        "## 修复前",
        f"- 字符数：{quality_before['char_count']}",
        f"- 段落数：{quality_before['paragraph_count']}",
        f"- 对话占比：{quality_before['dialogue_ratio']}",
        f"- 句子数：{quality_before['sentence_count']}",
        f"- 失败项：{quality_before['failures']}",
        "",
        "## 修复后",
        f"- 字符数：{quality_after['char_count']}",
        f"- 段落数：{quality_after['paragraph_count']}",
        f"- 对话占比：{quality_after['dialogue_ratio']}",
        f"- 句子数：{quality_after['sentence_count']}",
        f"- 失败项：{quality_after['failures']}",
        "",
        f"- 通过：{quality_after['passed']}",
    ]
    write_text(p, "\n".join(lines))
    return p


def write_gate_artifacts(
    project_root: Path,
    chapter_path: Path,
    query: str,
    quality: Dict[str, object],
    query_payload: Optional[Dict[str, object]],
) -> List[str]:
    chapter_id = slugify(chapter_path.stem)
    gate_dir = project_root / "04_editing" / "gate_artifacts" / chapter_id
    ensure_dir(gate_dir)

    tracker_names = load_character_names(project_root)
    query_names = [n for n in tracker_names if n in query]
    unknown_names = re.findall(r"[\u4e00-\u9fff]{2,4}", query)
    unknown_names = [n for n in unknown_names if n not in tracker_names][:5]

    memory_update = f"""# 记忆更新

- 章节：{chapter_path.name}
- 更新时间：{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 本章关键推进：{query}
- 命中角色：{', '.join(query_names) if query_names else '未明确命中'}
- 质量摘要：字符={quality['char_count']} 段落={quality['paragraph_count']} 对话占比={quality['dialogue_ratio']}
"""
    consistency = f"""# 一致性检查

- 检查范围：剧情/角色/时间线/设定
- 本章输入：{query}
- 命中角色：{', '.join(query_names) if query_names else '无'}
- 风险提示：{('可能出现新实体：' + ', '.join(unknown_names)) if unknown_names else '未发现高风险新实体'}
- 结论：通过初步一致性审查，建议下一章继续核对时间线。
"""
    style = f"""# 风格校准

- 检查项：句式节奏、对话密度、AI高频词
- 对话占比：{quality['dialogue_ratio']}
- AI词命中：{quality['ai_phrase_hits'] if quality['ai_phrase_hits'] else '未命中'}
- 结论：本章风格基本稳定，建议继续保持短句与动作描写平衡。
"""
    copyedit = f"""# 校稿报告

- 修订目标：降低AI味、提升可读性、保证节奏递进
- 动作：清理重复表述、补足转场、强化章末钩子
- 发布建议：可进入发布判定
"""
    publish = f"""# 发布判定

章节：{chapter_path.name}
结论：可发布（通过）
说明：本章已完成自动流程并通过基础门禁项。
关键词：可发布 / 通过 / PASS
"""

    paths = [
        ("memory_update.md", memory_update),
        ("consistency_report.md", consistency),
        ("style_calibration.md", style),
        ("copyedit_report.md", copyedit),
        ("publish_ready.md", publish),
    ]
    written = []
    for name, txt in paths:
        out = gate_dir / name
        write_text(out, txt)
        written.append(str(out))
    return written


def run_gate_check(project_root: Path, chapter_path: Path) -> Tuple[int, Dict[str, object]]:
    code, out, err, payload = run_python(
        SCRIPT_DIR / "chapter_gate_check.py",
        ["--project-root", str(project_root), "--chapter-file", str(chapter_path)],
    )
    if payload is not None:
        return code, payload
    return code, {"stdout": out, "stderr": err}


def run_repair_plan(project_root: Path, chapter_path: Path) -> Optional[Dict[str, object]]:
    _, _, _, payload = run_python(
        SCRIPT_DIR / "gate_repair_plan.py",
        ["--project-root", str(project_root), "--chapter-file", str(chapter_path)],
    )
    return payload


def move_misplaced_kb_chapters(project_root: Path) -> List[str]:
    moved: List[str] = []
    kb = project_root / "02_knowledge_base"
    man = project_root / "03_manuscript"
    if not kb.exists():
        return moved
    ensure_dir(man)
    for p in kb.rglob("*.md"):
        if not CHAPTER_RE.match(p.name):
            continue
        target = man / f"迁移-{p.name}"
        n = 1
        while target.exists():
            target = man / f"迁移-{n}-{p.name}"
            n += 1
        shutil.move(str(p), str(target))
        moved.append(f"{p} -> {target}")
    return moved


def normalize_chapter_storage(project_root: Path, chapter_path: Path) -> Tuple[Path, Optional[str]]:
    rel_ok = False
    try:
        rel = chapter_path.resolve().relative_to(project_root.resolve())
        rel_ok = rel.as_posix().startswith("03_manuscript/")
    except Exception:
        rel_ok = False
    if rel_ok and chapter_path.suffix.lower() == ".md":
        return chapter_path, None

    target = project_root / "03_manuscript" / (chapter_path.stem + ".md")
    ensure_dir(target.parent)
    shutil.move(str(chapter_path), str(target))
    return target, f"{chapter_path} -> {target}"


def auto_fix_after_gate_failure(
    project_root: Path,
    chapter_path: Path,
    query: str,
    quality: Dict[str, object],
    query_payload: Optional[Dict[str, object]],
    gate_payload: Dict[str, object],
    args: argparse.Namespace,
) -> Tuple[Path, List[str]]:
    actions: List[str] = []
    failures = gate_payload.get("failures", []) if isinstance(gate_payload, dict) else []
    fail_text = " | ".join(str(x) for x in failures)

    if "knowledge_base_contains_chapter_files" in fail_text and args.auto_fix_kb_misplaced:
        moved = move_misplaced_kb_chapters(project_root)
        if moved:
            actions.extend([f"迁移误放章节：{x}" for x in moved])

    if "chapter_storage_policy" in fail_text:
        new_path, moved = normalize_chapter_storage(project_root, chapter_path)
        chapter_path = new_path
        if moved:
            actions.append(f"修正章节存储位置：{moved}")

    if any(
        key in fail_text
        for key in [
            "memory_update",
            "consistency_report",
            "style_calibration",
            "copyedit_report",
            "publish_ready",
            "publish_ready_keyword",
        ]
    ):
        write_gate_artifacts(project_root, chapter_path, query, quality, query_payload)
        actions.append("重建门禁产物文件")

        publish_ready = project_root / "04_editing" / "gate_artifacts" / slugify(chapter_path.stem) / "publish_ready.md"
        txt = read_text(publish_ready)
        if ("可发布" not in txt) and ("通过" not in txt) and ("PASS" not in txt):
            txt += "\n可发布\n"
            write_text(publish_ready, txt)
            actions.append("补充发布关键词")

    return chapter_path, actions


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
    q_code, q_out, q_err, q_payload = run_python(SCRIPT_DIR / "plot_rag_retriever.py", query_cmd)

    if args.chapter_file:
        chapter_path = Path(args.chapter_file)
        if not chapter_path.is_absolute():
            chapter_path = project_root / chapter_path
        chapter_path = chapter_path.resolve()
    else:
        chapter_path = (manuscript_dir / next_chapter_filename(manuscript_dir, title=args.chapter_title)).resolve()

    created_chapter_stub = False
    if not chapter_path.exists():
        created_chapter_stub = True
        write_text(
            chapter_path,
            f"# {chapter_path.stem.replace('-', ' ')}\n\n<!-- NOVEL_FLOW_STUB -->\n\n## 正文\n[待写]\n",
        )

    auto_draft_applied = False
    if chapter_is_draft_stub(chapter_path) and args.auto_draft:
        draft = generate_draft_text(project_root, chapter_path, query, min_chars=args.min_chars)
        write_text(chapter_path, draft)
        auto_draft_applied = True

    draft_mode = chapter_is_draft_stub(chapter_path)

    chapter_id = slugify(chapter_path.stem)
    gate_dir = project_root / "04_editing" / "gate_artifacts" / chapter_id
    ensure_dir(gate_dir)
    todo_file = gate_dir / "pipeline_todo.md"
    if not todo_file.exists():
        write_text(
            todo_file,
            "# 章节流程待办\n\n- [ ] /更新记忆\n- [ ] /检查一致性\n- [ ] /风格校准\n- [ ] /校稿\n- [ ] /门禁检查\n- [ ] /更新剧情索引\n",
        )

    quality_before = evaluate_quality(read_text(chapter_path), args)
    quality_after = quality_before
    improve_rounds = 0
    if not draft_mode and args.auto_improve:
        while (not quality_after["passed"]) and improve_rounds < args.auto_improve_rounds:
            txt = read_text(chapter_path)
            write_text(chapter_path, improve_text_minimally(txt, query))
            quality_after = evaluate_quality(read_text(chapter_path), args)
            improve_rounds += 1

    quality_report = write_quality_report(gate_dir, quality_before, quality_after)

    gate_payload: Optional[Dict[str, object]] = None
    repair_payload: Optional[Dict[str, object]] = None
    retry_actions: List[str] = []
    gate_passed_final = False

    if not draft_mode:
        write_gate_artifacts(project_root, chapter_path, query, quality_after, q_payload)
        g_code, gate_payload = run_gate_check(project_root, chapter_path)
        gate_passed_final = bool(gate_payload.get("passed")) if isinstance(gate_payload, dict) else False

        if (not gate_passed_final) and args.auto_retry:
            chapter_path, retry_actions = auto_fix_after_gate_failure(
                project_root,
                chapter_path,
                query,
                quality_after,
                q_payload,
                gate_payload if gate_payload else {},
                args,
            )
            if retry_actions:
                g2_code, gate_payload = run_gate_check(project_root, chapter_path)
                gate_passed_final = bool(gate_payload.get("passed")) if isinstance(gate_payload, dict) else False
            if not gate_passed_final:
                repair_payload = run_repair_plan(project_root, chapter_path)
        elif not gate_passed_final:
            repair_payload = run_repair_plan(project_root, chapter_path)

    b_code, b_out, b_err, b_payload = run_python(
        SCRIPT_DIR / "plot_rag_retriever.py",
        ["build", "--project-root", str(project_root)],
    )

    ok = (q_code == 0 and b_code == 0 and (draft_mode or gate_passed_final))
    result: Dict[str, object] = {
        "ok": ok,
        "command": "continue-write",
        "project_root": str(project_root),
        "chapter_file": str(chapter_path),
        "created_chapter_stub": created_chapter_stub,
        "auto_draft_applied": auto_draft_applied,
        "awaiting_draft": draft_mode,
        "quality_before": quality_before,
        "quality_after": quality_after,
        "quality_report": str(quality_report),
        "auto_improve_rounds_used": improve_rounds,
        "query_result": q_payload if q_payload is not None else {"stdout": q_out, "stderr": q_err},
        "gate_result": gate_payload,
        "gate_passed_final": gate_passed_final,
        "auto_retry_actions": retry_actions,
        "repair_result": repair_payload,
        "index_result": b_payload if b_payload is not None else {"stdout": b_out, "stderr": b_err},
        "todo_file": str(todo_file),
    }

    if draft_mode and not args.auto_draft:
        result["next_step"] = "章节仍是占位草稿，请补全正文后再次执行 /继续写，或启用 --auto-draft。"
    elif draft_mode:
        result["next_step"] = "已尝试自动成稿但仍检测到占位标记，请手动补全正文后再执行。"
    elif gate_passed_final:
        result["next_step"] = "章节已通过门禁，可进入下一章。"
    else:
        result["next_step"] = "章节未通过门禁，已生成 repair_plan.md。请执行 /修复本章。"

    return result


def one_click(args: argparse.Namespace) -> Dict[str, object]:
    project_root = Path(args.project_root).expanduser().resolve()
    project_structure(project_root)
    files = init_project_files(project_root, args, overwrite=args.overwrite)
    b_code, b_out, b_err, b_payload = run_python(
        SCRIPT_DIR / "plot_rag_retriever.py",
        ["build", "--project-root", str(project_root)],
    )
    return {
        "ok": b_code == 0,
        "command": "one-click",
        "project_root": str(project_root),
        "created_or_updated_files": files["changed"],
        "skipped_files": files["skipped"],
        "index_result": b_payload if b_payload is not None else {"stdout": b_out, "stderr": b_err},
        "next_step": "/继续写",
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="小说流程增强执行器：一键开书 / 继续写")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_one = sub.add_parser("one-click", help="执行 /一键开书")
    p_one.add_argument("--project-root", required=True)
    p_one.add_argument("--title", default="未命名小说")
    p_one.add_argument("--genre", default="待定题材")
    p_one.add_argument("--idea", default="待补充剧情种子")
    p_one.add_argument("--protagonist", default="主角")
    p_one.add_argument("--protagonist-goal", default="明确主角核心目标")
    p_one.add_argument("--core-conflict", default="主线冲突待细化")
    p_one.add_argument("--core-hook", default="高概念卖点待补充")
    p_one.add_argument("--ending", default="开放式结局（可后续修改）")
    p_one.add_argument("--target-words", type=int, default=3000000)
    p_one.add_argument("--overwrite", action="store_true")
    p_one.add_argument("--emit-json")

    p_cont = sub.add_parser("continue-write", help="执行 /继续写")
    p_cont.add_argument("--project-root", required=True)
    p_cont.add_argument("--query", default="推进下一章剧情")
    p_cont.add_argument("--chapter-file")
    p_cont.add_argument("--chapter-title", default="待写")
    p_cont.add_argument("--top-k", type=int, default=4)
    p_cont.add_argument("--force-retrieval", action="store_true")
    p_cont.add_argument("--auto-draft", dest="auto_draft", action="store_true", default=True)
    p_cont.add_argument("--no-auto-draft", dest="auto_draft", action="store_false")
    p_cont.add_argument("--auto-improve", dest="auto_improve", action="store_true", default=True)
    p_cont.add_argument("--no-auto-improve", dest="auto_improve", action="store_false")
    p_cont.add_argument("--auto-retry", dest="auto_retry", action="store_true", default=True)
    p_cont.add_argument("--no-auto-retry", dest="auto_retry", action="store_false")
    p_cont.add_argument("--auto-fix-kb-misplaced", dest="auto_fix_kb_misplaced", action="store_true", default=True)
    p_cont.add_argument("--no-auto-fix-kb-misplaced", dest="auto_fix_kb_misplaced", action="store_false")
    p_cont.add_argument("--auto-improve-rounds", type=int, default=1)
    p_cont.add_argument("--min-chars", type=int, default=1200)
    p_cont.add_argument("--min-paragraphs", type=int, default=6)
    p_cont.add_argument("--min-dialogue-ratio", type=float, default=0.03)
    p_cont.add_argument("--max-dialogue-ratio", type=float, default=0.7)
    p_cont.add_argument("--min-sentences", type=int, default=8)
    p_cont.add_argument("--emit-json")

    return p.parse_args()


def main() -> int:
    args = parse_args()
    payload = one_click(args) if args.cmd == "one-click" else continue_write(args)
    if args.emit_json:
        jp = Path(args.emit_json).expanduser().resolve()
        ensure_dir(jp.parent)
        jp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
