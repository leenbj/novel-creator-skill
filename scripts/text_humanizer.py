#!/usr/bin/env python3
"""文本人性化处理器 - 检测并消除中文小说中的 AI 写作痕迹。

基于 humanizer skill (https://github.com/blader/humanizer) 的方法论，
专为中文网络小说创作场景定制，检测 7 大类 AI 写作模式，
输出结构化报告和两遍式润色 prompt。

子命令：
  detect   --chapter-file <path> [--project-root <path>]
           扫描章节文件，输出 JSON 检测报告
  report   --chapter-file <path>
           输出人类可读的 AI 痕迹报告（Markdown）
  prompt   --chapter-file <path> [--mode gate|full]
           生成供 Claude 执行的两遍式人性化润色 prompt
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# AI 模式库（中文小说专用）
# ---------------------------------------------------------------------------

# Category 1 - AI 高频词汇（直接命中即扣分）
AI_VOCAB: List[Tuple[str, str]] = [
    # 比喻/感知套话
    ("不禁", "情感反应套话，角色常失去主动性"),
    ("仿佛", "过度比喻词，每段出现超过1次即AI特征"),
    ("宛如", "过度比喻词"),
    ("宛若", "过度比喻词"),
    ("恍若", "过度比喻词"),
    ("仿若", "过度比喻词"),
    ("好似", "过度比喻词"),
    # 视觉描写套话
    ("映入眼帘", "陈词滥调视觉过渡"),
    ("涌入眼帘", "陈词滥调视觉过渡"),
    ("跃入眼帘", "陈词滥调视觉过渡"),
    # 时间膨胀
    ("此时此刻", "时间强调膨胀"),
    ("就在此时", "时间强调膨胀"),
    ("恰在此时", "时间强调膨胀"),
    ("在这一刻", "时间强调膨胀"),
    # 内心独白套话
    ("心中暗道", "内心独白滥用"),
    ("心中暗想", "内心独白滥用"),
    ("暗自思忖", "内心独白滥用"),
    ("心中一动", "内心独白滥用"),
    ("心中一凛", "内心独白滥用"),
    ("心念一动", "内心独白滥用"),
    # 对话标签套话
    ("沉声道", "对话标签套话，可简化为「说」"),
    ("淡淡地说", "对话标签套话"),
    ("轻声道", "对话标签套话"),
    ("缓缓说道", "对话标签套话"),
    ("淡然道", "对话标签套话"),
    ("漠然道", "对话标签套话"),
    # 反应/动作套话
    ("脸色一变", "反应套话"),
    ("神情一凛", "反应套话"),
    ("眉头微皱", "反应套话"),
    ("身形一顿", "动作套话"),
    ("脚步一顿", "动作套话"),
    ("身子微微一颤", "动作套话"),
    # 外貌描写套话
    ("目光如炬", "眼睛描写套话"),
    ("目光深邃", "眼睛描写套话"),
    ("深邃的眸子", "眼睛描写套话"),
    ("嘴角微扬", "微笑描写套话（AI特征极强）"),
    ("勾起一抹弧度", "微笑描写套话（AI特征极强）"),
    ("嘴角勾起", "微笑描写套话"),
    # 过渡套话
    ("只见", "场景过渡套话"),
    ("但见", "场景过渡套话"),
    # 情感套话
    ("感慨良多", "情感套话"),
    ("百感交集", "情感套话"),
    ("不禁感叹", "情感套话"),
    # 主体性剥夺
    ("不由自主", "主体性剥夺词，角色变成被动对象"),
    ("不由得", "主体性剥夺词"),
    ("情不自禁", "主体性剥夺词"),
]

# Category 2 - 弱化副词泛滥（单个无害，密集使用是AI特征）
WEAK_ADVERBS: List[str] = [
    "微微", "淡淡", "缓缓", "轻轻", "悄悄", "悄然",
    "深深", "静静", "慢慢", "默默", "暗暗", "隐隐",
    "渐渐", "徐徐", "徐徐地",
]
WEAK_ADVERB_DENSITY_THRESHOLD = 3  # 每千字超过此数量即触发

# Category 3 - 意义膨胀（重要性/历史性夸大）
SIGNIFICANCE_PHRASES: List[Tuple[str, str]] = [
    ("意义深远", "意义膨胀"),
    ("影响深远", "意义膨胀"),
    ("意义非凡", "意义膨胀"),
    ("令人叹为观止", "意义膨胀"),
    ("叹为观止", "意义膨胀"),
    ("前所未有", "意义膨胀"),
    ("史无前例", "意义膨胀"),
    ("意味深长", "意义膨胀"),
    ("深入人心", "意义膨胀"),
    ("可谓", "意义膨胀：用繁替简，可改为「是」"),
    ("堪称", "意义膨胀：用繁替简"),
    ("不得不说", "评论性插入，破坏叙事流"),
    ("值得一提的是", "评论性插入"),
    ("不容忽视", "评论性插入"),
    ("毋庸置疑", "评论性插入"),
    ("不容置疑", "评论性插入"),
]

# Category 4 - 通用结论套话（小说结尾常见）
CONCLUSION_CLICHÉS: List[str] = [
    "展望未来", "未来可期", "前途无量",
    "前景广阔", "大有可为", "方兴未艾",
    "相信未来", "充满希望", "充满期待",
    "前程似锦", "大展宏图",
]

# Category 5 - 段落首句总结模式（从正文提取后检测）
PARA_SUMMARY_STARTERS: List[str] = [
    "总的来说", "总而言之", "综上所述",
    "由此可见", "不难看出", "显而易见",
    "值得注意的是", "不容忽视的是",
    "更重要的是", "尤其值得一提",
    "事实上", "实际上", "说到底",
    "换句话说", "简而言之",
]

# Category 6 - 翻译腔/正式语体入侵小说（网文里出现是异物）
FORMAL_INTRUSION: List[Tuple[str, str]] = [
    ("于是乎", "翻译腔正式语体"),
    ("然而事实上", "正式论述语体入侵"),
    ("然而实际上", "正式论述语体入侵"),
    ("理所当然", "正式论述语体入侵"),
    ("一方面", "论文结构词入侵小说"),
    ("另一方面", "论文结构词入侵小说"),
    ("与此同时", "正式新闻语体"),
    ("从而", "正式逻辑连接词"),
    ("因而", "正式逻辑连接词"),
    ("诚然", "正式让步连词"),
]

# Category 7 - 排比三连（连续三个相同句式）
# 通过正则检测"A、B、C"或"A，B，C"中结构相似的片段

# ---------------------------------------------------------------------------
# 检测核心
# ---------------------------------------------------------------------------

_PARA_SEP = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"[。！？!?…]+")
_THOUSAND_CHARS = 1000


def _strip_markdown(text: str) -> str:
    """去除标题、列表等 Markdown 标记，只保留正文。"""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(("- ", "* ", "1.", "2.", "3.")):
            continue
        lines.append(line)
    return "\n".join(lines)


def _extract_context(text: str, pos: int, window: int = 40) -> str:
    """截取命中位置前后 window 字符作为上下文。"""
    start = max(0, pos - window)
    end = min(len(text), pos + window)
    snippet = text[start:end].replace("\n", " ")
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def detect_patterns(text: str) -> Dict:
    """对章节正文执行全类别检测，返回结构化结果。"""
    body = _strip_markdown(text)
    pure = re.sub(r"\s+", "", body)
    char_count = max(len(pure), 1)
    per_thousand = char_count / _THOUSAND_CHARS

    # --- Category 1: AI 高频词汇 ---
    vocab_hits: List[Dict] = []
    total_vocab_count = 0
    for phrase, reason in AI_VOCAB:
        positions = [m.start() for m in re.finditer(re.escape(phrase), body)]
        if positions:
            count = len(positions)
            total_vocab_count += count
            # 截取前3个上下文示例
            examples = [_extract_context(body, p) for p in positions[:3]]
            vocab_hits.append({
                "phrase": phrase,
                "count": count,
                "reason": reason,
                "examples": examples,
            })
    vocab_density = total_vocab_count / per_thousand if per_thousand else 0

    # --- Category 2: 弱化副词密度 ---
    adverb_hits: List[Dict] = []
    total_adverb_count = 0
    for adv in WEAK_ADVERBS:
        positions = [m.start() for m in re.finditer(re.escape(adv), body)]
        if positions:
            count = len(positions)
            total_adverb_count += count
            adverb_hits.append({"adverb": adv, "count": count})
    adverb_density = total_adverb_count / per_thousand if per_thousand else 0
    adverb_flagged = adverb_density > WEAK_ADVERB_DENSITY_THRESHOLD

    # --- Category 3: 意义膨胀 ---
    significance_hits: List[Dict] = []
    for phrase, reason in SIGNIFICANCE_PHRASES:
        positions = [m.start() for m in re.finditer(re.escape(phrase), body)]
        if positions:
            examples = [_extract_context(body, p) for p in positions[:2]]
            significance_hits.append({
                "phrase": phrase,
                "count": len(positions),
                "reason": reason,
                "examples": examples,
            })

    # --- Category 4: 通用结论套话 ---
    conclusion_hits: List[str] = [p for p in CONCLUSION_CLICHÉS if p in body]

    # --- Category 5: 段落首句总结模式 ---
    paragraphs = [p.strip() for p in _PARA_SEP.split(body) if p.strip()]
    summary_para_count = 0
    summary_examples: List[str] = []
    for para in paragraphs:
        first_sentence = re.split(r"[，。！？]", para)[0]
        for starter in PARA_SUMMARY_STARTERS:
            if first_sentence.startswith(starter):
                summary_para_count += 1
                summary_examples.append(first_sentence[:60])
                break
    essay_structure_ratio = summary_para_count / max(len(paragraphs), 1)

    # --- Category 6: 翻译腔/正式语体入侵 ---
    formal_hits: List[Dict] = []
    for phrase, reason in FORMAL_INTRUSION:
        positions = [m.start() for m in re.finditer(re.escape(phrase), body)]
        if positions:
            formal_hits.append({
                "phrase": phrase,
                "count": len(positions),
                "reason": reason,
                "examples": [_extract_context(body, p) for p in positions[:2]],
            })

    # --- Category 7: 排比三连检测 ---
    # 检测"A、B、C"模式中 A/B/C 结尾字符相同（同结构排比）
    trio_pattern = re.compile(r"[\u4e00-\u9fff]{2,8}[、，][^\n、，。！？]{2,8}[、，][^\n、，。！？]{2,8}[。，！]")
    trio_matches = trio_pattern.findall(body)
    trio_count = len(trio_matches)
    trio_examples = trio_matches[:3]

    # --- 综合评分 ---
    issues: List[str] = []
    if vocab_hits:
        top_phrases = sorted(vocab_hits, key=lambda x: x["count"], reverse=True)[:5]
        top_names = [f'{h["phrase"]}(×{h["count"]})' for h in top_phrases]
        issues.append(f"AI高频词：{', '.join(top_names)}")
    if adverb_flagged:
        issues.append(f"弱化副词密度过高：每千字 {adverb_density:.1f} 个（阈值 {WEAK_ADVERB_DENSITY_THRESHOLD}）")
    if significance_hits:
        issues.append(f"意义膨胀词：{', '.join(h['phrase'] for h in significance_hits[:4])}")
    if conclusion_hits:
        issues.append(f"通用结论套话：{', '.join(conclusion_hits)}")
    if essay_structure_ratio > 0.25:
        issues.append(f"论文式段落结构：{summary_para_count}/{len(paragraphs)} 段以总结句开头")
    if formal_hits:
        issues.append(f"正式语体入侵：{', '.join(h['phrase'] for h in formal_hits[:3])}")
    if trio_count > 3:
        issues.append(f"排比三连过多：{trio_count} 处")

    # 严重程度评级
    issue_count = len(issues)
    severity = "low" if issue_count <= 1 else ("medium" if issue_count <= 3 else "high")

    return {
        "char_count": char_count,
        "paragraph_count": len(paragraphs),
        "severity": severity,
        "issue_count": issue_count,
        "issues": issues,
        "details": {
            "ai_vocab": {
                "total_count": total_vocab_count,
                "density_per_thousand": round(vocab_density, 2),
                "hits": vocab_hits,
            },
            "weak_adverbs": {
                "total_count": total_adverb_count,
                "density_per_thousand": round(adverb_density, 2),
                "flagged": adverb_flagged,
                "hits": adverb_hits,
            },
            "significance_inflation": {
                "hits": significance_hits,
            },
            "conclusion_clichés": {
                "hits": conclusion_hits,
            },
            "essay_structure": {
                "flagged_paragraphs": summary_para_count,
                "total_paragraphs": len(paragraphs),
                "ratio": round(essay_structure_ratio, 3),
                "examples": summary_examples[:3],
            },
            "formal_intrusion": {
                "hits": formal_hits,
            },
            "rule_of_three": {
                "count": trio_count,
                "examples": trio_examples,
            },
        },
    }


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------

def build_text_report(result: Dict, chapter_name: str) -> str:
    """将 detect 结果转为人类可读 Markdown 报告。"""
    severity_label = {"low": "轻微", "medium": "中等", "high": "严重"}.get(
        result["severity"], result["severity"]
    )
    lines = [
        f"# 去AI味检测报告",
        f"",
        f"- 章节：{chapter_name}",
        f"- 字符数：{result['char_count']}",
        f"- 段落数：{result['paragraph_count']}",
        f"- AI痕迹严重程度：**{severity_label}**（发现 {result['issue_count']} 类问题）",
        f"",
    ]

    if not result["issues"]:
        lines.append("未发现显著 AI 写作痕迹，本章人性化程度良好。")
        return "\n".join(lines)

    lines.append("## 发现的问题")
    for i, issue in enumerate(result["issues"], 1):
        lines.append(f"{i}. {issue}")
    lines.append("")

    # AI高频词详情
    vocab = result["details"]["ai_vocab"]
    if vocab["hits"]:
        lines.append("## AI 高频词详情")
        lines.append(f"总命中：{vocab['total_count']} 次，密度：每千字 {vocab['density_per_thousand']} 次")
        lines.append("")
        for hit in sorted(vocab["hits"], key=lambda x: x["count"], reverse=True)[:8]:
            lines.append(f"- **{hit['phrase']}** ×{hit['count']}：{hit['reason']}")
            for ex in hit["examples"][:1]:
                lines.append(f"  > {ex}")
        lines.append("")

    # 弱化副词
    adverb = result["details"]["weak_adverbs"]
    if adverb["flagged"]:
        lines.append("## 弱化副词泛滥")
        lines.append(f"密度：每千字 {adverb['density_per_thousand']} 次（阈值 {WEAK_ADVERB_DENSITY_THRESHOLD}）")
        top_adverbs = sorted(adverb["hits"], key=lambda x: x["count"], reverse=True)[:6]
        lines.append(", ".join(f'{h["adverb"]}(×{h["count"]})' for h in top_adverbs))
        lines.append("")

    # 意义膨胀
    sig = result["details"]["significance_inflation"]
    if sig["hits"]:
        lines.append("## 意义膨胀词")
        for hit in sig["hits"]:
            lines.append(f"- **{hit['phrase']}** ×{hit['count']}：{hit['reason']}")
        lines.append("")

    # 段落结构
    es = result["details"]["essay_structure"]
    if es["ratio"] > 0.25:
        lines.append("## 论文式段落结构（总结句开头）")
        lines.append(f"{es['flagged_paragraphs']}/{es['total_paragraphs']} 段以总结/评论句开头（论文写法入侵小说）")
        for ex in es["examples"]:
            lines.append(f"- 示例：{ex}")
        lines.append("")

    # 排比三连
    trio = result["details"]["rule_of_three"]
    if trio["count"] > 3:
        lines.append("## 排比三连过多")
        lines.append(f"发现 {trio['count']} 处三元排比结构")
        for ex in trio["examples"][:2]:
            lines.append(f"- {ex}")
        lines.append("")

    lines.append("## 润色建议")
    lines.append("执行 `/校稿` 时，请优先针对以上问题进行两遍式润色：")
    lines.append("1. **第一遍**：逐一清除上述模式，替换为具体行动/对话/细节")
    lines.append('2. **审查**：问自己\u300c哪些地方还是明显AI生成的\uff1f\u300d并列出')
    lines.append("3. **第二遍**：针对审查列出的剩余问题再次修改")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 两遍式润色 Prompt 生成
# ---------------------------------------------------------------------------

_HUMANIZE_PROMPT_TEMPLATE = """\
## 校稿任务：去除 AI 写作痕迹

