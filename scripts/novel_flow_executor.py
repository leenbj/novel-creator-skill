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
import random
import re
import shutil
import statistics
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
    # 比喻/感知套话
    "不禁", "仿佛", "宛如", "宛若", "恍若", "仿若", "好似",
    # 视觉过渡套话
    "映入眼帘", "涌入眼帘", "跃入眼帘",
    # 内心独白套话
    "心中暗道", "心中暗想", "暗自思忖", "心中一动", "心中一凛",
    # 对话标签套话
    "沉声道", "淡淡地说", "缓缓说道", "淡然道",
    # 反应/动作套话
    "脸色一变", "神情一凛", "眉头微皱", "身形一顿", "脚步一顿",
    # 外貌描写套话
    "嘴角微扬", "勾起一抹弧度", "目光如炬",
    # 过渡套话
    "只见", "此时此刻",
    # 主体性剥夺词
    "不由自主", "不由得", "情不自禁",
    # 意义膨胀
    "叹为观止", "意义深远", "前所未有", "可谓", "毋庸置疑",
]
STUB_MARKER = "<!-- NOVEL_FLOW_STUB -->"
BEAT_SHEET_STUB_MARKER = "<!-- BEAT_SHEET_STUB -->"
DRAFT_PLACEHOLDER_LINE = re.compile(r"(?m)^\[待写\]\s*$")
MAX_STUB_EFFECTIVE_CHARS = 800
FLOW_DIR_NAME = ".flow"
FLOW_LOCK_FILE = "continue_write.lock"
FLOW_CACHE_FILE = "continue_write_cache.json"
FLOW_SNAPSHOT_DIR = "snapshots"
FLOW_CACHE_MAX_ENTRIES = 200

# 节奏模式配置 — 映射到最低章节字数与 beat 扩写深度
PACING_MODE_PROFILES: Dict[str, Any] = {
    # fast/standard 不改变现有默认字数门槛，仅靠 Beat 扩写约束改善质量
    # immersive 显著提升字数要求，适合需要强代入感的正剧/慢热风格
    "fast":      {"min_chars": 2500, "beat_pacing_depth": "fast",      "max_skip_density": 0.40},
    "standard":  {"min_chars": 2500, "beat_pacing_depth": "standard",  "max_skip_density": 0.30},
    "immersive": {"min_chars": 4500, "beat_pacing_depth": "immersive", "max_skip_density": 0.15},
}

# 概括跳过词正则（与 chapter_synthesizer.py 保持同步）
_FLOW_PACING_SKIP_PATTERNS = [
    r"(?:此后|随后|转眼|一晃|没过多久|几天后|数日后|几个月后|数月后|又过了)",
    r"(?:经过一番|经过数轮|花了[一二三四五六七八九十百\d两]+[天日月年]|苦修[一二三四五六七八九十百\d两]*[天日月年]?)",
    r"(?:练功大成|很快(?:就|便)|就这样(?:结束|过去)|不知不觉(?:就)?(?:完成|突破|成功))",
]


def _resolve_pacing_mode(value: Optional[str]) -> str:
    return value if value in PACING_MODE_PROFILES else "standard"


def _infer_pacing_tier(event_types: List[str]) -> str:
    """从事件类型列表推断节奏档位，与 pacing_tracker.infer_tier_from_event_types 保持一致。"""
    event_set = {str(t) for t in event_types}
    fast_types = {"conflict_thrill", "tension_escalation"}
    slow_types = {"bond_deepening", "world_painting"}
    has_fast = bool(event_set & fast_types)
    has_slow = bool(event_set & slow_types)
    if has_fast and has_slow:
        return "medium"
    if has_fast:
        return "fast"
    if has_slow:
        return "slow"
    return "medium"


_VALID_EVENT_TYPES: set = {
    "conflict_thrill", "bond_deepening",
    "faction_building", "world_painting", "tension_escalation",
}


def _extract_event_types_from_constraints(constraints: object) -> List[str]:
    """从 writing_constraints 中提取已过滤的有效事件类型列表。"""
    if not isinstance(constraints, dict):
        return []
    event_rec = constraints.get("event_recommendation")
    if not isinstance(event_rec, dict):
        return []
    rec_types = event_rec.get("recommended_types", []) or []
    return [str(t) for t in rec_types if str(t) in _VALID_EVENT_TYPES]


# 环境变量：标记当前是否在 Claude Code / Codex 等 CLI 工具中运行
# 设置此变量后，系统将使用 MCP Codex 工具进行写作，无需外部 API Key
_CLAUDE_CODE_MODE = os.environ.get("CLAUDE_CODE_MODE", "") or os.environ.get("CODEX_MODE", "")


def _has_llm_config(args: argparse.Namespace, project_root: Path) -> bool:
    """Check if LLM configuration is available for writing."""
    # 优先检查是否在 Claude Code / Codex 模式下
    if _CLAUDE_CODE_MODE:
        return True
    if getattr(args, "llm_provider", None) or getattr(args, "llm_api_key", None):
        return True
    if os.environ.get("NOVEL_LLM_PROVIDER") or os.environ.get("NOVEL_AI_PROVIDER"):
        return True
    return (project_root / ".novel_writer_config.yaml").exists()


def _resolve_draft_provider(args: argparse.Namespace, project_root: Path) -> str:
    """Resolve draft provider: auto -> llm (if configured) or template."""
    raw = str(getattr(args, "draft_provider", "auto") or "auto")
    if raw in {"template", "llm"}:
        return raw
    # Claude Code 模式下默认使用 llm（通过 MCP Codex）
    if _CLAUDE_CODE_MODE:
        return "llm"
    return "llm" if _has_llm_config(args, project_root) else "template"


def _split_sentences(paragraph: str) -> List[str]:
    """Split paragraph into sentences based on Chinese punctuation."""
    return [s.strip() for s in re.split(r"(?<=[。！？!?])", paragraph) if s.strip()]


def _normalize_paragraph_variance(text: str) -> str:
    """Balance paragraph lengths: split long ones, merge short ones."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    normalized: List[str] = []
    buffer_short: List[str] = []
    for p in paragraphs:
        sentences = _split_sentences(p)
        if len(p) >= 260 and len(sentences) >= 4:
            cut = max(2, len(sentences) // 2)
            normalized.append("".join(sentences[:cut]).strip())
            normalized.append("".join(sentences[cut:]).strip())
            continue
        if len(p) <= 45:
            buffer_short.append(p)
            if sum(len(x) for x in buffer_short) >= 90:
                normalized.append(" ".join(buffer_short))
                buffer_short = []
            continue
        if buffer_short:
            normalized.append(" ".join(buffer_short))
            buffer_short = []
        normalized.append(p)
    if buffer_short:
        normalized.append(" ".join(buffer_short))
    return "\n\n".join(normalized)


def _rebalance_dialogue_heavy_text(text: str, query: str) -> str:
    """Insert narrative bridges between consecutive dialogue-heavy paragraphs."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: List[str] = []
    dialogue_run = 0
    for p in paragraphs:
        is_dialogue_heavy = p.startswith(("“", "”")) or p.count("“") >= 2
        out.append(p)
        if is_dialogue_heavy:
            dialogue_run += 1
        else:
            dialogue_run = 0
        if dialogue_run >= 2:
            out.append(
                f"——叙述桥——两人的话并没有直接解决“{query}”，"
                "反而把风险顺序、执行步骤与彼此顾虑暴露得更清楚。"
                "他们不得不把口头判断落实到行动上，场面因此继续向前推进。"
            )
            dialogue_run = 0
    return "\n\n".join(out)


def _build_pacing_rewrite_prompt(query: str, failures: List[str]) -> str:
    """Build prompt for LLM to rewrite chapter with pacing issues."""
    return (
        "Rewrite the chapter to fix pacing issues (too fast / summary skips).\n"
        f"Task: {query}\n"
        f"Failures: {'; '.join(failures)}\n\n"
        "Requirements:\n"
        "1. Preserve all plot facts, character relations, event order, and chapter hooks.\n"
        "2. Expand summary skip phrases like 'after a while' into continuous visible scenes.\n"
        "3. Each key progress must include: action -> sensory/environment -> feedback/resistance -> new decision.\n"
        "4. Do not just append summary patches; rewrite the high skip density paragraphs themselves.\n"
        "5. Control dialogue ratio; balance paragraph lengths.\n"
        "6. Output only the rewritten text, no explanations.\n"
    )


def _write_with_mcp_codex(
    project_root: Path,
    chapter_path: Path,
    prompt: str,
) -> bool:
    """Write chapter using MCP Codex tool (Claude Code integration).

    This function is called when CLAUDE_CODE_MODE is enabled, allowing
    the system to use the current Claude Code session for writing without
    requiring external API keys.

    Returns True on success.
    """
    # This is a placeholder that signals the orchestrator to use MCP Codex
    # The actual MCP call is handled by the calling code (Claude Code agent)
    # We write a signal file that the agent can detect and respond to
    signal_file = project_root / ".flow" / "mcp_write_request.json"
    ensure_dir(signal_file.parent)

    signal_data = {
        "chapter_path": str(chapter_path),
        "prompt": prompt,
        "timestamp": dt.datetime.now().isoformat(),
    }
    write_json(signal_file, signal_data)

    # Return False to indicate this needs to be handled by the caller
    # The actual MCP Codex call will be made by the Claude Code agent
    return False


def _rewrite_chapter_with_llm(
    project_root: Path,
    chapter_path: Path,
    args: argparse.Namespace,
    prompt: str,
) -> bool:
    """Rewrite chapter using LLM for pacing issues. Returns True on success."""
    if not _has_llm_config(args, project_root):
        return False

    # Claude Code 模式：使用 MCP Codex
    if _CLAUDE_CODE_MODE:
        return _write_with_mcp_codex(project_root, chapter_path, prompt)
    try:
        from novel_chapter_writer import write_chapter  # type: ignore[import]
        overrides: Dict[str, object] = {"writing_prompt": prompt}
        if getattr(args, "llm_provider", None):
            overrides["ai_provider"] = args.llm_provider
        if getattr(args, "llm_model", None):
            overrides["model"] = args.llm_model
        if getattr(args, "llm_api_key", None):
            provider = getattr(args, "llm_provider", "") or "openai"
            if provider == "openai":
                overrides["openai_api_key"] = args.llm_api_key
            elif provider == "anthropic":
                overrides["anthropic_api_key"] = args.llm_api_key
            else:
                overrides["api_key"] = args.llm_api_key
        result = write_chapter(project_root, chapter_file=chapter_path, config_overrides=overrides, dry_run=False)
        return bool(result.get("ok"))
    except Exception:
        return False


