#!/usr/bin/env python3
"""
从样章提取写作风格特征，并同步到：
1) 项目内风格文件与知识库
2) 全局风格库（跨项目复用）

仅使用标准库，避免依赖膨胀。
"""

import argparse
import datetime as dt
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
SENTENCE_SPLIT_RE = re.compile(r"[。！？!?]+")
PARA_SPLIT_RE = re.compile(r"\n\s*\n+")
DIALOGUE_RE = re.compile(r"[“\"]([^\"”]{1,2000})[”\"]|「([^」]{1,2000})」|『([^』]{1,2000})』")

FIRST_PERSON = {"我", "我们", "咱", "咱们"}
THIRD_PERSON = {"他", "她", "他们", "她们", "它", "它们"}

PUNCTUATIONS = ["，", "。", "！", "？", "；", "：", "…"]

STOP_PHRASES = {
    "我们", "你们", "他们", "她们", "它们", "这个", "那个", "一种", "没有", "已经",
    "因为", "所以", "如果", "但是", "然后", "自己", "不是", "不会", "就是", "还是",
    "一个", "一些", "可以", "时候", "什么", "怎么", "这样", "那样", "起来", "进去",
    "出来", "一下", "一样", "然后", "于是", "而且", "并且", "但是", "然而", "以及",
}


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-").lower()
    if slug:
        return slug
    return "style-" + hashlib.md5(value.encode("utf-8")).hexdigest()[:8]


def read_texts(paths: List[Path]) -> Tuple[str, List[str]]:
    contents = []
    missing = []
    for p in paths:
        if not p.exists():
            missing.append(str(p))
            continue
        contents.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n\n".join(contents), missing


def sentence_stats(text: str) -> Dict[str, float]:
    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if not sentences:
        return {"sentence_count": 0, "avg_sentence_chars": 0.0, "max_sentence_chars": 0}
    lengths = [len(CJK_RE.findall(s)) for s in sentences]
    return {
        "sentence_count": len(sentences),
        "avg_sentence_chars": round(sum(lengths) / len(lengths), 2),
        "max_sentence_chars": max(lengths),
    }


def paragraph_stats(text: str) -> Dict[str, float]:
    paras = [p.strip() for p in PARA_SPLIT_RE.split(text) if p.strip()]
    if not paras:
        return {"paragraph_count": 0, "avg_paragraph_chars": 0.0}
    lens = [len(CJK_RE.findall(p)) for p in paras]
    return {
        "paragraph_count": len(paras),
        "avg_paragraph_chars": round(sum(lens) / len(lens), 2),
    }


def dialogue_ratio(text: str, total_cjk_chars: int) -> float:
    if total_cjk_chars <= 0:
        return 0.0
    dialogue_chars = 0
    for m in DIALOGUE_RE.finditer(text):
        parts = [g for g in m.groups() if g]
        if not parts:
            continue
        dialogue_chars += sum(len(CJK_RE.findall(part)) for part in parts)
    return round(dialogue_chars / total_cjk_chars, 4)


def punctuation_density(text: str, sentence_count: int) -> Dict[str, float]:
    if sentence_count <= 0:
        return {p: 0.0 for p in PUNCTUATIONS}
    result = {}
    for p in PUNCTUATIONS:
        result[p] = round(text.count(p) / sentence_count, 3)
    return result


def top_phrases(text: str, top_n: int) -> List[Tuple[str, int]]:
    sequences = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    counter: Counter[str] = Counter()

    for seq in sequences:
        seq_len = len(seq)
        for n in (2, 3):
            if seq_len < n:
                continue
            for i in range(seq_len - n + 1):
                phrase = seq[i : i + n]
                if phrase in STOP_PHRASES:
                    continue
                if len(set(phrase)) == 1:
                    continue
                counter[phrase] += 1

    return counter.most_common(top_n)


def perspective(text: str) -> Dict[str, float]:
    total = len(CJK_RE.findall(text))
    if total <= 0:
        return {"first_person_per_10k": 0.0, "third_person_per_10k": 0.0, "label": "未知"}

    first = sum(text.count(w) for w in FIRST_PERSON)
    third = sum(text.count(w) for w in THIRD_PERSON)

    first_k = round(first * 10000 / total, 2)
    third_k = round(third * 10000 / total, 2)

    if first_k > third_k * 1.4 and first_k > 8:
        label = "第一人称倾向"
    elif third_k > first_k * 1.4 and third_k > 8:
        label = "第三人称倾向"
    else:
        label = "混合/不显著"

    return {
        "first_person_per_10k": first_k,
        "third_person_per_10k": third_k,
        "label": label,
    }