本章已通过自动检测，发现以下 AI 写作特征：

{issue_summary}

---

### 执行方式：两遍式润色（来源：humanizer 方法论）

**第一遍：清除 AI 模式**

针对以下类型逐段修改，用具体细节替代抽象套话：

**A. AI高频词替换原则**
{vocab_guidance}

**B. 弱化副词瘦身**
{adverb_guidance}

**C. 意义膨胀处理**
把"意义深远"、"可谓"、"前所未有"等改为具体事实描述。
例：~~"这次交谈意义深远"~~ → "那天之后，他改变了用兵的节奏"

**D. 段落结构调整**
消除以总结句开头的段落，改为以行动/感知/对话开头。
例：~~"不难看出，他已下定决心"~~ → 直接写他做了什么。

**E. 通用结论改写**
末尾不用"未来可期"类结语，改为具体的悬念或行动钩子。

---

**第二遍：审查剩余 AI 味**

完成第一遍后，问自己：
> "这段文字哪些地方还是明显 AI 生成的感觉？"

列出 3-5 条具体问题，然后针对它们再次修改。

判断标准（有以下任一即需修改）：
- 每句话节奏相同、长度相近
- 情感表达依赖套话而非具体细节
- 角色反应都是被动的（"不禁"、"不由"）
- 段落间过渡依赖"此时"、"与此同时"