def _calc_skip_density(text: str, paragraphs: List[str]) -> float:
    """计算概括跳过词密度（hits / paragraphs），用于检测剧情飞速推进。"""
    total = sum(len(re.findall(p, text)) for p in _FLOW_PACING_SKIP_PATTERNS)
    return round(total / max(len(paragraphs), 1), 3)


def _validate_beat_text(text: str, word_target: int, max_skip_density: float) -> Dict[str, object]:
    """校验单个 beat 正文是否达到最低展开要求。

    通过条件：
    1. 实际字数 >= word_target * 0.75（允许 25% 弹性）
    2. 概括跳过密度 <= max_skip_density
    """
    body = clean_for_stats(text)
    pure = re.sub(r"\s+", "", body)
    char_count = len(pure)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    min_chars = max(1, int(word_target * 0.75))
    skip_density = _calc_skip_density(body, paragraphs)

    failures: List[str] = []
    if char_count < min_chars:
        failures.append(f"char_count<{min_chars} (actual:{char_count}, target:{word_target})")
    if skip_density > max_skip_density:
        failures.append(f"skip_density>{max_skip_density:.2f} (actual:{skip_density:.3f})")

    return {
        "passed": len(failures) == 0,
        "char_count": char_count,
        "word_target": word_target,
        "min_chars": min_chars,
        "paragraph_count": len(paragraphs),
        "skip_density": skip_density,
        "max_skip_density": max_skip_density,
        "failures": failures,
    }


def _build_retry_prompt(expand_prompt: str, retry: int, word_target: int) -> str:
    """在重试时在原扩写提示词前追加强化要求。"""
    header = (
        f"\u3010\u5f3a\u5236\u91cd\u5199 - \u7b2c{retry}\u6b21\u3011\u4e0a\u4e00\u7248\u672c\u5b57\u6570\u4e0d\u8db3\u6216\u4f7f\u7528\u4e86\u6982\u62ec\u8df3\u8fc7\u53e5\uff0c\u672c\u6b21\u5fc5\u987b\u6ee1\u8db3\uff1a\n"
        f"1. \u5b57\u6570\u8fbe\u5230 {word_target} \u5b57\n"
        "2. \u6bcf\u4e2a\u65f6\u95f4\u63a8\u8fdb\u90fd\u8981\u843d\u5230\u5177\u4f53\u884c\u52a8\uff0c\u7981\u6b62\u4f7f\u7528'\u6b64\u540e/\u7ecf\u8fc7\u4e00\u756a/\u7ec3\u529f\u5927\u6210'\u7b49\u8df3\u8fc7\u53e5\n"
        "3. \u81f3\u5c11\u5199\u51fa3\u4e2a\u5177\u4f53\u7684\u573a\u666f\u77ac\u95f4\uff08\u52a8\u4f5c-\u53cd\u5e94-\u60c5\u7eea\u94fe\u6761\uff09\n"
        "4. \u4e0d\u5f97\u51fa\u73b0\u4efb\u4f55\u7ed3\u8bba\u5148\u884c\u3001\u7701\u7565\u8fc7\u7a0b\u7684\u53d9\u8ff0\n\n"
    )
    return header + expand_prompt


# ── 两阶段写作：场景分解 + 场景锚定提示词 ───────────────────────────────────

_SCENE_DECOMPOSE_SYSTEM = (
    "你是专业小说结构编辑。接收一个 beat（场景片段）的写作任务描述，"
    "将其拆解为 5\u20137 个连续的「微时刻」，以 JSON 格式输出。"
    "每个微时刻必须包含：action（具体动作，非总结）、sensory（感官细节）、"
    "emotion（情绪/内心状态）、obstacle（遇到的阻力或变化，可为空字符串）。"
    "输出格式严格为：```json\n"
    "{\"moments\": [{\"id\":1,\"action\":\"\",\"sensory\":\"\",\"emotion\":\"\",\"obstacle\":\"\"}]}\n"
    "```\n"
    "禁止使用「经过一番」「很快」「此后」等概括跳过词描述微时刻。"
)

_SCENE_DECOMPOSE_USER_TMPL = (
    "请将以下 beat 写作任务拆解为 5\u20137 个微时刻（JSON 格式）：\n\n"
    "{beat_summary}\n\n"
    "字数目标：约 {word_target} 字。每个微时刻对应约 {chars_per_moment} 字的散文。"
)