def style_tags(avg_sentence_chars: float, dialogue_rate: float, punct: Dict[str, float]) -> List[str]:
    tags = []

    if avg_sentence_chars <= 16:
        tags.append("短句快节奏")
    elif avg_sentence_chars >= 30:
        tags.append("长句沉浸")
    else:
        tags.append("中句平衡")

    if dialogue_rate >= 0.45:
        tags.append("高对话驱动")
    elif dialogue_rate <= 0.15:
        tags.append("叙述驱动")
    else:
        tags.append("叙述-对话均衡")

    if punct.get("！", 0) >= 0.18:
        tags.append("情绪外放")
    if punct.get("？", 0) >= 0.15:
        tags.append("高疑问张力")
    if punct.get("；", 0) >= 0.08:
        tags.append("复句逻辑化")

    return tags


def ensure_file(path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(f"# {title}\n\n", encoding="utf-8")


def upsert_section(path: Path, section_title: str, body: str, default_title: str) -> None:
    ensure_file(path, default_title)
    text = path.read_text(encoding="utf-8", errors="ignore")
    header = f"## {section_title}"
    block = f"{header}\n{body.strip()}\n\n"

    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == header:
            start = i
            break

    if start is None:
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + block
        path.write_text(text, encoding="utf-8")
        return

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break

    replaced = lines[:start] + block.strip("\n").splitlines() + [""] + lines[end:]
    path.write_text("\n".join(replaced).rstrip() + "\n", encoding="utf-8")


def render_profile_md(profile_name: str, sample_paths: List[str], metrics: Dict[str, object]) -> str:
    top_phrases_str = "、".join([f"{w}({c})" for w, c in metrics["top_phrases"]]) or "无"
    style_tags_str = "、".join(metrics["style_tags"]) or "无"

    return f"""# 风格档案：{profile_name}

- 生成时间：{metrics['generated_at']}
- 样章数量：{len(sample_paths)}
- 样章路径：\n  - """ + "\n  - ".join(sample_paths) + f"""

## 核心指标
- 总中文字符：{metrics['total_cjk_chars']}
- 句子数：{metrics['sentence_count']}
- 平均句长：{metrics['avg_sentence_chars']}
- 段落数：{metrics['paragraph_count']}
- 平均段长：{metrics['avg_paragraph_chars']}
- 对话占比：{metrics['dialogue_ratio']}
- 叙述视角：{metrics['perspective_label']}

## 标点密度（每句）
- 逗号：{metrics['punctuation_density']['，']}
- 句号：{metrics['punctuation_density']['。']}
- 感叹号：{metrics['punctuation_density']['！']}
- 问号：{metrics['punctuation_density']['？']}
- 分号：{metrics['punctuation_density']['；']}
- 冒号：{metrics['punctuation_density']['：']}
- 省略号：{metrics['punctuation_density']['…']}

## 高频短语（2-3字）
{top_phrases_str}

## 风格标签
{style_tags_str}

## 写作动作建议
1. 句长控制：以 {metrics['avg_sentence_chars']} 字为中枢，上下浮动不超过 30%。
2. 对话比例：保持在 {metrics['dialogue_ratio']} 附近，偏离时优先修正文体而非剧情。
3. 视角一致：默认按“{metrics['perspective_label']}”写作，切视角必须给章节理由。
"""


def update_global_index(index_file: Path, profile_name: str, profile_path: Path, generated_at: str) -> None:
    ensure_file(index_file, "全局风格库索引")
    text = index_file.read_text(encoding="utf-8", errors="ignore")
    lines = [ln for ln in text.splitlines() if ln.strip()]

    marker = f"- {profile_name} | {profile_path} | 更新于 {generated_at}"

    filtered = []
    for ln in lines:
        if ln.startswith(f"- {profile_name} | "):
            continue
        filtered.append(ln)

    if not filtered or not filtered[0].startswith("# "):
        filtered = ["# 全局风格库索引", "", "> 由 style_fingerprint.py 自动维护。按“最新更新时间”降序使用。", ""] + filtered

    filtered.append(marker)
    index_file.write_text("\n".join(filtered).rstrip() + "\n", encoding="utf-8")


def collect_metrics(text: str, top_n: int) -> Dict[str, object]:
    total_cjk = len(CJK_RE.findall(text))
    s = sentence_stats(text)
    p = paragraph_stats(text)
    d_ratio = dialogue_ratio(text, total_cjk)
    punct = punctuation_density(text, s["sentence_count"])
    pers = perspective(text)

    return {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_cjk_chars": total_cjk,
        "sentence_count": s["sentence_count"],
        "avg_sentence_chars": s["avg_sentence_chars"],
        "max_sentence_chars": s["max_sentence_chars"],
        "paragraph_count": p["paragraph_count"],
        "avg_paragraph_chars": p["avg_paragraph_chars"],
        "dialogue_ratio": d_ratio,
        "punctuation_density": punct,
        "perspective_label": pers["label"],
        "first_person_per_10k": pers["first_person_per_10k"],
        "third_person_per_10k": pers["third_person_per_10k"],
        "top_phrases": top_phrases(text, top_n),
        "style_tags": style_tags(s["avg_sentence_chars"], d_ratio, punct),
    }


def update_project_files(project_root: Path, profile_name: str, slug: str, profile_md: str) -> Dict[str, str]:
    outputs = {}

    profile_file = project_root / "00_memory" / "style_profiles" / f"{slug}.md"
    profile_file.parent.mkdir(parents=True, exist_ok=True)
    profile_file.write_text(profile_md, encoding="utf-8")
    outputs["project_profile"] = str(profile_file)

    anchor_file = project_root / "00_memory" / "style_anchor.md"
    anchor_body = f"""- 当前生效风格：{profile_name}
- 最近更新：自动由 style_fingerprint.py 生成
- 建议：写前检查句长、对话占比、叙述视角一致性。
"""
    upsert_section(anchor_file, f"当前生效风格：{profile_name}", anchor_body, "风格锚点")
    outputs["style_anchor"] = str(anchor_file)

    kb_file = project_root / "02_knowledge_base" / "12_style_skills.md"
    kb_body = f"""- 风格名：{profile_name}
- 复用文件：`00_memory/style_profiles/{slug}.md`
- 使用时机：开新卷、换题材、风格漂移修复。
- 必做动作：写前读取风格标签；写后做偏移检查。
"""
    upsert_section(kb_file, f"风格技能：{profile_name}", kb_body, "写作风格技能库")
    outputs["knowledge_style"] = str(kb_file)

    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="提取样章风格并沉淀为跨项目可复用风格档案")
    parser.add_argument("files", nargs="+", help="样章文件路径（支持多个）")
    parser.add_argument("--profile-name", required=True, help="风格名称，例如：番茄快节奏玄幻")
    parser.add_argument("--project-root", help="小说项目根目录；提供后会同步写入项目知识库")
    parser.add_argument(
        "--global-library",
        default=str(Path.home() / ".codex" / "skills" / "novel-creator-skill" / "assets" / "style_library"),
        help="全局风格库存储目录",
    )
    parser.add_argument("--top-n", type=int, default=12, help="高频短语数量")
    parser.add_argument("--emit-json", help="额外导出 JSON 结果路径")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    sample_paths = [Path(p).expanduser().resolve() for p in args.files]
    text, missing = read_texts(sample_paths)

    if missing:
        print("以下样章不存在：")
        for m in missing:
            print(f"- {m}")
        return 2

    if not text.strip():
        print("输入文本为空，无法提取风格。")
        return 3

    metrics = collect_metrics(text, args.top_n)
    profile_name = args.profile_name.strip()
    slug = slugify(profile_name)

    global_dir = Path(args.global_library).expanduser().resolve()
    global_dir.mkdir(parents=True, exist_ok=True)
    global_profile = global_dir / f"{slug}.md"

    md = render_profile_md(profile_name, [str(p) for p in sample_paths], metrics)
    global_profile.write_text(md, encoding="utf-8")

    index_file = global_dir / "index.md"
    update_global_index(index_file, profile_name, global_profile, metrics["generated_at"])

    outputs = {
        "global_profile": str(global_profile),
        "global_index": str(index_file),
    }

    if args.project_root:
        project_root = Path(args.project_root).expanduser().resolve()
        outputs.update(update_project_files(project_root, profile_name, slug, md))

    result = {
        "profile_name": profile_name,
        "slug": slug,
        "metrics": metrics,
        "outputs": outputs,
    }

    if args.emit_json:
        json_path = Path(args.emit_json).expanduser().resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        outputs["json"] = str(json_path)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
