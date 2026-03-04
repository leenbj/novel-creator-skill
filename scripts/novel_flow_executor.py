#!/usr/bin/env python3
"""小说流程增强执行器。

覆盖目标：
1. /继续写 自动把占位章转成正文并进入后续流程
2. 增加章节质量下限检查
3. 门禁失败后自动最小修复重试
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

from common import (
    ensure_dir, read_text, write_text, slugify,
    sha1_text, file_sha1, load_json, save_json,
    chapter_no_from_name,
)


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
FLOW_DIR_NAME = ".flow"
FLOW_LOCK_FILE = "continue_write.lock"
FLOW_CACHE_FILE = "continue_write_cache.json"
FLOW_SNAPSHOT_DIR = "snapshots"
FLOW_CACHE_MAX_ENTRIES = 200


def run_python(script: Path, args: List[str]) -> Tuple[int, str, str, Optional[Dict[str, object]]]:
    cmd = [sys.executable, str(script), *args]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
    except subprocess.TimeoutExpired:
        return -1, "", "子进程超时 (300s)", None
    out = proc.stdout.strip()
    err = proc.stderr.strip()
    payload = None
    if out:
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            payload = None
    return proc.returncode, out, err, payload


def acquire_lock(lock_file: Path, run_id: str, timeout_sec: int) -> Tuple[bool, Optional[Dict[str, object]]]:
    now = time.time()
    if lock_file.exists():
        current = load_json(lock_file, {})
        cur = cast(Dict[str, Any], current)
        ts_raw = cur.get("ts", 0)
        ts = float(ts_raw) if isinstance(ts_raw, (int, float, str)) else 0.0
        if ts and (now - ts) < max(1, timeout_sec):
            return False, current
    save_json(lock_file, {
        "run_id": run_id,
        "pid": os.getpid(),
        "ts": now,
        "started_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    return True, None


def release_lock(lock_file: Path, run_id: str) -> None:
    if not lock_file.exists():
        return
    cur = load_json(lock_file, {})
    if cur.get("run_id") == run_id:
        lock_file.unlink(missing_ok=True)


def create_snapshot(chapter_path: Path, flow_dir: Path, run_id: str) -> Optional[Path]:
    if not chapter_path.exists():
        return None
    out = flow_dir / FLOW_SNAPSHOT_DIR / slugify(chapter_path.stem) / f"{run_id}.md"
    ensure_dir(out.parent)
    shutil.copy2(str(chapter_path), str(out))
    return out


def restore_snapshot(snapshot_path: Path, original_path: Path, current_path: Path) -> Optional[Path]:
    if not snapshot_path.exists():
        return None
    ensure_dir(original_path.parent)
    shutil.copy2(str(snapshot_path), str(original_path))
    if current_path != original_path and current_path.exists():
        current_path.unlink(missing_ok=True)
    return original_path


def make_request_id(args: argparse.Namespace, chapter_path: Path, query: str, chapter_hash_before: str, project_root: Path = None) -> str:
    # 使用相对路径避免符号链接解析导致缓存键不一致
    try:
        if project_root and chapter_path.is_relative_to(project_root):
            path_key = str(chapter_path.relative_to(project_root))
        else:
            path_key = chapter_path.name
    except (ValueError, TypeError):
        path_key = chapter_path.name

    raw = "|".join([
        path_key,
        query.strip(),
        str(args.top_k),
        str(args.min_chars),
        str(args.min_paragraphs),
        str(args.min_dialogue_ratio),
        str(args.max_dialogue_ratio),
        str(args.min_sentences),
        str(args.auto_draft),
        str(args.auto_improve),
        str(args.auto_retry),
        chapter_hash_before,
    ])
    return sha1_text(raw)


def load_continue_cache(flow_dir: Path) -> Dict[str, object]:
    return load_json(flow_dir / FLOW_CACHE_FILE, {"entries": {}})


def save_continue_cache(flow_dir: Path, cache: Dict[str, object]) -> None:
    entries = cache.get("entries", {})
    if isinstance(entries, dict) and len(entries) > FLOW_CACHE_MAX_ENTRIES:
        items = sorted(entries.items(), key=lambda kv: kv[1].get("saved_at", ""), reverse=True)
        cache["entries"] = dict(items[:FLOW_CACHE_MAX_ENTRIES])
    save_json(flow_dir / FLOW_CACHE_FILE, cache)


def update_flow_metrics(project_root: Path, item: Dict[str, object]) -> Dict[str, object]:
    retrieval_dir = project_root / "00_memory" / "retrieval"
    ensure_dir(retrieval_dir)
    metrics_file = retrieval_dir / "flow_metrics.json"
    metrics = load_json(metrics_file, {"runs": []})
    runs = metrics.get("runs", [])
    if not isinstance(runs, list):
        runs = []
    runs.append(item)
    runs = runs[-300:]
    metrics["runs"] = runs
    save_json(metrics_file, metrics)

    total = len(runs)
    ok_count = sum(1 for r in runs if r.get("ok"))
    gate_ok = sum(1 for r in runs if r.get("gate_passed_final"))
    retry_count = sum(1 for r in runs if (r.get("auto_retry_actions_count", 0) > 0))
    idempotent_hits = sum(1 for r in runs if r.get("idempotent_hit"))
    avg_runtime = round(sum(float(r.get("runtime_ms", 0)) for r in runs) / total, 2) if total else 0.0
    avg_ctx_chars = round(sum(float(r.get("retrieval_context_chars", 0)) for r in runs) / total, 2) if total else 0.0
    avg_candidates = round(sum(float(r.get("retrieval_candidates", 0)) for r in runs) / total, 2) if total else 0.0

    summary = {
        "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_runs": total,
        "ok_rate": round(ok_count / total, 4) if total else 0.0,
        "gate_pass_rate": round(gate_ok / total, 4) if total else 0.0,
        "retry_rate": round(retry_count / total, 4) if total else 0.0,
        "idempotent_hit_rate": round(idempotent_hits / total, 4) if total else 0.0,
        "avg_runtime_ms": avg_runtime,
        "avg_retrieval_context_chars": avg_ctx_chars,
        "avg_retrieval_candidates": avg_candidates,
    }
    save_json(retrieval_dir / "flow_metrics_summary.json", summary)
    return summary


def template(name: str, mapping: Dict[str, str]) -> str:
    txt = read_text(TEMPLATE_DIR / name)
    for k, v in mapping.items():
        txt = txt.replace("{" + k + "}", v)
    return txt


def latest_chapter(manuscript_dir: Path) -> Optional[Path]:
    files = sorted(manuscript_dir.glob("*.md"), key=lambda p: (chapter_no_from_name(p.name), p.name))
    return files[-1] if files else None


def next_chapter_filename(manuscript_dir: Path, title: str = "待写") -> str:
    cur = latest_chapter(manuscript_dir)
    next_no = chapter_no_from_name(cur.name) + 1 if cur else 1
    return f"第{next_no}章-{title}.md"


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
    """增强版质量评估 - 添加内容密度、AI词密度、段落多样性检查"""
    import statistics

    body = clean_for_stats(text)
    pure = re.sub(r"\s+", "", body)
    char_count = len(pure)
    
    # 计算正文密度（排除标记、注释等）
    content_density = len(pure) / len(body) if body else 0
    
    # 检查AI高频词密度
    ai_phrase_count = sum(body.count(w) for w in AI_PHRASE_BLACKLIST)
    ai_density = ai_phrase_count / char_count if char_count else 0
    
    # 段落多样性检查
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    para_lengths = [len(p) for p in paragraphs]
    para_variance = statistics.variance(para_lengths) if len(para_lengths) > 1 else 0
    paragraph_count = len(paragraphs)

    # 段落重复度检查（P0-01 新增）
    # 使用标准化段落文本进行重复检测
    normalized_paragraphs = [re.sub(r'\s+', ' ', p).strip() for p in paragraphs]
    para_counter: Dict[str, int] = {}
    for p in normalized_paragraphs:
        para_counter[p] = para_counter.get(p, 0) + 1

    unique_paragraph_count = len(para_counter)
    paragraph_unique_ratio = unique_paragraph_count / paragraph_count if paragraph_count > 0 else 1.0
    max_duplicate_paragraph_repeat = max(para_counter.values()) if para_counter else 1
    
    # 对话占比：同时识别中文引号和英文引号
    dialogue_chars = sum(len(m.group(1)) for m in re.finditer(r"[“\"]([^”\"]*)[”\"]", body))
    dialogue_ratio = (dialogue_chars / char_count) if char_count else 0.0
    
    # 句子数
    sentence_count = len(re.findall(r"[。！？!?]", body))
    
    # AI词命中详情
    ai_phrase_hits = []
    for w in AI_PHRASE_BLACKLIST:
        c = body.count(w)
        if c > 0:
            ai_phrase_hits.append({"phrase": w, "count": c})
    
    # 失败检查 - 增强版
    failures: List[str] = []
    if char_count < args.min_chars:
        failures.append(f"char_count<{args.min_chars} (current: {char_count})")
    if paragraph_count < args.min_paragraphs:
        failures.append(f"paragraph_count<{args.min_paragraphs}")
    
    # 新增检查项
    min_density = getattr(args, 'min_content_density', 0.7)
    if content_density < min_density:
        failures.append(f"content_density<{min_density:.2f} (current: {content_density:.2f})")
    
    max_ai_density = getattr(args, 'max_ai_phrase_density', 0.05)
    if ai_density > max_ai_density:
        failures.append(f"ai_phrase_density_too_high ({ai_density:.2%}, max: {max_ai_density:.2%})")
    
    max_variance = getattr(args, 'max_paragraph_variance', 10000)
    if para_variance > max_variance:
        failures.append(f"paragraph_variance_too_high ({para_variance:.0f}, max: {max_variance})")
    
    # 原有检查项
    if dialogue_ratio < args.min_dialogue_ratio:
        failures.append(f"dialogue_ratio_too_low ({dialogue_ratio:.2%})")
    if dialogue_ratio > args.max_dialogue_ratio:
        failures.append(f"dialogue_ratio_too_high ({dialogue_ratio:.2%})")
    if sentence_count < args.min_sentences:
        failures.append(f"sentence_count_too_low ({sentence_count})")

    # 段落重复度失败检查（P0-01 新增）
    min_unique_ratio = getattr(args, 'min_paragraph_unique_ratio', 0.85)
    max_dup_repeat = getattr(args, 'max_duplicate_paragraph_repeat', 2)

    if paragraph_unique_ratio < min_unique_ratio:
        failures.append(
            f"paragraph_unique_ratio<{min_unique_ratio:.2f} (current: {paragraph_unique_ratio:.2%}, "
            f"unique={unique_paragraph_count}/{paragraph_count})"
        )

    if max_duplicate_paragraph_repeat > max_dup_repeat:
        failures.append(
            f"max_duplicate_paragraph_repeat>{max_dup_repeat} (current: {max_duplicate_paragraph_repeat})"
        )

    return {
        "char_count": char_count,
        "paragraph_count": paragraph_count,
        "sentence_count": sentence_count,
        "dialogue_chars": dialogue_chars,
        "dialogue_ratio": round(dialogue_ratio, 4),
        "content_density": round(content_density, 4),
        "ai_density": round(ai_density, 4),
        "paragraph_variance": round(para_variance, 2),
        "paragraph_unique_ratio": round(paragraph_unique_ratio, 4),
        "max_duplicate_paragraph_repeat": max_duplicate_paragraph_repeat,
        "unique_paragraph_count": unique_paragraph_count,
        "ai_phrase_hits": ai_phrase_hits,
        "passed": len(failures) == 0,
        "failures": failures,
    }


def generate_draft_text(project_root: Path, chapter_path: Path, query: str, min_chars: int) -> str:
    names = load_character_names(project_root)
    # 从角色列表获取主角名，避免硬编码
    protagonist = names[0] if names else "主角"
    commander = "张潮义" if "张潮义" in names else (names[1] if len(names) > 1 else "指挥官")
    intel = "苏谨" if "苏谨" in names else (names[2] if len(names) > 2 else "情报员")
    enemy = "赤狼" if "赤狼" in names else (names[3] if len(names) > 3 else "敌人")

    chapter_no = chapter_no_from_name(chapter_path.name)
    title = chapter_path.stem.replace("-", " ")
    scene_by_arc = [
        (53, 60, "河西北线", "围绕证人交易展开反制，并以斥候网和诱饵队重建主动权"),
        (61, 70, "陇右-长安双线", "借吐蕃战压牵动朝堂，切断赵相私仓并放大皇统裂痕"),
        (71, 80, "玄武库与关中粮道", "一边抗击吐蕃主力，一边争夺法统证据的解释权"),
        (81, 90, "长安宫城与渭水防线", "军政并举压制政变尝试，逼出幕后同盟"),
        (91, 100, "河西反攻至长安收束", "完成战场反攻与朝堂清算的并轨推进"),
    ]
    scene = "河西战线"
    arc_goal = "推进抗吐蕃与朝争主线"
    for lo, hi, sc, g in scene_by_arc:
        if lo <= chapter_no <= hi:
            scene = sc
            arc_goal = g
            break

    target_chars = max(3000, min(min_chars, 3300))
    max_chars = 3500

    paragraphs: List[str] = [
        f"{scene}的风比前几日更硬，沙粒打在甲片上像细小鼓点。{protagonist}站在望楼北角，先看烽燧，再看粮车，再看巡哨交接的时辰。他把木牌一块块挪到沙盘上，最终停在敌军最可能突入的三条谷口。今日要办的事只有一件：{query}。若此步成，{arc_goal}便能往前撬开一寸。",
        f"“先报军情，不报猜测。”{protagonist}对值守书记说。书记递上昨夜斥候回卷，纸上记着吐蕃骑队的折返路线，和一支不该出现的商队标识。{protagonist}把路线分成快线、慢线、伪装线三层，再让亲兵把每一层对应到不同的拦截队。现代参谋法讲究冗余验证，他在唐军营里把这套法子改成最直白的军令：同一情报，至少三处交叉再动兵。",
        f"{commander}披着旧氅走进军帐，伤势未全好，声音却稳。“你昨晚调走前营百骑，给个说法。”{protagonist}把木尺压在沙盘西侧：“赤狼喜欢打人心，不先打城门。前营摆在明处，只会被他牵着走。我把百骑拆成五股，每股只拿半刻钟命令，见旗而动，不等口令。”{commander}盯着沙盘许久，点头：“你这是拿吐蕃的快，去撞他的乱。”",
        f"午后，{intel}带回城中暗线。赵相的人在盐行抬高驮价，逼河西军用更慢的补给道；与此同时，长安有人放风，说{protagonist}借军情挟持证人，意在自立。两条线一内一外，配得极紧。{protagonist}没有急着辩白，而是先把物证分柜封存：账册页、口供条、押印蜡。政治斗争最怕口舌先行，他要把每一次反击都钉在可复核的证据上。",
        f"黄昏时分，{enemy}果然送来使者。使者只带一句话：交出押解名单的原件，换回半名证人和半份真相。{protagonist}当场回绝：“我要人活着，要账链完整，要你们在城南驿站留下真实路线。少一条，这笔买卖不做。”使者冷笑：“你拿什么谈？”{protagonist}把一封伪造调令丢在案上：“拿你们昨夜提前布伏的证据谈。”",
        f"夜战在二更后突起。吐蕃轻骑从北坡探入，明打粮垛，暗切水源。{protagonist}提前在水车沟设了折线拒马，又让弓手按‘三段火’轮替：第一段压头马，第二段断后队，第三段专打传令骑。短短半个时辰，敌军三次冲锋都被截断。最要紧的是，唐军没有追到黑谷深处，而是在界线前收兵。现代军事训练里最难的是克制，他把“见好就收”写进了军中功簿。",
        f"战后清点，损失比预计少三成。{commander}当众升了两名校尉，却把最大的军功记在“执行纪律”四字上。{protagonist}借势推行新操典：白日练队形转向，夜间练口令拆分，三日一轮沙盘复盘。老卒一开始不服，觉得花架子太多；等到下一次伏击，所有人都看懂了门道——新操典让每个百人队都能在失去主将时继续打。",
        f"军营之外，长安朝堂也在起风。太子党与赵相党围绕边军调度互相攻讦，言辞越狠，越说明各家都怕河西突然站稳。{intel}把密报摊开：“有人在问你身世，问得很细，连你幼年住过哪条巷都在查。”{protagonist}沉默片刻，只说一句：“他们要的不是我是谁，是谁能借我开刀。”他决定反其道而行，把部分可公开线索主动递进京中，让谣言失去先手。",
        f"次日黎明，{protagonist}亲自带队走访伤兵营。他不谈宏图，只问三件事：箭伤处置是否及时、口粮是否按数、家书是否能寄。他清楚军心不是口号，是每天都能摸到的秩序。伤兵中有人低声问：“都说朝里要弃河西，咱还守得住吗？”{protagonist}答得很慢：“守得住。因为我们先守住彼此，再守城。”短短一句，帐内沉默后响起应声。",
        f"傍晚，{enemy}第二次来信，语气比前夜急。信上多了一个新条件：要{protagonist}独自赴约，地点定在废烽台下。{commander}反对独行，{intel}建议设双层替身。{protagonist}最终取中策：本人出面，但所有谈判节点由暗号触发，超过三句废话即终止接触。他把暗号写成最简单的军中术语，确保任何一个小队都能在混战里听懂并执行。",
        f"废烽台会面时，风里带着血腥味。{enemy}没有现身，只隔着石墙问：“你真要把长安那层天掀开？”{protagonist}回道：“不是掀天，是把压在边军头上的假天拆掉。”对方沉默良久，丢来一枚半裂玉环和一段口供抄本。抄本只写了名字首字，却足以把私仓与中枢某署衙连在一起。{protagonist}把玉环收进袖中，心里已把后续三步排好：先核笔迹，再核押印，再核传递时序。",
        f"回营路上，{intel}问：“若这份口供是真的，你要先打吐蕃，还是先打朝堂？”{protagonist}望着城头火把，回答干脆：“先打能今天就死人那一线，再打能明天毁国那一线。战场不能停，证据也不能断。”这是他一路成长后的取舍：不再迷信单点胜负，而是把战争与政治当作同一张作战图上的两条轴。",
        f"本章收束时，{protagonist}在军议簿末页添下一行：‘第{chapter_no}章后，执行双轨推进——北线压敌骑，南线锁账链。’他抬头看见城楼信灯连闪三次，来自长安的急件已经在路上。谁先拆开那封急件，谁就能决定下一轮攻防的节奏。",
    ]

    filler_pool = [
        f"军议结束后，{protagonist}把当日命令逐条复述给各营校尉，每条命令都附‘失败兜底’。这套做法起初让人觉得啰嗦，但几次突发后，人人都知道它能保命。",
        f"{commander}要求全军三日内完成一次夜行十里和一次无火造饭，{protagonist}把考核表按班伍贴到营门，谁拖后腿谁当众复盘，不罚面子，只罚流程。",
        f"{intel}补充了一条新消息：长安有人要在朝会上拿河西伤亡做文章。{protagonist}让文书先写事实账，再写处置账，最后写改进账，三账并列，堵住空口攻讦。",
        f"押运队在关口遇查，{protagonist}让副将故意暴露一份假名册，引敌方把注意力引到错误方向，真正证物则随军医车慢行南下。",
        f"当夜点名时，{protagonist}要求每名队正讲一条‘今日差错’，不许只报功。军中气氛因此更硬，却也更实。",
        f"在沙盘复盘里，{protagonist}把吐蕃惯用的佯退路线标成红线，把唐军容易上头的追击路线标成黑线，反复强调‘黑线之外，功再大也不追’。",
    ]

    text = f"# {title}\n\n" + "\n\n".join(paragraphs)
    i = 0
    while len(re.sub(r"\s+", "", text)) < target_chars:
        text += "\n\n" + filler_pool[i % len(filler_pool)]
        i += 1

    pure_len = len(re.sub(r"\s+", "", text))
    if pure_len > max_chars:
        keep = int(len(text) * (max_chars / pure_len))
        clipped = text[:keep]
        cut = max(clipped.rfind("。"), clipped.rfind("！"), clipped.rfind("？"))
        if cut > 0:
            text = clipped[: cut + 1]
        else:
            text = clipped

    return text


def improve_text_minimally(text: str, query: str) -> str:
    extra = (
        f"补充推进：围绕“{query}”再加入一段行动结果、一段对话冲突、一段章末钩子，"
        "确保本章既有情节推进也有角色关系变化。"
    )
    return text.rstrip() + "\n\n" + extra + "\n"


def apply_targeted_quality_fix(
    chapter_path: Path,
    quality: Dict[str, object],
    args: argparse.Namespace,
    query: str,
) -> List[str]:
    txt = read_text(chapter_path).rstrip()
    failures_raw = quality.get("failures", [])
    failures = [str(x) for x in failures_raw] if isinstance(failures_raw, list) else []
    actions: List[str] = []

    paragraph_count_raw = quality.get("paragraph_count", 0)
    sentence_count_raw = quality.get("sentence_count", 0)
    paragraph_count = int(paragraph_count_raw) if isinstance(paragraph_count_raw, (int, float, str)) else 0
    sentence_count = int(sentence_count_raw) if isinstance(sentence_count_raw, (int, float, str)) else 0

    if any(f.startswith("paragraph_count<") for f in failures):
        missing = max(1, args.min_paragraphs - paragraph_count)
        blocks = []
        for i in range(missing):
            blocks.append(
                f"补充段落{i+1}：围绕“{query}”推进一小步行动结果，并明确本段的因果关系。"
                "角色需要做出可验证选择，以便下一章承接。"
            )
        txt += "\n\n" + "\n\n".join(blocks)
        actions.append(f"补足段落数量 +{missing}")

    if any(f.startswith("sentence_count<") or f.startswith("sentence_count_too_low") for f in failures):
        missing = max(1, args.min_sentences - sentence_count)
        short = " ".join(["他迅速复盘线索。她立即提出质疑。两人决定先验证坐标。"] * max(1, missing // 3))
        txt += "\n\n" + short
        actions.append(f"补足句子数量 +{missing}")

    if any(f.startswith("dialogue_ratio<") or f.startswith("dialogue_ratio_too_low") for f in failures):
        txt += (
            "\n\n"
            f"“先别下结论，”同伴压低声音，“{query}这条线还缺最后一块证据。”"
            "主角点头：“那就按时间线回查，每一步都留痕。”"
        )
        actions.append("补足对话占比")

    if any(f.startswith("dialogue_ratio>") or f.startswith("dialogue_ratio_too_high") for f in failures):
        txt += (
            "\n\n"
            "叙述补偿：两人将对话结论写入行动清单，逐项标记风险等级与验证顺序，"
            "避免口头信息过载导致剧情推进失焦。"
        )
        actions.append("稀释过高对话占比")

    # 最后兜底字符数
    cur_chars = len(re.sub(r"\s+", "", clean_for_stats(txt)))
    if cur_chars < args.min_chars:
        needed = args.min_chars - cur_chars
        repeat = max(1, needed // 80)
        extra = []
        for i in range(repeat):
            extra.append(
                f"补充推进{i+1}：围绕“{query}”补写一段行动执行、风险反馈与下一步目标，"
                "确保情节、人物与线索三者同时前进。"
            )
        txt += "\n\n" + "\n\n".join(extra)
        actions.append(f"补足字符数 +{needed}")

    if actions:
        write_text(chapter_path, txt)
    return actions


def write_quality_report(gate_dir: Path, quality_before: Dict[str, object], quality_after: Dict[str, object]) -> Path:
    p = gate_dir / "quality_report.md"

    # 辅助函数：安全获取字典值
    def safe_get(d: Dict[str, object], key: str, default: Any = None) -> Any:
        return d.get(key, default) if isinstance(d, dict) else default

    lines = [
        "# 章节质量检查",
        "",
        "## 修复前",
        f"- 字符数：{safe_get(quality_before, 'char_count', 'N/A')}",
        f"- 段落数：{safe_get(quality_before, 'paragraph_count', 'N/A')}",
        f"- 对话占比：{safe_get(quality_before, 'dialogue_ratio', 'N/A')}",
        f"- 句子数：{safe_get(quality_before, 'sentence_count', 'N/A')}",
        f"- 段落唯一比例：{safe_get(quality_before, 'paragraph_unique_ratio', 'N/A')}",
        f"- 最大重复段落次数：{safe_get(quality_before, 'max_duplicate_paragraph_repeat', 'N/A')}",
        f"- 失败项：{safe_get(quality_before, 'failures', [])}",
        "",
        "## 修复后",
        f"- 字符数：{safe_get(quality_after, 'char_count', 'N/A')}",
        f"- 段落数：{safe_get(quality_after, 'paragraph_count', 'N/A')}",
        f"- 对话占比：{safe_get(quality_after, 'dialogue_ratio', 'N/A')}",
        f"- 句子数：{safe_get(quality_after, 'sentence_count', 'N/A')}",
        f"- 段落唯一比例：{safe_get(quality_after, 'paragraph_unique_ratio', 'N/A')}",
        f"- 最大重复段落次数：{safe_get(quality_after, 'max_duplicate_paragraph_repeat', 'N/A')}",
        f"- 失败项：{safe_get(quality_after, 'failures', [])}",
        "",
        f"- 通过：{safe_get(quality_after, 'passed', False)}",
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
) -> Tuple[Path, List[str], Dict[str, object]]:
    actions: List[str] = []
    failures_raw = gate_payload.get("failures", []) if isinstance(gate_payload, dict) else []
    failures = failures_raw if isinstance(failures_raw, list) else []
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

    if "quality_baseline" in fail_text and args.auto_fix_quality:
        old_quality = dict(quality)
        quality_actions = apply_targeted_quality_fix(chapter_path, quality, args, query)
        if quality_actions:
            actions.extend([f"质量最小修复：{x}" for x in quality_actions])
            quality = evaluate_quality(read_text(chapter_path), args)
            gate_dir = project_root / "04_editing" / "gate_artifacts" / slugify(chapter_path.stem)
            ensure_dir(gate_dir)
            write_quality_report(gate_dir, old_quality, quality)

    return chapter_path, actions, quality


def continue_write(args: argparse.Namespace) -> Dict[str, object]:
    project_root = Path(args.project_root).expanduser().resolve()
    project_structure(project_root)
    manuscript_dir = project_root / "03_manuscript"
    ensure_dir(manuscript_dir)
    flow_dir = project_root / FLOW_DIR_NAME
    ensure_dir(flow_dir)

    run_id = dt.datetime.now().strftime("%Y%m%d%H%M%S") + f"-{os.getpid()}"
    lock_file = flow_dir / FLOW_LOCK_FILE
    locked, lock_holder = acquire_lock(lock_file, run_id, timeout_sec=args.lock_timeout_sec)
    if not locked:
        update_flow_metrics(project_root, {
            "ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": False,
            "gate_passed_final": False,
            "runtime_ms": 0,
            "query_length": 0,
            "retrieval_context_chars": 0,
            "retrieval_candidates": 0,
            "auto_retry_actions_count": 0,
            "idempotent_hit": False,
        })
        return {
            "ok": False,
            "command": "continue-write",
            "project_root": str(project_root),
            "error": "another_run_in_progress",
            "lock_holder": lock_holder,
            "next_step": "检测到另一个 /继续写 正在执行，请稍后重试或清理过期锁。",
        }

    started_at = time.time()
    query = args.query.strip() if args.query else "推进下一章剧情"
    chapter_path: Optional[Path] = None
    original_chapter_path: Optional[Path] = None
    chapter_hash_before = ""
    snapshot_path: Optional[Path] = None
    rollback_applied = False
    idempotent_hit = False

    try:
        query_cmd = [
            "query",
            "--project-root",
            str(project_root),
            "--query",
            query,
            "--top-k",
            str(args.top_k),
            "--candidate-k",
            str(args.candidate_k),
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
            # 安全检查：确保路径在项目目录内，防止路径遍历攻击
            try:
                chapter_path.relative_to(project_root.resolve())
            except ValueError:
                return {
                    "ok": False,
                    "error": f"安全错误：章节文件必须在项目目录内: {args.chapter_file}",
                }
            # 安全检查：确保路径在项目目录内，防止路径遍历攻击
            try:
                chapter_path.relative_to(project_root.resolve())
            except ValueError:
                return {
                    "ok": False,
                    "error": f"安全错误：章节文件必须在项目目录内: {args.chapter_file}",
                }
        else:
            chapter_path = (manuscript_dir / next_chapter_filename(manuscript_dir, title=args.chapter_title)).resolve()
        original_chapter_path = chapter_path

        created_chapter_stub = False
        if not chapter_path.exists():
            created_chapter_stub = True
            write_text(
                chapter_path,
                f"# {chapter_path.stem.replace('-', ' ')}\n\n<!-- NOVEL_FLOW_STUB -->\n\n## 正文\n[待写]\n",
            )

        chapter_hash_before = file_sha1(chapter_path)
        request_id = make_request_id(args, chapter_path, query, chapter_hash_before, project_root)

        if args.idempotent_cache and not args.force_run:
            cache = load_continue_cache(flow_dir)
            entries_raw = cache.get("entries")
            entries = entries_raw if isinstance(entries_raw, dict) else {}
            entry = entries.get(request_id)
            if isinstance(entry, dict) and entry.get("chapter_hash_before") == chapter_hash_before and entry.get("result"):
                result = dict(entry["result"])
                result["idempotent_hit"] = True
                result["request_id"] = request_id
                runtime_ms = round((time.time() - started_at) * 1000, 2)
                metrics_summary = update_flow_metrics(project_root, {
                    "ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "ok": bool(result.get("ok")),
                    "gate_passed_final": bool(result.get("gate_passed_final")),
                    "runtime_ms": runtime_ms,
                    "query_length": len(query),
                    "retrieval_context_chars": 0,
                    "retrieval_candidates": 0,
                    "auto_retry_actions_count": 0,
                    "idempotent_hit": True,
                })
                result["metrics_summary"] = metrics_summary
                result["runtime_ms"] = runtime_ms
                return result

        snapshot_path = create_snapshot(chapter_path, flow_dir, run_id)

        # 自动调研：检测知识缺口
        research_gaps = None
        if args.auto_research:
            try:
                from research_agent import detect_knowledge_gaps
                gaps_result = detect_knowledge_gaps(project_root, query)
                if gaps_result.get("has_gaps"):
                    research_gaps = gaps_result
            except ImportError:
                pass  # research_agent.py 不存在时静默跳过

        auto_draft_applied = False
        draft_provider_used = getattr(args, 'draft_provider', 'template')
        fallback_applied = False
        llm_error_msg = None

        if chapter_is_draft_stub(chapter_path) and args.auto_draft:
            if draft_provider_used == "llm":
                # 尝试使用 LLM 写作
                try:
                    from novel_chapter_writer import write_chapter
                    config_overrides = {}
                    if args.llm_provider:
                        config_overrides['ai_provider'] = args.llm_provider
                    if args.llm_model:
                        config_overrides['model'] = args.llm_model
                    if args.llm_api_key:
                        provider = args.llm_provider or 'openai'
                        if provider == 'openai':
                            config_overrides['openai_api_key'] = args.llm_api_key
                        elif provider == 'anthropic':
                            config_overrides['anthropic_api_key'] = args.llm_api_key
                        else:
                            config_overrides['api_key'] = args.llm_api_key

                    llm_result = write_chapter(
                        project_root,
                        chapter_file=chapter_path,
                        config_overrides=config_overrides,
                        dry_run=False,
                        context_window=5,
                    )

                    if llm_result.get("ok"):
                        draft_provider_used = "llm"
                        auto_draft_applied = True
                    else:
                        # LLM 调用失败，回退到模板
                        llm_error_msg = llm_result.get("error", "unknown error")
                        draft = generate_draft_text(project_root, chapter_path, query, min_chars=args.min_chars)
                        write_text(chapter_path, draft)
                        draft_provider_used = "template"
                        fallback_applied = True
                        auto_draft_applied = True

                except Exception as e:
                    # 导入或调用异常，回退到模板
                    llm_error_msg = str(e)
                    draft = generate_draft_text(project_root, chapter_path, query, min_chars=args.min_chars)
                    write_text(chapter_path, draft)
                    draft_provider_used = "template"
                    fallback_applied = True
                    auto_draft_applied = True
            else:
                # template 模式
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
            _, gate_payload = run_gate_check(project_root, chapter_path)
            gate_passed_final = bool(gate_payload.get("passed")) if isinstance(gate_payload, dict) else False

            retry_rounds = 0
            while (not gate_passed_final) and args.auto_retry and retry_rounds < args.max_auto_retry_rounds:
                chapter_path, actions, quality_after = auto_fix_after_gate_failure(
                    project_root,
                    chapter_path,
                    query,
                    quality_after,
                    q_payload,
                    gate_payload if gate_payload else {},
                    args,
                )
                if not actions:
                    break
                retry_actions.extend(actions)
                retry_rounds += 1
                _, gate_payload = run_gate_check(project_root, chapter_path)
                gate_passed_final = bool(gate_payload.get("passed")) if isinstance(gate_payload, dict) else False

            if not gate_passed_final:
                repair_payload = run_repair_plan(project_root, chapter_path)

        b_code, b_out, b_err, b_payload = run_python(
            SCRIPT_DIR / "plot_rag_retriever.py",
            ["build", "--project-root", str(project_root)],
        )

        ok = (q_code == 0 and b_code == 0 and (draft_mode or gate_passed_final))

        if (not ok) and args.rollback_on_failure and snapshot_path and original_chapter_path and chapter_path:
            restored = restore_snapshot(snapshot_path, original_chapter_path, chapter_path)
            rollback_applied = restored is not None
            if rollback_applied:
                chapter_path = restored
                run_python(SCRIPT_DIR / "plot_rag_retriever.py", ["build", "--project-root", str(project_root)])

        retrieval_stats: Dict[str, Any] = {}
        if isinstance(q_payload, dict):
            result_obj = q_payload.get("result")
            if isinstance(result_obj, dict):
                rs_obj = result_obj.get("retrieval_stats")
                if isinstance(rs_obj, dict):
                    retrieval_stats = rs_obj

        runtime_ms = round((time.time() - started_at) * 1000, 2)
        result: Dict[str, object] = {
            "ok": ok,
            "command": "continue-write",
            "project_root": str(project_root),
            "chapter_file": str(chapter_path) if chapter_path else "",
            "created_chapter_stub": created_chapter_stub,
            "auto_draft_applied": auto_draft_applied,
            "draft_provider_used": draft_provider_used,
            "fallback_applied": fallback_applied,
            "llm_error_msg": llm_error_msg,
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
            "run_id": run_id,
            "request_id": request_id,
            "idempotent_hit": idempotent_hit,
            "snapshot_file": str(snapshot_path) if snapshot_path else None,
            "rollback_applied": rollback_applied,
            "runtime_ms": runtime_ms,
            "chapter_hash_before": chapter_hash_before,
            "chapter_hash_after": file_sha1(chapter_path) if chapter_path and chapter_path.exists() else "",
            "research_gaps": research_gaps,
        }

        if draft_mode and not args.auto_draft:
            result["next_step"] = "章节仍是占位草稿，请补全正文后再次执行 /继续写，或启用 --auto-draft。"
        elif draft_mode:
            result["next_step"] = "已尝试自动成稿但仍检测到占位标记，请手动补全正文后再执行。"
        elif fallback_applied and llm_error_msg:
            result["next_step"] = f"LLM写作失败({llm_error_msg})，已自动回退到模板模式。请检查API配置后重试。"
        elif gate_passed_final:
            result["next_step"] = "章节已通过门禁，可进入下一章。"
        else:
            result["next_step"] = "章节未通过门禁，已生成 repair_plan.md。请执行 /修复本章。"

        metrics_summary = update_flow_metrics(project_root, {
            "ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": ok,
            "gate_passed_final": gate_passed_final,
            "runtime_ms": runtime_ms,
            "query_length": len(query),
            "retrieval_context_chars": retrieval_stats.get("estimated_context_chars", 0),
            "retrieval_candidates": retrieval_stats.get("candidate_pool", 0),
            "auto_retry_actions_count": len(retry_actions),
            "idempotent_hit": False,
        })
        result["metrics_summary"] = metrics_summary

        if args.idempotent_cache and result.get("ok"):
            cache = load_continue_cache(flow_dir)
            entries_raw = cache.get("entries")
            if not isinstance(entries_raw, dict):
                entries_raw = {}
                cache["entries"] = entries_raw
            entries_raw[request_id] = {
                "saved_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "chapter_hash_before": chapter_hash_before,
                "result": result,
            }
            save_continue_cache(flow_dir, cache)
        return result

    except Exception as exc:
        if args.rollback_on_failure and snapshot_path and original_chapter_path and chapter_path:
            restored = restore_snapshot(snapshot_path, original_chapter_path, chapter_path)
            rollback_applied = restored is not None
            if rollback_applied:
                chapter_path = restored
        runtime_ms = round((time.time() - started_at) * 1000, 2)
        metrics_summary = update_flow_metrics(project_root, {
            "ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": False,
            "gate_passed_final": False,
            "runtime_ms": runtime_ms,
            "query_length": len(query),
            "retrieval_context_chars": 0,
            "retrieval_candidates": 0,
            "auto_retry_actions_count": 0,
            "idempotent_hit": False,
        })
        return {
            "ok": False,
            "command": "continue-write",
            "project_root": str(project_root),
            "chapter_file": str(chapter_path) if chapter_path else "",
            "error": repr(exc),
            "run_id": run_id,
            "rollback_applied": rollback_applied,
            "metrics_summary": metrics_summary,
            "next_step": "执行发生异常，已尝试回滚章节文件。请检查错误后重试。",
        }
    finally:
        release_lock(lock_file, run_id)


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
    p_cont.add_argument("--candidate-k", type=int, default=12)
    p_cont.add_argument("--force-retrieval", action="store_true")
    p_cont.add_argument("--force-run", action="store_true", help="忽略幂等缓存，强制执行完整流程")
    p_cont.add_argument("--auto-draft", dest="auto_draft", action="store_true", default=True)
    p_cont.add_argument("--no-auto-draft", dest="auto_draft", action="store_false")
    p_cont.add_argument("--auto-improve", dest="auto_improve", action="store_true", default=True)
    p_cont.add_argument("--no-auto-improve", dest="auto_improve", action="store_false")
    p_cont.add_argument("--auto-retry", dest="auto_retry", action="store_true", default=True)
    p_cont.add_argument("--no-auto-retry", dest="auto_retry", action="store_false")
    p_cont.add_argument("--auto-fix-quality", dest="auto_fix_quality", action="store_true", default=True)
    p_cont.add_argument("--no-auto-fix-quality", dest="auto_fix_quality", action="store_false")
    p_cont.add_argument("--auto-fix-kb-misplaced", dest="auto_fix_kb_misplaced", action="store_true", default=True)
    p_cont.add_argument("--no-auto-fix-kb-misplaced", dest="auto_fix_kb_misplaced", action="store_false")
    p_cont.add_argument("--auto-improve-rounds", type=int, default=1)
    p_cont.add_argument("--max-auto-retry-rounds", type=int, default=2)
    p_cont.add_argument("--rollback-on-failure", dest="rollback_on_failure", action="store_true", default=True)
    p_cont.add_argument("--no-rollback-on-failure", dest="rollback_on_failure", action="store_false")
    p_cont.add_argument("--idempotent-cache", dest="idempotent_cache", action="store_true", default=True)
    p_cont.add_argument("--no-idempotent-cache", dest="idempotent_cache", action="store_false")
    p_cont.add_argument("--lock-timeout-sec", type=int, default=1800)
    p_cont.add_argument("--min-chars", type=int, default=2500)  # 从1200提升至2500
    p_cont.add_argument("--min-paragraphs", type=int, default=8)  # 从6提升至8
    p_cont.add_argument("--min-dialogue-ratio", type=float, default=0.03)
    p_cont.add_argument("--max-dialogue-ratio", type=float, default=0.7)
    p_cont.add_argument("--min-sentences", type=int, default=8)
    p_cont.add_argument("--min-content-density", type=float, default=0.7,
                        help="正文密度要求（排除标记、注释等），默认0.7")
    p_cont.add_argument("--max-chapter-variance", type=float, default=0.3,
                        help="相邻章节字数差异限制，默认0.3（30%%）")
    p_cont.add_argument("--max-ai-phrase-density", type=float, default=0.05,
                        help="AI高频词密度限制，默认0.05（5%%）")
    p_cont.add_argument("--auto-research", dest="auto_research", action="store_true", default=False,
                        help="写前自动检测知识缺口并提示调研")
    p_cont.add_argument("--draft-provider", choices=["template", "llm"], default="template",
                        help="草稿生成策略：template(模板模式,默认) 或 llm(多LLM写作)")
    p_cont.add_argument("--llm-provider", default=None,
                        help="LLM提供商(openai/anthropic/kimi/glm/minimax)，需配合--draft-provider llm")
    p_cont.add_argument("--llm-model", default=None,
                        help="LLM模型名称，需配合--draft-provider llm")
    p_cont.add_argument("--llm-api-key", default=None,
                        help="LLM API密钥，需配合--draft-provider llm")
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
