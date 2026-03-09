#!/usr/bin/env python3
"""章节合成器（多步流水线写作 Step 3）。

将多个 Beat 扩写结果串联为完整章节，添加过渡句，
统一人称时态，确保章内时间线连续性和章末钩子。

子命令：
1. synthesize — 合成多个 Beat 扩写为完整章节
2. validate   — 校验合成稿的连贯性和质量
"""

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import count_chars, ensure_dir, load_json, read_text, save_json, write_text

# -- 节奏检测 ---------------------------------------------------------------

# 按节奏模式设定校验阈值
PACING_PROFILES: Dict[str, Any] = {
    "fast": {
        "min_chapter_chars": 2500,
        "max_skip_density": 0.35,   # 每段平均允许的跳过词频率上限
        "min_avg_chars_per_paragraph": 45,
    },
    "standard": {
        "min_chapter_chars": 3000,
        "max_skip_density": 0.25,
        "min_avg_chars_per_paragraph": 50,
    },
    "immersive": {
        "min_chapter_chars": 4500,
        "max_skip_density": 0.15,
        "min_avg_chars_per_paragraph": 80,
    },
}

# 概括跳过词正则（用于检测"剧情飞速推进"信号）
_PACING_SKIP_PATTERNS: List[tuple] = [
    ("time_skip",    r"(?:此后|随后|转眼|一晃|没过多久|几天后|数日后|几个月后|数月后|又过了)"),
    ("summary_skip", r"(?:经过一番|经过数轮|花了[一二三四五六七八九十百\d两]+[天日月年]|苦修[一二三四五六七八九十百\d两]*[天日月年]?)"),
    ("result_only",  r"(?:练功大成|很快(?:就|便)|就这样(?:结束|过去)|不知不觉(?:就)?(?:完成|突破|成功))"),
]


def _resolve_pacing_mode(value: str) -> str:
    return value if value in PACING_PROFILES else "standard"


def _check_pacing_skip(text: str, paragraphs: List[str]) -> Dict[str, Any]:
    """检测概括性跳过叙述密度。返回命中次数、段落密度和分类明细。"""
    import re as _re
    hits: List[Dict[str, Any]] = []
    total_hits = 0
    for label, pattern in _PACING_SKIP_PATTERNS:
        count = len(_re.findall(pattern, text))
        if count > 0:
            hits.append({"label": label, "count": count})
            total_hits += count
    density = round(total_hits / max(len(paragraphs), 1), 3)
    return {"total_hits": total_hits, "density": density, "hits": hits}


# -- 配置 ------------------------------------------------------------------

@dataclass
class SynthConfig:
    beats_rel_dir: str = "00_memory/beats"
    manuscript_rel_dir: str = "03_manuscript"
    min_chapter_chars: int = 2000
    max_chapter_chars: int = 6000
    default_indent: int = 2

    # 章末钩子检测关键词
    hook_keywords: List[str] = field(default_factory=lambda: [
        "?", "？", "……", "却", "突然", "竟", "谁知", "不料",
        "正要", "忽然", "然而", "可是", "殊不知",
        "心中一凛", "暗道不好", "变了脸色",
    ])

    # 过渡模板（AI 填充时参考）
    transition_hints: List[str] = field(default_factory=lambda: [
        "（场景切换：时间推移）",
        "（场景切换：空间转移）",
        "（视角切换）",
    ])


# -- 内部工具 ---------------------------------------------------------------

def _beats_dir(root: Path, cfg: SynthConfig) -> Path:
    return root / cfg.beats_rel_dir


def _beat_sheet_path(root: Path, chapter: int, cfg: SynthConfig) -> Path:
    return _beats_dir(root, cfg) / f"ch{chapter:04d}_beat_sheet.json"


def _beat_expand_path(root: Path, chapter: int, beat_id: int, cfg: SynthConfig) -> Path:
    return _beats_dir(root, cfg) / f"ch{chapter:04d}_beat{beat_id:02d}_expand.md"


def _synth_output_path(root: Path, chapter: int, cfg: SynthConfig) -> Path:
    return _beats_dir(root, cfg) / f"ch{chapter:04d}_synthesized.md"


def _collect_beat_texts(
    root: Path, chapter: int, beat_count: int, cfg: SynthConfig,
) -> List[Dict[str, Any]]:
    """收集所有 Beat 扩写文本，返回 [{beat_id, text, chars, file}]。"""
    results: List[Dict[str, Any]] = []
    for bid in range(1, beat_count + 1):
        path = _beat_expand_path(root, chapter, bid, cfg)
        text = read_text(path)
        results.append({
            "beat_id": bid,
            "text": text,
            "chars": count_chars(text),
            "file": str(path),
            "exists": path.exists(),
        })
    return results