---

### 输出要求

1. 给出润色后的完整章节正文
2. 不改变剧情内容，只改写表达方式
3. 保留所有章节结构（标题等）
4. 修改量建议：字数变化控制在 ±10% 以内
"""

_NO_ISSUES_PROMPT = """\
## 校稿任务：精细润色

本章经自动检测，未发现显著 AI 写作痕迹，整体质量良好。

执行精细润色：

1. **节奏检查**：阅读每段，找出连续三句以上等长的段落并调整节奏
2. **具体化检查**：把任何模糊的情感/状态描述替换为具体行动或细节
3. **结尾钩子**：末段是否留有足够的悬念或行动张力
4. **个人风格**：全篇是否有独特的叙事声音，还是过于"中性标准"

完成后输出修改版本（变化量建议控制在 5% 以内）。
"""


def build_humanize_prompt(result: Dict, chapter_text: str) -> str:
    """根据检测结果生成两遍式润色 prompt。"""
    if not result["issues"]:
        return _NO_ISSUES_PROMPT

    # 汇总问题
    issue_lines = "\n".join(f"- {issue}" for issue in result["issues"])

    # AI词汇具体指导
    vocab = result["details"]["ai_vocab"]
    if vocab["hits"]:
        top = sorted(vocab["hits"], key=lambda x: x["count"], reverse=True)[:6]
        vocab_lines = []
        for h in top:
            vocab_lines.append(f"- **{h['phrase']}**（×{h['count']}）：{h['reason']}")
            if h["examples"]:
                vocab_lines.append(f'  出现示例："{h["examples"][0]}"')
        vocab_guidance = "\n".join(vocab_lines)
    else:
        vocab_guidance = "本章未发现 AI 高频词问题。"

    # 副词指导
    adverb = result["details"]["weak_adverbs"]
    if adverb["flagged"]:
        top_adv = sorted(adverb["hits"], key=lambda x: x["count"], reverse=True)[:5]
        adverb_guidance = (
            f"以下弱化副词密度过高（每千字 {adverb['density_per_thousand']} 次）：\n"
            + "\n".join(f'- {h["adverb"]} ×{h["count"]}' for h in top_adv)
            + "\n删除大部分，保留确有必要的即可。"
        )
    else:
        adverb_guidance = "弱化副词密度正常，保持即可。"

    prompt = _HUMANIZE_PROMPT_TEMPLATE.format(
        issue_summary=issue_lines,
        vocab_guidance=vocab_guidance,
        adverb_guidance=adverb_guidance,
    )

    # 附上章节正文（截断超长内容）
    chapter_preview = chapter_text[:8000] if len(chapter_text) > 8000 else chapter_text
    if len(chapter_text) > 8000:
        chapter_preview += "\n\n[... 正文已截断，请使用 Read 工具读取完整文件 ...]"

    return prompt + f"\n\n---\n\n### 待润色章节正文\n\n{chapter_preview}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_chapter(chapter_file: str) -> Tuple[str, Path]:
    path = Path(chapter_file).expanduser().resolve()
    if not path.exists():
        print(json.dumps({"ok": False, "error": f"文件不存在: {chapter_file}"}), flush=True)
        sys.exit(1)
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}), flush=True)
        sys.exit(1)
    return text, path


def cmd_detect(args: argparse.Namespace) -> None:
    text, path = _load_chapter(args.chapter_file)
    result = detect_patterns(text)
    output = {
        "ok": True,
        "chapter_file": str(path),
        "chapter_name": path.name,
        **result,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_report(args: argparse.Namespace) -> None:
    text, path = _load_chapter(args.chapter_file)
    result = detect_patterns(text)
    report = build_text_report(result, path.name)
    print(json.dumps({
        "ok": True,
        "chapter_file": str(path),
        "severity": result["severity"],
        "report": report,
    }, ensure_ascii=False, indent=2))


def cmd_prompt(args: argparse.Namespace) -> None:
    text, path = _load_chapter(args.chapter_file)
    result = detect_patterns(text)
    prompt = build_humanize_prompt(result, text)
    print(json.dumps({
        "ok": True,
        "chapter_file": str(path),
        "severity": result["severity"],
        "issue_count": result["issue_count"],
        "prompt": prompt,
    }, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="文本人性化处理器 - 检测并消除 AI 写作痕迹"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_detect = sub.add_parser("detect", help="检测章节中的 AI 写作模式，输出 JSON 报告")
    p_detect.add_argument("--chapter-file", required=True, help="章节文件路径")
    p_detect.add_argument("--project-root", default=None, help="项目根目录（可选）")

    p_report = sub.add_parser("report", help="输出人类可读的 Markdown 检测报告")
    p_report.add_argument("--chapter-file", required=True, help="章节文件路径")

    p_prompt = sub.add_parser("prompt", help="生成两遍式润色 prompt 供 Claude 执行")
    p_prompt.add_argument("--chapter-file", required=True, help="章节文件路径")

    return p.parse_args()


def main() -> int:
    args = parse_args()
    dispatch = {"detect": cmd_detect, "report": cmd_report, "prompt": cmd_prompt}
    dispatch[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