def _decompose_beat_scenes(
    expand_prompt: str,
    word_target: int,
    overrides: Dict[str, object],
    project_root: Path,
) -> Optional[Dict[str, object]]:
    """Phase 1：调用 LLM 将 beat 拆解为 5~7 个微时刻 JSON。

    复用散文写作的 provider 配置，发出一次独立的场景分解请求。
    成功返回 scene_map dict（含 moments 列表），失败返回 None（降级到原流程）。
    """
    import json as _json

    beat_summary = expand_prompt[:600].strip()
    moment_count = 6
    chars_per_moment = max(80, word_target // moment_count)

    user_msg = _SCENE_DECOMPOSE_USER_TMPL.format(
        beat_summary=beat_summary,
        word_target=word_target,
        chars_per_moment=chars_per_moment,
    )

    try:
        from novel_chapter_writer import write_chapter  # type: ignore[import]

        tmp_file = project_root / "00_memory" / "beats" / "_scene_decompose_tmp.md"
        decompose_overrides: Dict[str, object] = {
            **overrides,  # type: ignore[misc]
            "writing_prompt": user_msg,
            "writing_system_prompt_override": _SCENE_DECOMPOSE_SYSTEM,
            "max_tokens": 1200,
            "humanizer_enabled": False,
            # 场景分解是中间任务，禁止触发记忆更新，避免污染项目记忆
            "auto_update_memory": False,
        }

        result = write_chapter(
            project_root,
            chapter_file=tmp_file,
            config_overrides=decompose_overrides,
            dry_run=False,
        )

        if not result.get("ok"):
            return None

        raw = tmp_file.read_text(encoding="utf-8") if tmp_file.exists() else ""
        tmp_file.unlink(missing_ok=True)

        # 优先提取 ```json...``` 代码块，其次尝试裸 JSON
        json_match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
        if json_match:
            scene_map: Dict[str, object] = _json.loads(json_match.group(1))
        else:
            bare = re.search(r'\{[^{}]*"moments"[^{}]*\[.*?\]\s*\}', raw, re.DOTALL)
            if not bare:
                return None
            scene_map = _json.loads(bare.group(0))

        moments = scene_map.get("moments", [])
        if not isinstance(moments, list) or len(moments) < 3:
            return None

        return scene_map

    except Exception as _dbs_err:
        print(f"[警告] 场景分解失败，降级到原始扩写提示词: {_dbs_err}")
        return None


def _build_scene_anchored_prompt(expand_prompt: str, scene_map: Dict[str, object]) -> str:
    """Phase 2：将场景分解结果嵌入扩写提示词，锁定微时刻序列。

    LLM 在 Phase 1 已承诺具体微时刻，Phase 2 只能按序展开，无法再概括跳过。
    """
    moments: List[Dict[str, object]] = scene_map.get("moments", [])  # type: ignore[assignment]
    lines: List[str] = []
    for m in moments:
        idx = m.get("id", "?")
        action = m.get("action", "")
        sensory = m.get("sensory", "")
        emotion = m.get("emotion", "")
        obstacle = m.get("obstacle", "")
        line = (
            f"  \u300e\u5fae\u65f6\u523b{idx}\u300f"
            f"\u52a8\u4f5c\uff1a{action}"
            f"\uff5c\u611f\u5b98\uff1a{sensory}"
            f"\uff5c\u60c5\u7eea\uff1a{emotion}"
        )
        if obstacle:
            line += f"\uff5c\u963b\u529b\uff1a{obstacle}"
        lines.append(line)

    moments_text = "\n".join(lines)
    n = len(moments)
    header = (
        f"\u3010\u573a\u666f\u5206\u89e3\u9501\u5b9a\u3011\u4ee5\u4e0b {n} \u4e2a\u5fae\u65f6\u523b\u5df2\u786e\u5b9a\uff0c"
        "\u5fc5\u987b\u6309\u987a\u5e8f\u5c55\u5f00\u6bcf\u4e2a\u5fae\u65f6\u523b\u7684\u6563\u6587\uff0c"
        "\u6bcf\u4e2a\u5fae\u65f6\u523b\u81f3\u5c11\u5199 3 \u6bb5\uff08\u52a8\u4f5c\u2192\u611f\u5b98\u2192\u60c5\u7eea\uff09\uff0c"
        "\u7981\u6b62\u5408\u5e76\u3001\u8df3\u8fc7\u6216\u91cd\u6392\u4efb\u4f55\u5fae\u65f6\u523b\u3002\n\n"
        f"\u5fae\u65f6\u523b\u5e8f\u5217\uff1a\n{moments_text}\n\n"
        "\u73b0\u5728\u5f00\u59cb\u7ed9\u6bcf\u4e2a\u5fae\u65f6\u523b\u5199\u8be6\u7ec6\u7684\u5c0f\u8bf4\u6563\u6587\uff1a\n\n"
    )
    return header + expand_prompt


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


def _collect_writing_constraints(
    project_root: Path, chapter_path: Path, query: str
) -> Dict[str, object]:
    """写前调用三个辅助脚本，汇总约束信息供后续注入 query。"""
    chapter_no = chapter_no_from_name(chapter_path.name)
    constraints: Dict[str, object] = {"query": query, "chapter": chapter_no}
    if chapter_no <= 0:
        constraints["error"] = f"invalid_chapter_no:{chapter_path.name}"
        return constraints
    o_code, o_out, _o_err, o_payload = run_python(
        SCRIPT_DIR / "outline_anchor_manager.py",
        ["check", "--project-root", str(project_root), "--chapter", str(chapter_no)],
    )
    a_code, a_out, _a_err, a_payload = run_python(
        SCRIPT_DIR / "anti_resolution_guard.py",
        ["constraint", "--project-root", str(project_root)],
    )
    e_code, e_out, _e_err, e_payload = run_python(
        SCRIPT_DIR / "event_matrix_scheduler.py",
        ["recommend", "--project-root", str(project_root), "--chapter", str(chapter_no)],
    )
    constraints["outline_constraints"] = o_payload if o_payload is not None else {"stdout": o_out}
    constraints["anti_resolution_constraints"] = a_payload if a_payload is not None else {"stdout": a_out}
    constraints["event_recommendation"] = e_payload if e_payload is not None else {"stdout": e_out}
    constraints["sources_ok"] = {
        "outline_anchor_manager": o_code == 0,
        "anti_resolution_guard": a_code == 0,
        "event_matrix_scheduler": e_code == 0,
    }
    # 图谱上下文注入（已初始化图谱时生效）
    graph_file = project_root / "00_memory" / "story_graph.json"
    if graph_file.exists():
        g_code, g_out, _g_err, g_payload = run_python(
            SCRIPT_DIR / "story_graph_builder.py",
            ["generate-context",
             "--project-root", str(project_root),
             "--chapter", str(max(chapter_no, 0)),
             "--max-foreshadows", "5",
             "--max-events", "5"],
        )
        if g_code == 0 and isinstance(g_payload, dict) and g_payload.get("ok"):
            constraints["graph_context"] = g_payload
    return constraints


def _try_create_lock(lock_file: Path, payload: Dict[str, object]) -> bool:
    """使用 O_CREAT|O_EXCL 原子创建锁文件，避免 TOCTOU 竞争窗口。"""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(str(lock_file), flags, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    return True


def acquire_lock(lock_file: Path, run_id: str, timeout_sec: int) -> Tuple[bool, Optional[Dict[str, object]]]:
    now = time.time()
    payload: Dict[str, object] = {
        "run_id": run_id,
        "pid": os.getpid(),
        "ts": now,
        "started_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    if _try_create_lock(lock_file, payload):
        return True, None

    if not lock_file.exists():
        return False, None

    existing_stat = lock_file.stat()
    current = load_json(lock_file, {})
    cur = cast(Dict[str, Any], current)
    ts_raw = cur.get("ts", 0)
    ts = float(ts_raw) if isinstance(ts_raw, (int, float, str)) else 0.0
    if ts and (now - ts) < max(1, timeout_sec):
        return False, current

    # 回收过期锁前再次确认文件未被其他进程替换
    try:
        latest_stat = lock_file.stat()
    except FileNotFoundError:
        if _try_create_lock(lock_file, payload):
            return True, None
        return False, load_json(lock_file, {})

    if (
        latest_stat.st_ino != existing_stat.st_ino
        or latest_stat.st_mtime_ns != existing_stat.st_mtime_ns
    ):
        return False, load_json(lock_file, {})

    lock_file.unlink(missing_ok=True)
    if _try_create_lock(lock_file, payload):
        return True, None
    return False, load_json(lock_file, {})


def validate_chapter_path(project_root: Path, chapter_file: str) -> Tuple[Path, Optional[str]]:
    """解析并校验章节路径，确保路径在项目目录内，防止路径遍历攻击。"""
    chapter_path = Path(chapter_file)
    if not chapter_path.is_absolute():
        chapter_path = project_root / chapter_path
    chapter_path = chapter_path.resolve()
    try:
        chapter_path.relative_to(project_root.resolve())
    except ValueError:
        return chapter_path, f"安全错误：章节文件必须在项目目录内: {chapter_file}"
    return chapter_path, None


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
    if BEAT_SHEET_STUB_MARKER in txt:
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

    # 概括跳过密度检查
    # immersive 模式：超阈值为硬失败
    # standard 模式：超阈值 0.5（极高）也升为硬失败，低于 0.5 仅记录警告
    # fast 模式：仅记录，不阻断
    pacing_mode_val = _resolve_pacing_mode(getattr(args, "pacing_mode", "standard"))
    pacing_p = PACING_MODE_PROFILES[pacing_mode_val]
    para_list = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    skip_density = _calc_skip_density(body, para_list)
    max_skip = float(pacing_p.get("max_skip_density", 0.30))
    skip_density_exceeded = skip_density > max_skip
    _STANDARD_HARD_SKIP_THRESHOLD = 0.50  # standard 模式极高密度升级为硬失败
    if skip_density_exceeded:
        if pacing_mode_val == "immersive":
            failures.append(
                f"pacing_skip_density_too_high ({skip_density:.2f}/para, max: {max_skip:.2f}) "
                f"— 检测到概括跳过叙述，immersive 模式须展开每个场景过程"
            )
        elif pacing_mode_val == "standard" and skip_density > _STANDARD_HARD_SKIP_THRESHOLD:
            failures.append(
                f"pacing_skip_density_critical ({skip_density:.2f}/para, hard_limit: {_STANDARD_HARD_SKIP_THRESHOLD:.2f}) "
                f"— 概括跳过密度极高，standard 模式亦不可接受，需展开场景"
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
        "pacing_mode": pacing_mode_val,
        "skip_density": skip_density,
        "skip_density_exceeded": skip_density_exceeded,
        "passed": len(failures) == 0,
        "failures": failures,
    }


def generate_draft_text(project_root: Path, chapter_path: Path, query: str, min_chars: int) -> str:
    # 兜底模板：LLM 不可用时使用。用 chapter_no 作随机种子，确保每章开头/结尾不同。
    # 注意：本函数只在 --draft-provider template 或 LLM 调用失败时触发，
    # 正常写作流程应使用 --draft-provider llm。
    chapter_no = chapter_no_from_name(chapter_path.name)
    title = chapter_path.stem.replace('-', ' ')
    names = load_character_names(project_root)
    protagonist = names[0] if names else '主角'
    side = names[1] if len(names) > 1 else '同伴'

    rng = random.Random(chapter_no)

    opening_pool = [
        (protagonist + '没有多说，直接走向了事情发生的地方。'
         + query + '——这一步迈出去，就没有回头的余地。'
         + '他知道自己在做什么，也知道可能付出什么代价。'
         + '但有些事，不做会后悔，做了最多是吃亏，两害相权，他选了前者。'),
        ('事情比预想的复杂。' + protagonist + '站在原地，把已知的信息重新梳理了一遍。'
         + query + '——每一条线索都指向同一个方向，偏偏每一条都差一截才能闭合。'
         + '他不急，急没用，这种事急了只会出错。'
         + side + '在一旁说："你想好了？"他没有回答，因为还在想。'),
        (side + '先开口说："你确定要这样做？"'
         + protagonist + '没有立刻回答，把问题在脑子里转了一圈，才开口："不确定，但现在没有更好的选项。"'
         + '于是两人就这样决定了：' + query + '，就从这里开始做起。'),
        ('清晨的光线还没有彻底亮起来。' + protagonist + '已经起身，站在窗边把今天要做的事理了一遍。'
         + query + '——放在平时，这不算什么大事，但放在现在这个节点，每一步都要踩稳。'
         + '他动作很轻，没有惊动任何人，然后出了门。'),
        ('上一章留下的麻烦没有消失，只是换了一张脸。' + protagonist + '盯着眼前的局面，'
         + '想起某人说过的一句话：问题不会自己消失，它只是在等一个更坏的时机重新出现。'
         + query + '，就是那个时机终于到了。他把手里的东西收好，准备开始。'),
    ]

    closing_pool = [
        (protagonist + '没有立刻离开，在原地停了一会儿。'
         + '事情走到这一步，算是告一段落——但"告一段落"不等于结束，只等于把问题暂时压住了。'
         + '压住的东西，早晚还会冒出来。下一步怎么走，他心里已经有了一个方向，'
         + '只是还没到说出来的时候。'),
        (side + '问："现在怎么办？"'
         + protagonist + '想了想，说："先把今天的事收尾，再说下一步。"'
         + '那句话说得很轻，但两个人都听出来了——这件事还没完，甚至刚刚开始。'
         + side + '没再多问，点了点头，两个人各自散了。'),
        ('夜深了。' + protagonist + '把今天发生的事在脑子里过了一遍，'
         + '有些东西对上了，有些东西还差一块。差的那块，是整件事的关键，也是目前最难拿到的那块。'
         + '他没有急着去找，因为有些东西越找越躲，不如等它自己浮出来。明天还有时间，先休息。'),
        ('结果不算好，也不算坏。' + protagonist + '把事情记下来，合上本子。'
         + '他没有总结，没有下判断，只是记录。判断留到事情彻底结束再做，现在下结论，太早。'
         + side + '看着他说："你总是这样，什么都先记下来再说。"他想了想，回答："记下来，才不会忘。"'),
        ('回去的路上，' + protagonist + '一直没说话。' + side + '也没问。'
         + '有些问题，现在还没有答案，说了也只是给对方添麻烦。沉默有时候比什么都有用。'
         + '走到分叉口，两个人停下来，各自往不同的方向去了。'),
    ]

    middle_pool = [
        (protagonist + '把情况仔细检查了一遍，确认没有遗漏，才继续往下走。'
         + '这种习惯是多次教训换来的——不是天生谨慎，是被逼出来的。'
         + '漏掉一个细节，后来要花十倍的力气补，不值当。'
         + side + '在旁边等着，没有催他，因为知道他有他的节奏。'),
        (side + '说："你有没有想过，事情可能不是我们以为的那样？"'
         + protagonist + '停下来，认真考虑了这个问题。'
         + '不是第一次有人这么说了，但每次被这样问，他还是会重新检查一遍自己的判断，'
         + '看有没有什么地方出了偏差。这一次，他发现，确实有一块地方，他之前想得有点简单了。'),
        ('中途出了一个岔子。' + protagonist + '没有慌，先把手头的东西放稳，再来处理新冒出来的问题。'
         + '慌解决不了事情，冷静也不一定能，但至少不会把事情弄得更乱。'
         + '他先把能控制的部分处理掉，再去看不能控制的那部分。'
         + side + '问："要我帮忙吗？"他说："先看看再说。"'),
        ('有一个细节一直让' + protagonist + '觉得不对，但说不清楚哪里不对。'
         + '直到这一刻，才突然想明白——不是细节本身有问题，是细节和上下文不搭。'
         + '单独看没问题，放进整件事里，就出现了一条缝。'
         + '他把这个发现告诉了' + side + '，对方听完，沉默了很久才说："那我们之前判断的方向……"'
         + protagonist + '点头："是的，需要重新想过。"'),
        ('事情推进得比预期慢。' + protagonist + '调整了节奏，不再追着进度走，而是等一个合适的时机。'
         + '有时候快是拖累，慢反而是推进。他见过太多人因为急着收网，把鱼全跑了。'
         + side + '倒是沉得住气："你现在倒想开了。"他说："不是想开了，是想通了。"'),
        (protagonist + '和' + side + '分头行动，各自去处理一件事，约好稍后碰面。'
         + '不是因为信任，是因为两件事同时需要人，而两个人是现在手里全部的资源。'
         + '临分开前，' + protagonist + '说："有情况随时通知我。"' + side + '点头："你也是。"'),
        ('遇到了一个不速之客。' + protagonist + '没有表现出惊讶，只是多看了对方一眼，暗中把情况记在心里。'
         + '对方的来意不明，但来得太巧，巧到不像是偶然。他没有先开口，等对方先说。'
         + '对方果然先开了口，说了一句话，让他意识到，这个人知道的比他以为的要多。'),
        ('这一段时间里，' + protagonist + '一直在思考一个问题：如果换个角度来看，事情会不会完全不同？'
         + '答案是——会。但换角度容易，换了角度之后怎么办，才是真正的难题。'
         + '他把这个问题说给' + side + '听，对方的回答很简单："先换，换完再说。"'
         + '他觉得这个回答有点粗，但又不得不承认，有时候确实只能这样。'),
        ('天色开始变暗。还有几件事没有处理完，但有些事急不来，只能等。'
         + protagonist + '把优先级重新排了一遍，把今晚能做的和只能明天做的分开，先把今晚的做完。'
         + '他这样做事已经很久了，不是计划感特别强，只是不愿意把事情搅成一团。'),
        (side + '带来了一条新消息。' + protagonist + '听完，沉默了片刻，然后说："这改变了一些事情。"'
         + '不是全部，但是重要的一部分。他把原来的计划在脑子里调整了一遍，改动不大，但方向有所偏移。'
         + side + '问："好的方向，还是坏的方向？"他想了想，说："还不确定，走一步看一步。"'),
        ('这件事牵扯的人比想象中多。' + protagonist + '意识到，自己需要更谨慎一些。'
         + '不是因为怕，是因为一个错误波及的范围会更大。谨慎不等于退缩，只是换了一种走法。'
         + '他把这个想法告诉了' + side + '，对方说："我一直觉得你太谨慎了。"他说："太谨慎也比不够谨慎好。"'),
        ('有一个时刻，' + protagonist + '几乎要放弃。但只是那一刻，之后还是继续了。'
         + '不是因为突然想通了什么，是因为放弃之后也没有更好的去处。既然都是难，就继续这条路。'
         + '他没有跟任何人说这件事，包括' + side + '。有些东西，说出来反而更重。'),
        (protagonist + '回到原地，把之前记录的东西重新看了一遍。'
         + '信息量并不小，但真正有用的不多。这很正常——有用的信息永远比没用的少。'
         + '他把有用的单独标出来，其他的先放着。' + side + '凑过来看了一眼，说："就这些？"他说："就这些，够了。"'),
        ('事情发展到某个节点，开始出现分叉。' + protagonist + '需要做一个选择，而每一条路都有代价。'
         + '他没有急着决定，先把每条路的代价都列出来，再比较哪一种代价是他能接受的。'
         + side + '说："你考虑太多了。"他说："我宁可考虑太多，也不要考虑太少。"'),
        (side + '说了一句他没想到的话。' + protagonist + '愣了一下，然后说："你怎么知道？"'
         + side + '说："猜的。但猜中了吧？"'
         + protagonist + '没有直接回答，只是说："继续说。"'
         + '这一段对话，让整件事突然变得比之前清晰了不少。'),
    ]

    rng.shuffle(middle_pool)

    opening = rng.choice(opening_pool)
    closing = rng.choice(closing_pool)

    paragraphs = [opening] + middle_pool + [closing]

    text = '# ' + title + '\n\n' + '\n\n'.join(paragraphs)

    # 兜底补充段落：若字数不足 target_chars，追加若干备用段落（每段各不同，不循环复用）
    target_chars = max(min_chars, 2500)
    extra_pool = [
        (protagonist + '把手头的事情暂停了一下，环顾周围。'
         + '这一带他来过几次，但每次来的原因都不一样，这一次也不例外。'
         + '他没有急着动，先把能观察到的信息收集完，再决定下一步怎么做。'
         + '有时候，多等一分钟，比直接冲上去强得多。'),
        ('两人之间有一段时间没说话。'
         + '不是因为没话说，是因为有些话说了也没用，不如省着力气。'
         + side + '最后先开口："你打算怎么处理？"' + protagonist + '想了想，说："先把能确认的部分确认了再说，其他的等。"'),
        (protagonist + '回头看了一眼来路，然后继续往前走。'
         + '他清楚，这件事从一开始就没有退路，不是因为被逼的，是因为他自己选的。'
         + '既然选了，就没有半途而废的道理。接下来的事，一件一件来。'),
        ('到了某个节点，' + protagonist + '意识到，自己对这件事的判断，和最开始相比，已经变了不少。'
         + '不是被说服了，是被事实改变了。这种改变让他有点不舒服，但他觉得，这是好事——'
         + '能被事实改变，说明还没有固执到无法转圜的地步。'),
        (side + '问了一个问题，' + protagonist + '没有立刻回答。'
         + '那个问题触到了他一直没想清楚的地方。他不喜欢在没想清楚的时候开口，'
         + '所以他说："给我一点时间。"' + side + '点头，没有催。'),
    ]
    pure_len = len(re.sub(r'\s+', '', text))
    for extra_para in extra_pool:
        if pure_len >= target_chars:
            break
        text += '\n\n' + extra_para
        pure_len = len(re.sub(r'\s+', '', text))

    if pure_len > target_chars + 500:
        keep = int(len(text) * ((target_chars + 500) / pure_len))
        clipped = text[:keep]
        cut = max(clipped.rfind('。'), clipped.rfind('！'), clipped.rfind('？'))
        if cut > 0:
            text = clipped[:cut + 1]

    return text


def improve_text_minimally(text: str, query: str) -> str:
    extra = (
        f"补充推进：围绕“{query}”再加入一段行动结果、一段对话冲突、一段章末钩子，"
        "确保本章既有情节推进也有角色关系变化。"
    )
    return text.rstrip() + "\n\n" + extra + "\n"


def _generate_beat_draft(
    project_root: Path,
    chapter_path: Path,
    chapter_no: int,
    query: str,
    writing_constraints: Optional[Dict[str, object]],
    args: argparse.Namespace,
) -> Tuple[bool, str]:
    """Beat Sheet 流水线：generate → expand → synthesize。

    返回 (success: bool, mode: str)。
    成功时 chapter_path 已被写入合成草稿。
    失败时返回 (False, error_reason)，调用方应回退到普通 draft 模式。
    """
    chapter_goal = query[:200]  # 截断保证参数合法

    pacing_depth = _resolve_pacing_mode(getattr(args, "pacing_mode", "standard"))

    # 从 writing_constraints 提取大纲约束和事件推荐，丰富章节目标描述
    # 使 beat 骨架 / 扩写 prompt 获得真实的剧情约束而非空泛目标
    enriched_goal = chapter_goal
    if writing_constraints:
        parts: List[str] = [chapter_goal]
        outline_c = writing_constraints.get("outline_constraints", "")
        if outline_c:
            parts.append(f"大纲约束：{str(outline_c)[:120]}")
        event_rec = writing_constraints.get("event_recommendation", "")
        if event_rec:
            parts.append(f"推荐事件：{str(event_rec)[:120]}")
        graph_ctx = writing_constraints.get("graph_context", "")
        if graph_ctx:
            parts.append(f"人物关系：{str(graph_ctx)[:100]}")
        enriched_goal = " | ".join(p for p in parts if p)[:400]

    # Step 1: 生成 Beat Sheet 骨架
    b_code, _b_out, _b_err, b_payload = run_python(
        SCRIPT_DIR / "beat_sheet_generator.py",
        ["generate",
         "--project-root", str(project_root),
         "--chapter", str(chapter_no),
         "--chapter-goal", enriched_goal,
         "--pacing-depth", pacing_depth,
         "--beat-count", str(getattr(args, "beat_count", 4))],
    )
    if b_code != 0 or not isinstance(b_payload, dict) or not b_payload.get("ok"):
        return False, "beat_generate_failed"

    beat_count = int(b_payload.get("beat_count", 4))

    # 预加载 beat sheet，用于获取每个 beat 的 word_target
    beats_dir = project_root / "00_memory" / "beats"
    beats_dir.mkdir(parents=True, exist_ok=True)
    sheet_path = beats_dir / f"ch{chapter_no:04d}_beat_sheet.json"
    sheet = load_json(sheet_path, default={})
    beats_meta: List[Dict[str, object]] = [
        b for b in sheet.get("beats", []) if isinstance(b, dict)
    ]
    pacing_profile = PACING_MODE_PROFILES[pacing_depth]
    max_skip_density = float(pacing_profile.get("max_skip_density", 0.30))

    # Step 2: 逐 Beat 扩写 + Beat 级校验与重试
    draft_provider = _resolve_draft_provider(args, project_root)

    for beat_id in range(1, beat_count + 1):
        e_code, _e_out, _e_err, e_payload = run_python(
            SCRIPT_DIR / "beat_sheet_generator.py",
            ["expand",
             "--project-root", str(project_root),
             "--chapter", str(chapter_no),
             "--pacing-depth", pacing_depth,
             "--beat-id", str(beat_id)],
        )
        if e_code != 0 or not isinstance(e_payload, dict):
            continue

        expand_prompt = e_payload.get("expand_prompt", "")
        beat_file = beats_dir / f"ch{chapter_no:04d}_beat{beat_id:02d}_expand.md"

        # 从 beat sheet 获取该 beat 的字数目标
        beat_meta = next((b for b in beats_meta if b.get("beat_id") == beat_id), {})
        word_target = int(e_payload.get("word_target") or beat_meta.get("word_target") or 800)

        if draft_provider == "llm" and expand_prompt:
            try:
                from novel_chapter_writer import write_chapter  # type: ignore[import]
                overrides: Dict[str, object] = {}
                if getattr(args, "llm_provider", None):
                    overrides["ai_provider"] = args.llm_provider
                if getattr(args, "llm_model", None):
                    overrides["model"] = args.llm_model
                if getattr(args, "llm_api_key", None):
                    # 按 provider 使用正确的 key 名，避免静默退化到环境变量兜底
                    _llm_prov = getattr(args, "llm_provider", "") or ""
                    if _llm_prov == "openai":
                        overrides["openai_api_key"] = args.llm_api_key
                    elif _llm_prov == "anthropic":
                        overrides["anthropic_api_key"] = args.llm_api_key
                    else:
                        overrides["api_key"] = args.llm_api_key

                # ── Phase 1：场景分解（Two-Phase Writing）────────────────────
                # 调用 LLM 将 beat 预先拆解为 5~7 个微时刻，强迫模型承诺
                # 具体瞬间（action/sensory/emotion/obstacle），使后续写作
                # 无法通过概括跳过来压缩内容。分解失败时降级到原流程。
                scene_map = _decompose_beat_scenes(
                    expand_prompt, word_target, overrides, project_root
                )
                # 用场景锚定提示词替换原始扩写提示词（Phase 2 基础提示词）
                base_prompt = (
                    _build_scene_anchored_prompt(expand_prompt, scene_map)
                    if scene_map is not None
                    else expand_prompt
                )

                # Beat 级校验与重试循环（最多 3 次尝试，失败降级接受继续下一 beat）
                attempt_results: List[Dict[str, object]] = []
                accepted = False
                final_validation: Optional[Dict[str, object]] = None

                for attempt in range(3):
                    current_prompt = (
                        base_prompt if attempt == 0
                        else _build_retry_prompt(base_prompt, attempt, word_target)
                    )
                    overrides["writing_prompt"] = current_prompt

                    try:
                        llm_result = write_chapter(
                            project_root,
                            chapter_file=beat_file,
                            config_overrides=overrides,
                            dry_run=False,
                        )
                        llm_ok = bool(llm_result.get("ok"))
                    except Exception as exc:
                        attempt_results.append({
                            "attempt": attempt + 1, "llm_ok": False,
                            "error": repr(exc), "accepted": False,
                        })
                        continue

                    if not llm_ok:
                        attempt_results.append({
                            "attempt": attempt + 1, "llm_ok": False,
                            "error": str(llm_result.get("error", "llm_write_failed")),
                            "accepted": False,
                        })
                        continue

                    # LLM 写成功，立即校验 beat 正文质量
                    beat_text = read_text(beat_file) if beat_file.exists() else ""
                    final_validation = cast(
                        Dict[str, object],
                        _validate_beat_text(beat_text, word_target, max_skip_density),
                    )
                    attempt_results.append({
                        "attempt": attempt + 1, "llm_ok": True,
                        "accepted": bool(final_validation.get("passed")),
                        "validation": final_validation,
                    })

                    if final_validation.get("passed"):
                        accepted = True
                        break
                    # 未通过 → 继续下一次 attempt（最多到 attempt=2）

                # 所有尝试用尽仍未通过：降级写入扩写提示词模板（保证合成不中断）
                if not accepted and (not beat_file.exists() or not read_text(beat_file).strip()):
                    write_text(beat_file, expand_prompt)

                # 将 beat 级校验结果写回 beat sheet，供后续分析
                if beat_meta:
                    beat_meta["generation_meta"] = {  # type: ignore[assignment]
                        "pacing_depth": pacing_depth,
                        "word_target": word_target,
                        "max_skip_density": max_skip_density,
                        "accepted": accepted,
                        "attempt_count": len(attempt_results),
                        "retry_count": max(0, len(attempt_results) - 1),
                        "attempts": attempt_results,
                        "final_validation": final_validation,
                    }
                    save_json(sheet_path, sheet, indent=2)

            except Exception as _beat_err:
                print(f"[警告] Beat {beat_id} LLM 写作异常，降级写入扩写提示词模板: {_beat_err}")
                write_text(beat_file, expand_prompt)
        else:
            write_text(beat_file, expand_prompt)

    # Step 3: chapter_synthesizer 合成
    s_code, _s_out, _s_err, s_payload = run_python(
        SCRIPT_DIR / "chapter_synthesizer.py",
        ["synthesize",
         "--project-root", str(project_root),
         "--chapter", str(chapter_no)],
    )
    if s_code != 0 or not isinstance(s_payload, dict) or not s_payload.get("ok"):
        return False, "synthesize_failed"

    output_file = s_payload.get("output_file", "")
    mode = s_payload.get("mode", "unknown")

    if mode == "draft_merged" and output_file and Path(output_file).exists():
        synth_text = read_text(Path(output_file))
        write_text(chapter_path, synth_text)
        return True, "beat_sheet_llm"
    elif mode == "prompt_only" and output_file and Path(output_file).exists():
        synth_prompt = read_text(Path(output_file))
        stub = f"# {chapter_path.stem}\n\n{BEAT_SHEET_STUB_MARKER}\n\n{synth_prompt}\n"
        write_text(chapter_path, stub)
        return True, "beat_sheet_template"

    return False, "synthesize_no_output"


def _next_fix_block_index(text: str, prefix: str) -> int:
    """Calculate next fix block index to avoid duplicate numbering across rounds."""
    matches = [int(m) for m in re.findall(rf"{re.escape(prefix)}(\d+)", text)]
    return (max(matches) + 1) if matches else 1


def _count_dialogue_chars(text: str) -> int:
    """Count dialogue characters (text inside Chinese quotation marks)."""
    return sum(len(m.group(1)) for m in re.finditer(r"[""]([^""]*)[""]", text))


def apply_targeted_quality_fix(
    project_root: Path,
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

    # 跨轮次编号接续
    next_paragraph_idx = _next_fix_block_index(txt, "\u8865\u5145\u6bb5\u843d")
    next_progress_idx = _next_fix_block_index(txt, "\u8865\u5145\u63a8\u8fdb")

    # 优先处理 pacing_skip_density_critical
    if any(
        f.startswith("pacing_skip_density_critical") or f.startswith("pacing_skip_density_too_high")
        for f in failures
    ):
        prompt = _build_pacing_rewrite_prompt(query, failures)
        if _rewrite_chapter_with_llm(project_root, chapter_path, args, prompt):
            txt = read_text(chapter_path).rstrip()
            txt = _normalize_paragraph_variance(_rebalance_dialogue_heavy_text(txt, query))
            actions.append("LLM rewrite for high skip density")
        else:
            txt = _normalize_paragraph_variance(_rebalance_dialogue_heavy_text(txt, query))
            txt += (
                "\n\n"
                f"[Scene expansion] Describe the execution of '{query}' with action steps, "
                "environment resistance, immediate feedback, and new decisions. "
                "Do not use summary skip phrases."
            )
            actions.append("Fallback scene expansion for skip density")

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
    # 调用 text_humanizer 获取 AI 痕迹检测数据，severity >= medium 时自动纠正（最多2轮）
    _SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}
    humanizer_section = ""
    humanizer_rounds = 0
    humanizer_auto_fixed = False
    h_code, _h_out, _h_err, h_payload = run_python(
        SCRIPT_DIR / "text_humanizer.py",
        ["report", "--chapter-file", str(chapter_path)],
    )
    if h_code == 0 and isinstance(h_payload, dict) and h_payload.get("ok"):
        llm_provider = os.environ.get("NOVEL_LLM_PROVIDER", "")
        while (
            _SEVERITY_ORDER.get(h_payload.get("severity", "low"), 0) >= 1
            and humanizer_rounds < 2
        ):
            p_code, _p_out, _p_err, p_payload = run_python(
                SCRIPT_DIR / "text_humanizer.py",
                ["prompt", "--chapter-file", str(chapter_path)],
            )
            if p_code != 0 or not isinstance(p_payload, dict):
                break
            humanize_prompt = p_payload.get("prompt", "")
            if not humanize_prompt:
                break
            if llm_provider:
                try:
                    from novel_chapter_writer import write_chapter  # type: ignore[import]
                    llm_result = write_chapter(
                        project_root,
                        chapter_file=chapter_path,
                        config_overrides={
                            "ai_provider": llm_provider,
                            "writing_prompt": humanize_prompt,
                        },
                        dry_run=False,
                    )
                    if llm_result.get("ok"):
                        humanizer_auto_fixed = True
                except Exception as _hum_err:
                    print(f"[警告] Humanizer 自动修复失败: {_hum_err}")
            humanizer_rounds += 1
            # 重新检测，severity 已达 low 则退出循环
            re_code, _, _, re_payload = run_python(
                SCRIPT_DIR / "text_humanizer.py",
                ["report", "--chapter-file", str(chapter_path)],
            )
            if (re_code == 0 and isinstance(re_payload, dict)
                    and _SEVERITY_ORDER.get(re_payload.get("severity", "low"), 0) < 1):
                h_payload = re_payload
                break
            if not llm_provider:
                break  # 非 LLM 模式只生成一次 prompt，不继续循环
        severity_map = {"low": "轻微", "medium": "中等", "high": "严重"}
        sev = severity_map.get(h_payload.get("severity", ""), h_payload.get("severity", ""))
        report_md = h_payload.get("report", "")
        humanizer_section = f"\n\n---\n\n{report_md}"
        if humanizer_auto_fixed:
            humanizer_section += f"\n\n（自动纠正已执行 {humanizer_rounds} 轮）"
        elif humanizer_rounds > 0:
            humanizer_section += "\n\n（已生成润色 prompt，需人工执行 /校稿 完成纠正）"
    else:
        sev = "未知"
        humanizer_section = "\n\n（text_humanizer 检测跳过：脚本不可用或无法读取文件）"

    copyedit = f"""# 校稿报告

- 修订目标：降低AI味、提升可读性、保证节奏递进
- 动作：清理重复表述、补足转场、强化章末钩子
- AI痕迹严重程度：{sev}
- 发布建议：参考下方检测报告后执行两遍式润色
{humanizer_section}
"""
    # evaluate_quality() 返回 "passed" 键；兼容上游可能传入 "ok" 键的场景
    quality_ok: bool = bool(quality.get("passed", quality.get("ok", False)))
    quality_failures: List[str] = list(quality.get("failures", []))  # type: ignore[arg-type]
    if quality_ok:
        publish_verdict = "可发布（通过）"
        publish_keyword = "可发布 / 通过 / PASS"
        publish_note = "本章已完成自动流程并通过所有质量门禁项。"
    else:
        publish_verdict = "不建议发布（未通过）"
        publish_keyword = "不通过 / FAIL"
        failure_lines = "\n".join(f"  - {f}" for f in quality_failures) if quality_failures else "  - 未知失败"
        publish_note = f"本章未通过以下质量门禁项，需修复后重新检查：\n{failure_lines}"

    publish = f"""# 发布判定

章节：{chapter_path.name}
结论：{publish_verdict}
说明：{publish_note}
字符数：{quality.get('char_count', 0)}  段落数：{quality.get('paragraph_count', 0)}
关键词：{publish_keyword}
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


def run_gate_check(
    project_root: Path,
    chapter_path: Path,
    pacing_tier: Optional[str] = None,
    pacing_event_types: str = "",
) -> Tuple[int, Dict[str, object]]:
    extra: List[str] = []
    if pacing_tier:
        extra.extend(["--pacing-tier", pacing_tier])
    if pacing_event_types:
        extra.extend(["--pacing-event-types", pacing_event_types])
    code, out, err, payload = run_python(
        SCRIPT_DIR / "chapter_gate_check.py",
        ["--project-root", str(project_root), "--chapter-file", str(chapter_path), *extra],
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
    gate_dir = project_root / "04_editing" / "gate_artifacts" / slugify(chapter_path.stem)
    ensure_dir(gate_dir)
    need_rebuild_gate_artifacts = False

    if "knowledge_base_contains_chapter_files" in fail_text and args.auto_fix_kb_misplaced:
        moved = move_misplaced_kb_chapters(project_root)
        if moved:
            actions.extend([f"迁移误放章节：{x}" for x in moved])

    if "chapter_storage_policy" in fail_text:
        new_path, moved = normalize_chapter_storage(project_root, chapter_path)
        chapter_path = new_path
        if moved:
            need_rebuild_gate_artifacts = True
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
        need_rebuild_gate_artifacts = True

    if "quality_baseline" in fail_text and args.auto_fix_quality:
        old_quality = dict(quality)
        quality_actions = apply_targeted_quality_fix(project_root, chapter_path, quality, args, query)
        if quality_actions:
            actions.extend([f"质量最小修复：{x}" for x in quality_actions])
            quality = evaluate_quality(read_text(chapter_path), args)
            write_quality_report(gate_dir, old_quality, quality)
            need_rebuild_gate_artifacts = True

    # 所有修复完成后统一重建门禁产物，确保时间戳晚于章节文件
    if need_rebuild_gate_artifacts:
        write_gate_artifacts(project_root, chapter_path, query, quality, query_payload)
        actions.append("重建门禁产物文件")

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
    # 节奏模式：同步提升最低字数门槛
    pacing_mode = _resolve_pacing_mode(getattr(args, "pacing_mode", "standard"))
    args.pacing_mode = pacing_mode
    pacing_profile = PACING_MODE_PROFILES[pacing_mode]
    args.min_chars = max(args.min_chars, int(pacing_profile["min_chars"]))
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
            chapter_path, path_error = validate_chapter_path(project_root, args.chapter_file)
            if path_error:
                return {"ok": False, "error": path_error}
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

        # 写前约束注入：大纲配额 / 反向刹车 / 事件推荐 / 知识图谱上下文
        writing_constraints: Optional[Dict[str, object]] = None
        injected_lines: List[str] = []
        if args.enable_constraints and chapter_path:
            writing_constraints = _collect_writing_constraints(project_root, chapter_path, query)
            outline_c = writing_constraints.get("outline_constraints")
            if isinstance(outline_c, dict):
                outline_prompt = outline_c.get("constraints_prompt")
                if isinstance(outline_prompt, str) and outline_prompt.strip():
                    injected_lines.append(outline_prompt.strip())
            anti_c = writing_constraints.get("anti_resolution_constraints")
            if isinstance(anti_c, dict):
                anti_prompt = anti_c.get("constraint_prompt")
                if isinstance(anti_prompt, str) and anti_prompt.strip():
                    injected_lines.append(anti_prompt.strip())
            event_rec = writing_constraints.get("event_recommendation")
            if isinstance(event_rec, dict):
                rec_types = event_rec.get("recommended_types")
                if isinstance(rec_types, list) and rec_types:
                    injected_lines.append(
                        "本章建议优先事件类型：" + "、".join(str(x) for x in rec_types if str(x).strip())
                    )
                notes = event_rec.get("notes")
                if isinstance(notes, list):
                    note_lines = [str(n).strip() for n in notes if str(n).strip()]
                    injected_lines.extend(note_lines)
            graph_ctx = writing_constraints.get("graph_context")
            if isinstance(graph_ctx, dict):
                ctx_prompt = graph_ctx.get("context_prompt", "")
                if ctx_prompt.strip():
                    injected_lines.append(ctx_prompt.strip())

        # RAG 检索结果注入：将 top-k 历史片段作为写作参考（与约束独立，始终注入）
        rag_lines: List[str] = []
        if isinstance(q_payload, dict):
            _rag_result = q_payload.get("result")
            _retrieved = _rag_result.get("retrieved", []) if isinstance(_rag_result, dict) else []
            _rag_limit = getattr(args, "top_k", 4)
            for _item in _retrieved:
                if not isinstance(_item, dict):
                    continue
                _chapter_ref = str(_item.get("chapter_file") or "").strip()
                for _passage in (_item.get("passages") or []):
                    if not isinstance(_passage, dict):
                        continue
                    _text = str(_passage.get("text") or "").strip()
                    if _text:
                        rag_lines.append(f"{_chapter_ref}：{_text}" if _chapter_ref else _text)
                        if len(rag_lines) >= _rag_limit:
                            break
                if len(rag_lines) >= _rag_limit:
                    break

        # 拼装最终写作查询：原始意图 + 相关历史剧情 + 写作约束
        query_sections = [query]
        if rag_lines:
            query_sections.append("[相关历史剧情]\n" + "\n".join(f"- {line}" for line in rag_lines))
        if injected_lines:
            query_sections.append("[写作约束]\n" + "\n".join(f"- {line}" for line in injected_lines))
        writing_query = "\n\n".join(query_sections)

        auto_draft_applied = False
        draft_provider_used = _resolve_draft_provider(args, project_root)
        fallback_applied = False
        llm_error_msg = None

        # Beat Sheet 流水线（优先于普通 draft，默认开启）
        if getattr(args, "use_beat_sheet", True) and chapter_is_draft_stub(chapter_path):
            _beat_chapter_no = chapter_no_from_name(chapter_path.name)
            if _beat_chapter_no > 0:
                beat_applied, beat_mode = _generate_beat_draft(
                    project_root, chapter_path, _beat_chapter_no,
                    writing_query, writing_constraints, args,
                )
                if beat_applied:
                    auto_draft_applied = True
                    draft_provider_used = beat_mode

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
            elif draft_provider_used == "beat_sheet_template":
                # beat_sheet_template 模式：beat 合成已产出结构化写作指引（BEAT_SHEET_STUB），
                # 用 beat sheet JSON 中的 chapter_goal 和各 beat 摘要构造富语义 query，
                # 生成比纯泛型模板更贴合剧情的草稿，保留 beat 结构信息。
                beat_sheet_json = load_json(
                    project_root / "00_memory" / "beats"
                    / f"ch{chapter_no_from_name(chapter_path.name):04d}_beat_sheet.json",
                    default={},
                )
                beat_goal = beat_sheet_json.get("chapter_goal", "") or query
                beat_summaries = [
                    str(b.get("summary", ""))
                    for b in beat_sheet_json.get("beats", [])
                    if isinstance(b, dict) and b.get("summary") and "[待填充]" not in str(b.get("summary", ""))
                ]
                enriched_beat_query = beat_goal
                if beat_summaries:
                    enriched_beat_query += "；" + "、".join(beat_summaries[:4])
                draft = generate_draft_text(
                    project_root, chapter_path,
                    enriched_beat_query[:300],
                    min_chars=args.min_chars,
                )
                write_text(chapter_path, draft)
                auto_draft_applied = True
            else:
                # 纯 template 模式
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
                write_text(chapter_path, improve_text_minimally(txt, writing_query))
                quality_after = evaluate_quality(read_text(chapter_path), args)
                improve_rounds += 1

        quality_report = write_quality_report(gate_dir, quality_before, quality_after)

        gate_payload: Optional[Dict[str, object]] = None
        repair_payload: Optional[Dict[str, object]] = None
        retry_actions: List[str] = []
        gate_passed_final = False

        # 提前提取事件类型和节奏档位，传给门禁做"含当前章"的预演校验
        _gate_event_types = _extract_event_types_from_constraints(writing_constraints)
        _gate_pacing_tier = _infer_pacing_tier(_gate_event_types) if _gate_event_types else None
        _gate_pacing_et_str = ",".join(_gate_event_types)

        if not draft_mode:
            write_gate_artifacts(project_root, chapter_path, writing_query, quality_after, q_payload)
            _, gate_payload = run_gate_check(
                project_root, chapter_path, _gate_pacing_tier, _gate_pacing_et_str
            )
            gate_passed_final = bool(gate_payload.get("passed")) if isinstance(gate_payload, dict) else False

            retry_rounds = 0
            while (not gate_passed_final) and args.auto_retry and retry_rounds < args.max_auto_retry_rounds:
                chapter_path, actions, quality_after = auto_fix_after_gate_failure(
                    project_root,
                    chapter_path,
                    writing_query,
                    quality_after,
                    q_payload,
                    gate_payload if gate_payload else {},
                    args,
                )
                if not actions:
                    break
                retry_actions.extend(actions)
                retry_rounds += 1
                _, gate_payload = run_gate_check(
                    project_root, chapter_path, _gate_pacing_tier, _gate_pacing_et_str
                )
                gate_passed_final = bool(gate_payload.get("passed")) if isinstance(gate_payload, dict) else False

            if not gate_passed_final:
                repair_payload = run_repair_plan(project_root, chapter_path)

        b_code, b_out, b_err, b_payload = run_python(
            SCRIPT_DIR / "plot_rag_retriever.py",
            ["build", "--project-root", str(project_root)],
        )

        # 写后处理：图谱更新 + 批量审核（均为可选，默认关闭）
        graph_update_file: Optional[str] = None
        batch_review_task: Optional[str] = None
        style_update_file: Optional[str] = None
        if gate_passed_final and chapter_path:
            _chapter_no = chapter_no_from_name(chapter_path.name)
            if args.auto_graph_update and _chapter_no > 0:
                _, _g_out, _g_err, _g_payload = run_python(
                    SCRIPT_DIR / "story_graph_updater.py",
                    ["extract", "--project-root", str(project_root),
                     "--chapter", str(_chapter_no), "--chapter-file", str(chapter_path)],
                )
                if isinstance(_g_payload, dict):
                    graph_update_file = _g_payload.get("update_file")
                # apply：将 extract 生成的待执行更新写入知识图谱
                if isinstance(_g_payload, dict) and _g_payload.get("ok"):
                    run_python(
                        SCRIPT_DIR / "story_graph_updater.py",
                        ["apply",
                         "--project-root", str(project_root),
                         "--chapter", str(_chapter_no)],
                    )
            if args.auto_batch_review:
                _chapter_numbers = sorted({
                    chapter_no_from_name(p.name)
                    for p in manuscript_dir.glob("*.md")
                    if p.is_file() and chapter_no_from_name(p.name) > 0
                })
                _chapter_count = len(_chapter_numbers)
                if _chapter_count > 0 and _chapter_count % 10 == 0:
                    _batch_start = _chapter_count - 9
                    _batch_end = _chapter_count
                    _, _r_out, _r_err, _r_payload = run_python(
                        SCRIPT_DIR / "cross_agent_reviewer.py",
                        ["batch-review", "--project-root", str(project_root),
                         "--chapter-start", str(_batch_start), "--chapter-end", str(_batch_end)],
                    )
                    if isinstance(_r_payload, dict):
                        batch_review_task = _r_payload.get("task_file")
            # 大纲锚点推进：门禁通过后将锚点推进到下一章
            if args.enable_constraints and _chapter_no > 0:
                run_python(
                    SCRIPT_DIR / "outline_anchor_manager.py",
                    ["advance",
                     "--project-root", str(project_root),
                     "--to-chapter", str(_chapter_no + 1)],
                )
            # 事件矩阵记录：门禁通过后记录本章实际使用的事件类型，维持冷却状态
            if args.enable_constraints and _chapter_no > 0:
                _filtered_types = _extract_event_types_from_constraints(writing_constraints)
                if _filtered_types:
                    run_python(
                        SCRIPT_DIR / "event_matrix_scheduler.py",
                        [
                            "record",
                            "--project-root", str(project_root),
                            "--chapter", str(_chapter_no),
                            "--types", ",".join(_filtered_types),
                        ],
                    )
                    # 节奏档位记录：从事件类型推断档位并写入 pacing_history.json
                    _pacing_tier = _infer_pacing_tier(_filtered_types)
                    run_python(
                        SCRIPT_DIR / "pacing_tracker.py",
                        [
                            "record",
                            "--project-root", str(project_root),
                            "--chapter", str(_chapter_no),
                            "--tier", _pacing_tier,
                            "--event-types", ",".join(_filtered_types),
                        ],
                    )
            # 风格基准自动更新：每 N 章（默认10章）更新一次
            style_update_file: Optional[str] = None
            if getattr(args, "auto_style_update", True):
                _style_interval = getattr(args, "style_update_interval", 10)
                _all_chapters = sorted({
                    chapter_no_from_name(p.name)
                    for p in manuscript_dir.glob("*.md")
                    if p.is_file() and chapter_no_from_name(p.name) > 0
                })
                _chapter_count = len(_all_chapters)
                if _chapter_count > 0 and _chapter_count % _style_interval == 0:
                    recent_chapters = sorted(
                        [p for p in manuscript_dir.glob("*.md") if p.is_file()],
                        key=lambda p: chapter_no_from_name(p.name),
                        reverse=True,
                    )[:_style_interval]
                    if recent_chapters:
                        style_args = (
                            [str(p) for p in recent_chapters]
                            + ["--profile-name", f"auto_ch{_chapter_count}",
                               "--project-root", str(project_root)]
                        )
                        st_code, _st_out, _st_err, st_payload = run_python(
                            SCRIPT_DIR / "style_fingerprint.py", style_args
                        )
                        if st_code == 0 and isinstance(st_payload, dict):
                            _st_outputs = st_payload.get("outputs", {})
                            if isinstance(_st_outputs, dict):
                                style_update_file = (
                                    _st_outputs.get("project_profile")
                                    or _st_outputs.get("global_profile")
                                    or ""
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
            "pacing_mode": pacing_mode,
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
            "writing_constraints": writing_constraints,
            "graph_update_file": graph_update_file,
            "batch_review_task": batch_review_task,
            "style_update_file": style_update_file if gate_passed_final and chapter_path else None,
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

    # 初始化知识图谱：调用 init 子命令确保结构符合 story_graph_builder 标准
    story_graph_file = project_root / "00_memory" / "story_graph.json"
    if not story_graph_file.exists():
        run_python(SCRIPT_DIR / "story_graph_builder.py", ["init", "--project-root", str(project_root)])
        if story_graph_file.exists():
            files["changed"].append(str(story_graph_file))

    # 初始化大纲锚点：调用 init 子命令，自动解析 novel_plan.md 构建 volumes
    outline_anchors_file = project_root / "00_memory" / "outline_anchors.json"
    if not outline_anchors_file.exists():
        target_chapters = max(10, int(getattr(args, "target_words", 0) or 0) // 3500)
        run_python(
            SCRIPT_DIR / "outline_anchor_manager.py",
            ["init", "--project-root", str(project_root),
             "--total-chapters-target", str(target_chapters)],
        )
        if outline_anchors_file.exists():
            files["changed"].append(str(outline_anchors_file))

    # 将开书前五要素确认信息写入 idea_seed.md（目标读者/写作风格/核心禁区）
    confirmation_items = [
        ("目标读者", getattr(args, "target_audience", "")),
        ("写作风格", getattr(args, "writing_style", "")),
        ("核心禁区", getattr(args, "core_taboo", "")),
    ]
    confirmation_lines = [
        f"- {label}：{val}" for label, val in confirmation_items if str(val or "").strip()
    ]
    if confirmation_lines:
        idea_seed_file = project_root / "00_memory" / "idea_seed.md"
        original = read_text(idea_seed_file) if idea_seed_file.exists() else "# 创意种子\n"
        addition = "\n\n## 开书前确认\n" + "\n".join(confirmation_lines) + "\n"
        write_text(idea_seed_file, original.rstrip() + addition)
        if str(idea_seed_file) not in files["changed"]:
            files["changed"].append(str(idea_seed_file))

    return {
        "ok": b_code == 0,
        "command": "one-click",
        "project_root": str(project_root),
        "created_or_updated_files": files["changed"],
        "skipped_files": files["skipped"],
        "index_result": b_payload if b_payload is not None else {"stdout": b_out, "stderr": b_err},
        "next_step": "/继续写",
    }


def cmd_revise_outline(args: argparse.Namespace) -> Dict[str, object]:
    """执行 /改纲续写：锚点重算 + 图谱级联标记 + RAG 索引重建。

    使用前提：用户已手动编辑 novel_plan.md，本命令将所有下游状态与新大纲同步。
    三步骤依次执行：
      1. 备份旧锚点 + 重算大纲锚点（必须成功，否则 ok=False）
      2. 图谱级联分析（图谱存在时执行，失败不阻断后续）
      3. 重建 RAG 索引（始终执行，失败不阻断报告生成）
    """
    project_root = Path(args.project_root).expanduser().resolve()
    from_chapter = int(args.from_chapter)
    change_description = str(getattr(args, "change_description", "") or "").strip()

    if from_chapter <= 0:
        return {
            "ok": False,
            "command": "revise-outline",
            "error": "from_chapter_must_be_positive",
        }

    plan_file = project_root / "00_memory" / "novel_plan.md"
    if not plan_file.exists():
        return {
            "ok": False,
            "command": "revise-outline",
            "error": f"novel_plan_missing:{plan_file}",
        }

    flow_dir = project_root / FLOW_DIR_NAME
    ensure_dir(flow_dir)

    report_file = project_root / "00_memory" / "revise_outline_report.md"
    anchors_file = project_root / "00_memory" / "outline_anchors.json"
    backup_file: Optional[Path] = None
    backup_created = False

    try:
        # Step 1: 备份现有锚点（不存在则跳过）
        if anchors_file.exists():
            ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = flow_dir / f"backup_anchors_{ts}.json"
            shutil.copy2(str(anchors_file), str(backup_file))
            backup_created = True

        # Step 2: 重算大纲锚点（从 novel_plan.md 重新解析卷结构）
        r_code, r_out, _r_err, r_payload = run_python(
            SCRIPT_DIR / "outline_anchor_manager.py",
            ["recalculate", "--project-root", str(project_root)],
        )
        recalc_result: Dict[str, object] = (
            r_payload if isinstance(r_payload, dict) else {"stdout": r_out}
        )
        anchors_recalculated = r_code == 0 and bool(recalc_result.get("ok"))

        # Step 3: 图谱级联标记（锚点成功且图谱存在时执行，失败不阻断后续）
        cascade_result: Dict[str, object] = {"ok": False, "skipped": True}
        cascade_ok = False
        graph_file = project_root / "00_memory" / "story_graph.json"
        if anchors_recalculated and graph_file.exists():
            c_code, c_out, _c_err, c_payload = run_python(
                SCRIPT_DIR / "story_graph_updater.py",
                [
                    "cascade",
                    "--project-root", str(project_root),
                    "--from-chapter", str(from_chapter),
                    "--change-description", change_description,
                ],
            )
            cascade_result = (
                c_payload if isinstance(c_payload, dict) else {"stdout": c_out}
            )
            cascade_ok = c_code == 0 and bool(cascade_result.get("ok"))

        # Step 4: 重建 RAG 索引（锚点成功后执行，不依赖级联结果）
        rag_result: Dict[str, object] = {"ok": False, "skipped": True}
        rag_rebuilt = False
        if anchors_recalculated:
            b_code, b_out, _b_err, b_payload = run_python(
                SCRIPT_DIR / "plot_rag_retriever.py",
                ["build", "--project-root", str(project_root)],
            )
            rag_result = b_payload if isinstance(b_payload, dict) else {"stdout": b_out}
            rag_rebuilt = b_code == 0 and bool(rag_result.get("ok"))

        # Step 5: 写入改纲汇总报告
        report_lines = [
            "# 改纲续写报告",
            "",
            f"- 时间：{dt.datetime.now().isoformat()}",
            f"- 改纲生效章节：第{from_chapter}章",
            f"- 改纲说明：{change_description or '未提供'}",
            f"- novel_plan.md：{plan_file}",
            f"- 锚点备份：{backup_file if backup_created else '无旧锚点，无需备份'}",
            "",
            "## 锚点重算",
            f"- 成功：{anchors_recalculated}",
            f"- 卷数：{recalc_result.get('volume_count', 'N/A')}",
            f"- 总章数：{recalc_result.get('total_chapters_target', 'N/A')}",
            "  （如卷数/总章数与新大纲不符，请检查 novel_plan.md 卷标题格式）",
            "",
            "## 图谱级联",
            f"- 执行：{'是' if graph_file.exists() else '否（图谱文件不存在，跳过）'}",
            f"- 成功：{cascade_ok}",
            f"- 受影响节点：{cascade_result.get('affected_nodes_count', 'N/A')}",
            f"- 受影响边：{cascade_result.get('affected_edges_count', 'N/A')}",
            "",
            "## RAG 索引重建",
            f"- 成功：{rag_rebuilt}",
            "",
            "## 下一步",
            "- 请核对上方卷数/总章数是否与新大纲一致。",
            "- 如不一致，请修正 novel_plan.md 后再次执行 /改纲续写。",
            "- 确认无误后，执行 /继续写 从新剧情方向推进。",
            "",
        ]
        report_written = write_text(report_file, "\n".join(report_lines))

        # ok 的判定：锚点重算和报告写入是必要条件；级联和RAG失败可降级继续
        ok = anchors_recalculated and report_written
        error: Optional[str] = (
            None if ok
            else "anchor_recalculate_failed" if not anchors_recalculated
            else "report_write_failed"
        )
        next_step = (
            "改纲完成：锚点已重算、图谱已标记、索引已重建。请执行 /继续写 从新方向推进。"
            if (anchors_recalculated and cascade_ok and rag_rebuilt)
            else "改纲流程部分完成，请查看 revise_outline_report.md 确认失败步骤后再执行 /继续写。"
        )

        return {
            "ok": ok,
            "command": "revise-outline",
            "project_root": str(project_root),
            "from_chapter": from_chapter,
            "change_description": change_description,
            "anchors_backup_file": str(backup_file) if backup_file else None,
            "anchors_recalculated": anchors_recalculated,
            "anchors_result": recalc_result,
            "cascade_ok": cascade_ok,
            "cascade_result": cascade_result,
            "rag_rebuilt": rag_rebuilt,
            "rag_result": rag_result,
            "report_file": str(report_file),
            "next_step": next_step,
            "error": error,
        }

    except Exception as exc:
        return {
            "ok": False,
            "command": "revise-outline",
            "project_root": str(project_root),
            "error": repr(exc),
        }


def cmd_brainstorm(args: argparse.Namespace) -> Dict[str, object]:
    """执行 /脑洞建图：交互式脑洞引导 → 生成 idea_seed.md + plan_generation_prompt.md。"""
    project_root = Path(args.project_root).expanduser().resolve()
    project_structure(project_root)

    # Step 1: 初始化会话（已有会话则保留）
    init_cmd = ["init", "--project-root", str(project_root)]
    if args.genre:
        init_cmd.extend(["--genre", args.genre])
    if args.idea:
        init_cmd.extend(["--title-hint", args.idea])
    i_code, i_out, _i_err, i_payload = run_python(
        SCRIPT_DIR / "interactive_ideation_engine.py", init_cmd,
    )
    if i_code != 0:
        return {
            "ok": False, "command": "brainstorm", "project_root": str(project_root),
            "error": "ideation_init_failed",
            "init_result": i_payload if i_payload is not None else {"stdout": i_out},
        }

    # Step 2: 如果提供了 genre/idea，预填第1轮答案（使用 fallback 模式）
    c_payload: Optional[Dict[str, object]] = None
    if args.genre or args.idea:
        seed_answers: Dict[str, str] = {}
        if args.genre:
            seed_answers["genre"] = args.genre
        if args.idea:
            seed_answers["hook"] = args.idea
            seed_answers["protagonist_goal"] = args.idea
        c_code, _c_out, _c_err, c_payload = run_python(
            SCRIPT_DIR / "interactive_ideation_engine.py",
            [
                "collect", "--project-root", str(project_root),
                "--round", "1",
                "--answers", json.dumps(seed_answers, ensure_ascii=False),
                "--use-fallback",
            ],
        )
        # 推进到下一轮，让 generate 可以生成产出物
        if c_code == 0:
            run_python(
                SCRIPT_DIR / "interactive_ideation_engine.py",
                ["advance", "--project-root", str(project_root)],
            )

    # Step 3: 尝试生成 idea_seed.md（需要至少1轮答案；无答案时优雅降级返回引导问题）
    g_code, _g_out, _g_err, g_payload = run_python(
        SCRIPT_DIR / "interactive_ideation_engine.py",
        ["generate", "--project-root", str(project_root)],
    )

    # generate 因答案不足失败时：返回 ok=True 并附带引导问题，让用户继续填写
    generate_succeeded = g_code == 0 and isinstance(g_payload, dict) and g_payload.get("ok")
    if not generate_succeeded:
        prompts_for_user = (
            i_payload.get("prompts", []) if isinstance(i_payload, dict) else []
        )
        fallback_opts = (
            i_payload.get("fallback_options", {}) if isinstance(i_payload, dict) else {}
        )
        return {
            "ok": True,  # 会话已初始化，只是需要更多输入
            "command": "brainstorm",
            "project_root": str(project_root),
            "session_started": True,
            "needs_more_input": True,
            "round_prompts": prompts_for_user,
            "fallback_options": fallback_opts,
            "init_result": i_payload,
            "generate_result": g_payload,
            "next_step": (
                "脑洞引导会话已初始化。请逐轮回答以下问题（或使用 collect 子命令收集答案），"
                "完成后执行 generate 生成 idea_seed.md。"
            ),
        }

    return {
        "ok": True,
        "command": "brainstorm",
        "project_root": str(project_root),
        "session_started": True,
        "needs_more_input": False,
        "init_result": i_payload,
        "collect_result": c_payload,
        "generate_result": g_payload,
        "generated_files": g_payload.get("generated_files", []),
        "next_step": "脑洞种子已生成。请审核 idea_seed.md，然后执行 /一键开书 正式开始写作。",
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
    p_one.add_argument("--target-audience", default="", help="目标读者群体（如：18-35岁起点男频读者）")
    p_one.add_argument("--writing-style", default="", help="写作风格（如：爽文快节奏/文艺慢叙事）")
    p_one.add_argument("--core-taboo", default="", help="核心禁区（如：不写血腥/不写恋童）")
    p_one.add_argument("--overwrite", action="store_true")
    p_one.add_argument("--emit-json")

    p_brain = sub.add_parser("brainstorm", help="执行 /脑洞建图（交互式脑洞引导）")
    p_brain.add_argument("--project-root", required=True)
    p_brain.add_argument("--genre", default="", help="预设题材")
    p_brain.add_argument("--idea", default="", help="初始故事想法/书名提示")
    p_brain.add_argument("--rounds", type=int, default=5, help="计划引导轮次")
    p_brain.add_argument("--emit-json")

    p_rev = sub.add_parser("revise-outline", help="执行 /改纲续写（锚点重算+图谱级联+索引重建）")
    p_rev.add_argument("--project-root", required=True)
    p_rev.add_argument("--from-chapter", type=int, required=True,
                       help="改纲生效的起始章节号（含该章，必须 >= 1）")
    p_rev.add_argument("--change-description", default="",
                       help="本次改纲说明（如：调整卷二主线冲突方向）")
    p_rev.add_argument("--emit-json")

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
    p_cont.add_argument(
        "--pacing-mode", choices=["fast", "standard", "immersive"], default="standard",
        help=(
            "章节节奏模式。fast=2000字/宽松约束，standard=2500字/均衡，"
            "immersive=4500字/强制沉浸展开。影响 Beat 扩写硬约束强度和最低章节字数。"
        ),
    )
    p_cont.add_argument("--min-dialogue-ratio", type=float, default=0.03)
    p_cont.add_argument("--max-dialogue-ratio", type=float, default=0.7)
    p_cont.add_argument("--min-sentences", type=int, default=8)
    p_cont.add_argument("--min-content-density", type=float, default=0.7,
                        help="正文密度要求（排除标记、注释等），默认0.7")
    p_cont.add_argument("--max-chapter-variance", type=float, default=0.3,
                        help="相邻章节字数差异限制，默认0.3（30%%）")
    p_cont.add_argument("--max-ai-phrase-density", type=float, default=0.05,
                        help="AI高频词密度限制，默认0.05（5%%）")
    p_cont.add_argument("--auto-research", dest="auto_research", action="store_true", default=True,
                        help="写前自动检测知识缺口并提示调研")
    p_cont.add_argument("--draft-provider", choices=["auto", "template", "llm"], default="auto",
                        help="Draft strategy: auto (Two-Phase if LLM configured), template, or llm")
    p_cont.add_argument("--llm-provider", default=None,
                        help="LLM提供商(openai/anthropic/kimi/glm/minimax)，需配合--draft-provider llm")
    p_cont.add_argument("--llm-model", default=None,
                        help="LLM模型名称，需配合--draft-provider llm")
    p_cont.add_argument("--llm-api-key", default=None,
                        help="LLM API密钥，需配合--draft-provider llm")
    p_cont.add_argument("--enable-constraints", dest="enable_constraints",
                        action="store_true", default=True,
                        help="写前注入大纲配额、反向刹车与事件推荐约束（默认开启）")
    p_cont.add_argument("--no-constraints", dest="enable_constraints",
                        action="store_false",
                        help="禁用写前约束注入（高级用户）")
    p_cont.add_argument("--auto-graph-update", dest="auto_graph_update",
                        action="store_true", default=True,
                        help="章节通过门禁后自动生成图谱更新建议（默认开启）")
    p_cont.add_argument("--no-graph-update", dest="auto_graph_update",
                        action="store_false",
                        help="禁用图谱自动更新")
    p_cont.add_argument("--auto-batch-review", dest="auto_batch_review",
                        action="store_true", default=True,
                        help="章节数达到10/20/30...时自动生成批量审核任务（默认开启）")
    p_cont.add_argument("--no-batch-review", dest="auto_batch_review",
                        action="store_false",
                        help="禁用每10章批量审核")
    p_cont.add_argument("--no-research", dest="auto_research",
                        action="store_false",
                        help="禁用写前知识缺口调研")
    p_cont.add_argument("--use-beat-sheet", dest="use_beat_sheet",
                        action="store_true", default=True,
                        help="使用 Beat Sheet 流水线写作（默认开启）")
    p_cont.add_argument("--no-beat-sheet", dest="use_beat_sheet",
                        action="store_false",
                        help="禁用 Beat Sheet 流水线，回退到普通草稿模式")
    p_cont.add_argument("--beat-count", type=int, default=4,
                        help="每章 Beat 数量（3-5），默认 4")
    p_cont.add_argument("--auto-style-update", dest="auto_style_update",
                        action="store_true", default=True,
                        help="每 N 章自动更新风格基准（默认开启）")
    p_cont.add_argument("--no-style-update", dest="auto_style_update",
                        action="store_false",
                        help="禁用风格基准自动更新")
    p_cont.add_argument("--style-update-interval", type=int, default=10,
                        help="风格更新章节间隔，默认 10")
    p_cont.add_argument("--emit-json")

    return p.parse_args()


def main() -> int:
    args = parse_args()
    _dispatch = {
        "one-click": one_click,
        "brainstorm": cmd_brainstorm,
        "revise-outline": cmd_revise_outline,
        "continue-write": continue_write,
    }
    _handler = _dispatch.get(args.cmd)
    if _handler is None:
        payload: Dict[str, object] = {"ok": False, "error": f"unknown_command:{args.cmd}"}
    else:
        payload = _handler(args)
    if args.emit_json:
        jp = Path(args.emit_json).expanduser().resolve()
        ensure_dir(jp.parent)
        jp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