def _check_hook(text: str, cfg: SynthConfig) -> Dict[str, Any]:
    """检查章末是否有钩子。"""
    tail = text[-200:] if len(text) > 200 else text
    hits = [kw for kw in cfg.hook_keywords if kw in tail]
    return {"has_hook": len(hits) > 0, "hits": hits}


def _build_synthesis_prompt(
    chapter: int,
    chapter_goal: str,
    beat_texts: List[Dict[str, Any]],
    cfg: SynthConfig,
) -> str:
    """构建合成提示词，供 AI 执行实际合成。"""
    lines = [
        f"# 第 {chapter} 章合成指令",
        "",
        f"**章节目标**: {chapter_goal}",
        "",
        "请将以下 Beat 扩写结果合成为一个完整章节：",
        "",
    ]

    for bt in beat_texts:
        if bt["exists"] and bt["text"].strip():
            lines.append(f"## Beat {bt['beat_id']}（{bt['chars']} 字）")
            lines.append(bt["text"].strip())
            lines.append("")

    lines.extend([
        "## 合成要求",
        "1. 在 Beat 之间添加自然过渡句（场景切换、时间推移）",
        "2. 统一人称和时态",
        "3. 检查章内时间线连续性",
        "4. 确保章末有钩子（悬念/新问题）",
        "5. 删除 Beat 分隔标记，使文章流畅连贯",
        "6. 不要添加章节标题，仅输出正文",
    ])

    return "\n".join(lines)


# -- 子命令 -----------------------------------------------------------------

def cmd_synthesize(args: argparse.Namespace, cfg: SynthConfig) -> Dict[str, Any]:
    """合成 Beat 扩写为完整章节。

    如果 Beat 扩写文件包含的是 AI 生成的正式文本，直接拼接并
    生成合成提示词；如果只是提示词模板，则仅生成合成指令文件。
    """
    root = Path(args.project_root).expanduser().resolve()
    chapter = args.chapter

    sheet_path = _beat_sheet_path(root, chapter, cfg)
    sheet = load_json(sheet_path, default={})
    beats = sheet.get("beats", [])

    if not beats:
        return {
            "ok": False, "command": "synthesize",
            "error": f"Beat Sheet 不存在或为空: {sheet_path}",
        }

    chapter_goal = sheet.get("chapter_goal", "")
    beat_texts = _collect_beat_texts(root, chapter, len(beats), cfg)

    existing_texts = [bt for bt in beat_texts if bt["exists"] and bt["text"].strip()]
    if not existing_texts:
        return {
            "ok": False, "command": "synthesize",
            "error": "没有找到任何 Beat 扩写文件，请先执行 expand 并填充内容",
        }

    # 生成合成提示词
    prompt = _build_synthesis_prompt(chapter, chapter_goal, beat_texts, cfg)

    # 如果所有 Beat 都是正式文本（非模板），尝试简单拼接
    all_texts = [bt["text"].strip() for bt in beat_texts if bt["exists"] and bt["text"].strip()]
    is_template = any("扩写指令" in t or "[待填充]" in t for t in all_texts)

    output_path = _synth_output_path(root, chapter, cfg)
    ensure_dir(output_path.parent)

    if is_template:
        # Beat 文件还是模板状态，只保存合成指令
        write_text(output_path, prompt)
        return {
            "ok": True, "command": "synthesize",
            "output_file": str(output_path),
            "mode": "prompt_only",
            "beat_count": len(beats),
            "existing_beats": len(existing_texts),
            "message": "Beat 扩写文件仍为模板，已生成合成指令。请先填充 Beat 正文。",
        }

    # Beat 文件是正式文本，拼接为初稿
    separator = "\n\n"
    raw_draft = separator.join(all_texts)
    total_chars = count_chars(raw_draft)

    draft_with_header = f"# 第{chapter}章\n\n{raw_draft}"
    write_text(output_path, draft_with_header)

    # 同时保存合成提示词供 AI 润色用
    prompt_path = _beats_dir(root, cfg) / f"ch{chapter:04d}_synth_prompt.md"
    write_text(prompt_path, prompt)

    return {
        "ok": True, "command": "synthesize",
        "output_file": str(output_path),
        "prompt_file": str(prompt_path),
        "mode": "draft_merged",
        "beat_count": len(beats),
        "existing_beats": len(existing_texts),
        "total_chars": total_chars,
        "message": f"已拼接 {len(existing_texts)} 个 Beat 为初稿（{total_chars} 字），"
                   f"合成提示词已保存供 AI 润色使用。",
    }


def cmd_validate(args: argparse.Namespace, cfg: SynthConfig) -> Dict[str, Any]:
    """校验合成稿的连贯性和质量。"""
    root = Path(args.project_root).expanduser().resolve()
    chapter = args.chapter

    # 优先使用手动指定的文件，否则使用默认合成稿路径
    if args.chapter_file:
        synth_path = Path(args.chapter_file)
        if not synth_path.is_absolute():
            synth_path = root / synth_path
    else:
        synth_path = _synth_output_path(root, chapter, cfg)

    if not synth_path.exists():
        return {
            "ok": False, "command": "validate",
            "error": f"合成稿不存在: {synth_path}",
        }

    text = read_text(synth_path)
    chars = count_chars(text)
    paragraphs = [p.strip() for p in text.split("\n") if p.strip() and not p.startswith("#")]
    pacing_mode = _resolve_pacing_mode(getattr(args, "pacing_mode", "standard"))
    pacing_profile = PACING_PROFILES[pacing_mode]
    errors: List[str] = []
    warnings: List[str] = []

    # 字数检查（取配置值与节奏模式阈值中的较大值）
    min_chars = max(cfg.min_chapter_chars, pacing_profile["min_chapter_chars"])
    if chars < min_chars:
        errors.append(f"字数不足: {chars} 字（{pacing_mode} 模式最低 {min_chars}）")
    if chars > cfg.max_chapter_chars:
        warnings.append(f"字数偏多: {chars} 字（建议 <= {cfg.max_chapter_chars}）")

    # 段落数检查
    if len(paragraphs) < 5:
        warnings.append(f"段落过少: {len(paragraphs)} 段（建议 >= 5）")

    # 段落平均字数检查（过短说明内容稀薄）
    avg_chars_per_paragraph = round(chars / max(len(paragraphs), 1), 1)
    if avg_chars_per_paragraph < pacing_profile["min_avg_chars_per_paragraph"]:
        warnings.append(
            f"段落平均字数偏低: {avg_chars_per_paragraph} 字/段"
            f"（{pacing_mode} 模式建议 >= {pacing_profile['min_avg_chars_per_paragraph']}）"
        )

    # 章末钩子检查
    hook = _check_hook(text, cfg)
    if not hook["has_hook"]:
        warnings.append("章末未检测到钩子元素，建议添加悬念")

    # 对话占比检查（覆盖中文引号和 ASCII 引号）
    quote_chars = (chr(0x201c), chr(0x201d), chr(0x22))
    dialogue_lines = [p for p in paragraphs if any(p.startswith(q) for q in quote_chars)]
    dialogue_ratio = len(dialogue_lines) / max(len(paragraphs), 1)
    if dialogue_ratio < 0.05:
        warnings.append(f"对话占比偏低: {dialogue_ratio:.1%}（建议 >= 5%）")

    # 概括跳过密度检查
    pacing_skip = _check_pacing_skip(text, paragraphs)
    if pacing_skip["density"] > pacing_profile["max_skip_density"]:
        warnings.append(
            f"概括跳过密度偏高: {pacing_skip['density']:.2f} 次/段"
            f"（{pacing_mode} 模式建议 <= {pacing_profile['max_skip_density']:.2f}）"
            "——请检查是否有大量'此后X天''经过一番'等跳过句"
        )

    # 残留模板标记检查
    template_markers = ["[待填充]", "扩写指令", "Beat {"]
    for marker in template_markers:
        if marker in text:
            errors.append(f"残留模板标记: '{marker}' 未被替换")

    return {
        "ok": len(errors) == 0,
        "command": "validate",
        "chapter_file": str(synth_path),
        "chapter": chapter,
        "pacing_mode": pacing_mode,
        "chars": chars,
        "avg_chars_per_paragraph": avg_chars_per_paragraph,
        "paragraphs": len(paragraphs),
        "dialogue_ratio": round(dialogue_ratio, 3),
        "hook": hook,
        "pacing_skip": pacing_skip,
        "errors": errors,
        "warnings": warnings,
        "passed": len(errors) == 0,
    }


# -- CLI -------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="章节合成器")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("synthesize", help="合成 Beat 扩写为完整章节")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", type=int, required=True, help="章节号")

    s = sub.add_parser("validate", help="校验合成稿质量")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", type=int, required=True)
    s.add_argument("--chapter-file", default="", help="手动指定章节文件路径")
    s.add_argument(
        "--pacing-mode", choices=["fast", "standard", "immersive"], default="standard",
        help="节奏模式：影响最低字数和概括跳过密度阈值",
    )

    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = SynthConfig()

    dispatch = {"synthesize": cmd_synthesize, "validate": cmd_validate}

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
