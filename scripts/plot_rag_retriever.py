#!/usr/bin/env python3
"""轻量剧情检索器（RAG 风格，零外部依赖）。

目标：将人物关系、剧情走向与章节内容建立可检索关联，
在写新剧情前自动给出“应回读哪些章节”的上下文建议。
"""

import argparse
import datetime as dt
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

STOPWORDS = {
    "我们", "你们", "他们", "她们", "它们", "这个", "那个", "一种", "已经", "因为", "所以", "如果",
    "但是", "然后", "自己", "不是", "不会", "就是", "还是", "一个", "一些", "可以", "时候", "什么",
    "怎么", "这样", "那样", "起来", "进去", "出来", "一下", "一样", "以及", "并且", "或者", "然后",
}

TRIGGER_KEYWORDS = {
    "冲突", "反转", "伏笔", "回收", "真相", "背叛", "联盟", "新角色", "时间线", "回忆",
    "穿越", "死亡", "复活", "势力", "升级", "突破", "决战", "危机", "转折", "悬念",
}

LIGHT_SCENE_KEYWORDS = {
    "日常", "过渡", "环境描写", "吃饭", "赶路", "休整", "闲聊", "铺垫",
}


def slugify(text: str) -> str:
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", text).strip("-")
    return s or "chapter"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> List[str]:
    # 中文采用 2~4 字片段，英文按词；保持轻量可解释。
    tokens: List[str] = []
    for seq in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        n = len(seq)
        for k in (2, 3, 4):
            if n < k:
                continue
            for i in range(n - k + 1):
                t = seq[i : i + k]
                if t in STOPWORDS:
                    continue
                tokens.append(t)
    tokens += [w.lower() for w in re.findall(r"[A-Za-z]{3,}", text)]
    return tokens


def parse_chapter_no(filename: str) -> int:
    m = re.search(r"第(\d+)章", filename)
    return int(m.group(1)) if m else 0


def normalize_query(query: str) -> str:
    return normalize_text(query)


def analyze_query_trigger(query: str, names: List[str]) -> Dict[str, object]:
    q = normalize_query(query)
    entities = [n for n in names if n in q]
    keyword_hits = sorted([k for k in TRIGGER_KEYWORDS if k in q])
    light_hits = sorted([k for k in LIGHT_SCENE_KEYWORDS if k in q])
    long_query = len(q) >= 18

    should = bool(entities or keyword_hits or (long_query and not light_hits))
    reason = []
    if entities:
        reason.append(f"命中角色:{','.join(entities)}")
    if keyword_hits:
        reason.append(f"命中剧情关键词:{','.join(keyword_hits[:4])}")
    if long_query and not light_hits:
        reason.append("查询描述较长，判定为复杂剧情")
    if light_hits and not entities and not keyword_hits:
        reason.append(f"仅命中轻场景关键词:{','.join(light_hits)}")
    if not reason:
        reason.append("未命中角色/剧情关键词，判定为可跳过检索")

    return {
        "should_trigger": should,
        "entities": entities,
        "keyword_hits": keyword_hits,
        "light_hits": light_hits,
        "query_length": len(q),
        "reason": reason,
    }


def load_character_names(project_root: Path) -> List[str]:
    p = project_root / "00_memory" / "character_tracker.md"
    if not p.exists():
        return []
    txt = read_text(p)

    names = set()

    # 1) 表格第一列
    for line in txt.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        candidate = cells[0]
        if candidate in {"人物", "角色", "姓名", "---", ""}:
            continue
        if re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9_·]{2,20}", candidate):
            names.add(candidate)

    # 2) “姓名: xxx”形式
    for m in re.finditer(r"(?:姓名|角色)\s*[:：]\s*([\u4e00-\u9fffA-Za-z0-9_·]{2,20})", txt):
        names.add(m.group(1).strip())

    # 去噪
    bad = {"当前状态", "关系", "位置", "目标", "变化", "章节"}
    names = {n for n in names if n not in bad}
    return sorted(names)


def extract_relation_snippets(path: Path, terms: List[str], window: int = 2, max_hits: int = 8) -> List[str]:
    if not path.exists() or not terms:
        return []
    lines = read_text(path).splitlines()
    hits: List[str] = []
    used = set()
    seen_blocks = set()
    last_end = -1
    for i, line in enumerate(lines):
        if not any(t in line for t in terms):
            continue
        if i <= last_end:
            continue
        start = max(0, i - window)
        end = min(len(lines), i + window + 1)
        key = (start, end)
        if key in used:
            continue
        used.add(key)
        block = "\n".join(lines[start:end]).strip()
        normalized_lines = []
        for ln in block.splitlines():
            s = ln.strip()
            if re.fullmatch(r"\|\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?", s):
                continue
            if s:
                normalized_lines.append(s)
        norm_key = " || ".join(normalized_lines)

        if block and norm_key and norm_key not in seen_blocks:
            hits.append(block)
            seen_blocks.add(norm_key)
            last_end = end - 1
        if len(hits) >= max_hits:
            break
    return hits


def split_passages(text: str, max_chars: int = 360) -> List[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if not paragraphs:
        paragraphs = [normalize_text(text)]

    passages: List[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            passages.append(para)
            continue
        # 超长段落按句子切片，避免整段回读。
        pieces = [s.strip() for s in re.split(r"(?<=[。！？!?])", para) if s.strip()]
        buf = ""
        for piece in pieces:
            if len(buf) + len(piece) <= max_chars:
                buf += piece
            else:
                if buf:
                    passages.append(buf)
                buf = piece
        if buf:
            passages.append(buf)
    return passages


def extract_location_candidates(text: str, top_n: int = 6) -> List[str]:
    # 轻量地点抽取：匹配“在X/到X/从X”及“X站/港/城/街/村/馆”等后缀。
    hits = []
    for m in re.finditer(r"(?:在|到|从|回到)([\u4e00-\u9fff]{2,12}(?:站台|车站|港区|港|城|城北|街|巷|村|楼|馆|厂|桥|学校|医院))", text):
        hits.append(m.group(1))
    for m in re.finditer(r"([\u4e00-\u9fff]{2,10}(?:站台|车站|港区|港|城|街|巷|村|楼|馆|厂|桥|学校|医院))", text):
        hits.append(m.group(1))
    if not hits:
        return []
    counter = Counter(hits)
    return [x for x, _ in counter.most_common(top_n)]


def infer_conflict_level(text: str) -> str:
    high = {"决战", "追杀", "爆炸", "死亡", "复活", "背叛", "崩溃", "危机", "反转"}
    medium = {"冲突", "争执", "对峙", "潜入", "调查", "追踪", "怀疑", "联盟"}
    low = {"日常", "休整", "过渡", "闲聊", "铺垫"}
    if any(k in text for k in high):
        return "high"
    if any(k in text for k in medium):
        return "medium"
    if any(k in text for k in low):
        return "low"
    return "unknown"


def build_chapter_meta(
    chapter_path: Path,
    text: str,
    chapter_no: int,
    names: List[str],
    retrieval_dir: Path,
) -> Dict[str, object]:
    entities = sorted([n for n in names if n in text])
    tokens = tokenize(text)
    top_tokens = [k for k, _ in Counter(tokens).most_common(18)]
    events = [k for k in TRIGGER_KEYWORDS if k in text][:10]
    locations = extract_location_candidates(text, top_n=6)
    foreshadow_refs = []
    for m in re.finditer(r"(伏笔|线索|坐标|编号|暗号|名单)[^。！？\n]{0,32}", text):
        frag = normalize_text(m.group(0))
        if frag and frag not in foreshadow_refs:
            foreshadow_refs.append(frag)
        if len(foreshadow_refs) >= 6:
            break

    meta_dir = retrieval_dir / "chapter_meta"
    ensure_dir(meta_dir)
    meta_path = meta_dir / f"{slugify(chapter_path.stem)}.meta.json"

    flat = re.sub(r"\s+", " ", text).strip()
    meta = {
        "chapter_file": chapter_path.name,
        "chapter_path": str(chapter_path),
        "chapter_no": chapter_no,
        "mtime": chapter_path.stat().st_mtime,
        "summary": flat[:220],
        "entities": entities,
        "events": events,
        "locations": locations,
        "foreshadow_refs": foreshadow_refs,
        "keywords": top_tokens,
        "conflict_level": infer_conflict_level(text),
        "meta_file": str(meta_path),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def score_passage(passage: str, query_tokens: List[str], query_entities: List[str]) -> Tuple[float, Dict[str, int]]:
    p_tokens = set(tokenize(passage))
    token_overlap = len(set(query_tokens) & p_tokens)
    entity_overlap = sum(1 for e in query_entities if e in passage)
    score = entity_overlap * 3.0 + token_overlap * 1.0
    return score, {
        "token_overlap": token_overlap,
        "entity_overlap": entity_overlap,
    }


def top_passages(
    chapter_path: Path,
    query_tokens: List[str],
    query_entities: List[str],
    per_chapter: int,
    passage_max_chars: int,
) -> List[Dict[str, object]]:
    text = read_text(chapter_path)
    passages = split_passages(text)
    scored = []
    for p in passages:
        s, reason = score_passage(p, query_tokens, query_entities)
        scored.append((s, reason, p))
    scored.sort(key=lambda x: x[0], reverse=True)

    selected = [x for x in scored if x[0] > 0][:per_chapter]
    if not selected:
        selected = scored[: min(per_chapter, len(scored))]

    result = []
    for s, reason, p in selected:
        short = p if len(p) <= passage_max_chars else p[:passage_max_chars].rstrip() + "..."
        result.append({
            "score": round(s, 3),
            "reason": reason,
            "text": short,
        })
    return result


def index_signature(index: Dict[str, object]) -> str:
    docs = index.get("docs", [])
    raw = "|".join(
        f"{d.get('chapter_file','')}:{d.get('mtime',0)}"
        for d in docs
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{len(docs)}-{digest}"


def load_cache(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"entries": {}}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            return {"entries": {}}
        obj.setdefault("entries", {})
        return obj
    except Exception:
        return {"entries": {}}


def save_cache(path: Path, cache: Dict[str, object], max_entries: int = 200) -> None:
    entries = cache.get("entries", {})
    if isinstance(entries, dict) and len(entries) > max_entries:
        items = sorted(entries.items(), key=lambda kv: kv[1].get("saved_at", ""), reverse=True)
        cache["entries"] = dict(items[:max_entries])
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def make_cache_key(query: str, top_k: int, per_chapter: int, passage_max_chars: int, idx_sig: str) -> str:
    raw = f"{normalize_query(query)}|{top_k}|{per_chapter}|{passage_max_chars}|{idx_sig}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def cleanup_stale_meta_files(retrieval_dir: Path, docs: List[Dict[str, object]]) -> int:
    meta_dir = retrieval_dir / "chapter_meta"
    if not meta_dir.exists():
        return 0
    valid_files = set()
    for d in docs:
        mf = d.get("meta_file")
        if isinstance(mf, str) and mf:
            valid_files.add(Path(mf).resolve())
    removed = 0
    for p in meta_dir.glob("*.meta.json"):
        if p.resolve() not in valid_files:
            p.unlink(missing_ok=True)
            removed += 1
    return removed


def build_index(project_root: Path, keyword_top_n: int = 20, incremental: bool = True) -> Dict[str, object]:
    manuscript_dir = project_root / "03_manuscript"
    retrieval_dir = project_root / "00_memory" / "retrieval"
    ensure_dir(retrieval_dir)
    index_file = retrieval_dir / "story_index.json"

    chapters = sorted(manuscript_dir.glob("*.md"), key=lambda p: (parse_chapter_no(p.name), p.name))
    names = load_character_names(project_root)

    existing_docs: Dict[str, Dict[str, object]] = {}
    old_character_sig = ""
    if incremental and index_file.exists():
        try:
            old = json.loads(index_file.read_text(encoding="utf-8"))
            old_character_sig = str(old.get("character_sig", ""))
            for d in old.get("docs", []):
                chapter_file = str(d.get("chapter_file", ""))
                if chapter_file:
                    existing_docs[chapter_file] = d
        except Exception:
            existing_docs = {}

    character_sig = hashlib.sha1(("|".join(names)).encode("utf-8")).hexdigest()[:16]
    reuse_allowed = (old_character_sig == character_sig) if old_character_sig else True

    docs = []
    reused_docs = 0
    rebuilt_docs = 0

    for path in chapters:
        mtime = path.stat().st_mtime
        cached = existing_docs.get(path.name)
        if reuse_allowed and cached and float(cached.get("mtime", -1)) == mtime:
            doc = cached
            meta_file = doc.get("meta_file")
            if not meta_file or not Path(str(meta_file)).exists():
                text = read_text(path)
                meta = build_chapter_meta(
                    chapter_path=path,
                    text=text,
                    chapter_no=parse_chapter_no(path.name),
                    names=names,
                    retrieval_dir=retrieval_dir,
                )
                doc.update({
                    "meta_file": meta.get("meta_file"),
                    "events": meta.get("events", []),
                    "locations": meta.get("locations", []),
                    "foreshadow_refs": meta.get("foreshadow_refs", []),
                    "conflict_level": meta.get("conflict_level", "unknown"),
                })
            reused_docs += 1
        else:
            text = read_text(path)
            flat = re.sub(r"\s+", " ", text).strip()
            summary = flat[:260]

            tokens = tokenize(text)
            top_keywords = [k for k, _ in Counter(tokens).most_common(keyword_top_n)]

            hit_entities = [n for n in names if n in text]
            meta = build_chapter_meta(
                chapter_path=path,
                text=text,
                chapter_no=parse_chapter_no(path.name),
                names=names,
                retrieval_dir=retrieval_dir,
            )
            doc = {
                "chapter_file": path.name,
                "chapter_path": str(path),
                "chapter_no": parse_chapter_no(path.name),
                "mtime": mtime,
                "summary": summary,
                "entities": hit_entities,
                "keywords": top_keywords,
                "meta_file": meta.get("meta_file"),
                "events": meta.get("events", []),
                "locations": meta.get("locations", []),
                "foreshadow_refs": meta.get("foreshadow_refs", []),
                "conflict_level": meta.get("conflict_level", "unknown"),
            }
            rebuilt_docs += 1
        docs.append(doc)

    docs.sort(key=lambda d: (int(d.get("chapter_no", 0)), str(d.get("chapter_file", ""))))
    entity_map: Dict[str, List[str]] = {n: [] for n in names}
    for d in docs:
        chapter_file = str(d.get("chapter_file", ""))
        for n in d.get("entities", []):
            entity_map.setdefault(n, []).append(chapter_file)
    cleaned_meta_files = cleanup_stale_meta_files(retrieval_dir, docs)

    index = {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_root": str(project_root),
        "chapter_count": len(docs),
        "reused_docs": reused_docs,
        "rebuilt_docs": rebuilt_docs,
        "cleaned_meta_files": cleaned_meta_files,
        "character_sig": character_sig,
        "docs": docs,
    }

    (retrieval_dir / "story_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    (retrieval_dir / "entity_chapter_map.json").write_text(json.dumps(entity_map, ensure_ascii=False, indent=2), encoding="utf-8")

    return index


def score_doc_coarse(
    doc: Dict[str, object],
    query_tokens: List[str],
    query_token_set: set,
    query_entities: List[str],
    query_text: str,
) -> Tuple[float, Dict[str, object]]:
    kw = set(doc.get("keywords", []))
    ent = set(doc.get("entities", []))
    evt = set(doc.get("events", []))
    loc = set(doc.get("locations", []))

    token_overlap = len(query_token_set & kw)
    entity_overlap = len(set(query_entities) & ent)
    event_overlap = sum(1 for e in evt if e and e in query_text)
    location_overlap = sum(1 for l in loc if l and l in query_text)

    score = entity_overlap * 4.0 + event_overlap * 2.0 + location_overlap * 1.5 + token_overlap * 1.0
    reason = {
        "token_overlap": token_overlap,
        "entity_overlap": entity_overlap,
        "event_overlap": event_overlap,
        "location_overlap": location_overlap,
    }
    return score, reason


def score_doc_fine(
    doc: Dict[str, object],
    query_tokens: List[str],
    query_token_set: set,
    query_entities: List[str],
    query_text: str,
    max_no: int,
) -> Tuple[float, Dict[str, object]]:
    kw = set(doc.get("keywords", []))
    ent = set(doc.get("entities", []))
    evt = set(doc.get("events", []))
    summary = str(doc.get("summary", ""))

    token_overlap = len(query_token_set & kw)
    summary_overlap = len(query_token_set & set(tokenize(summary)))
    entity_overlap = len(set(query_entities) & ent)
    event_overlap = sum(1 for e in evt if e and e in query_text)

    chapter_no = int(doc.get("chapter_no", 0))
    recency = (chapter_no / max_no) if max_no > 0 else 0.0
    conflict_bonus = 0.2 if doc.get("conflict_level") in {"high", "medium"} else 0.0

    score = (
        entity_overlap * 3.0
        + event_overlap * 1.8
        + token_overlap * 1.0
        + summary_overlap * 0.6
        + recency * 0.3
        + conflict_bonus
    )
    reason = {
        "token_overlap": token_overlap,
        "summary_overlap": summary_overlap,
        "entity_overlap": entity_overlap,
        "event_overlap": event_overlap,
        "recency": round(recency, 3),
        "conflict_bonus": conflict_bonus,
    }
    return score, reason


def retrieve(
    index: Dict[str, object],
    project_root: Path,
    query: str,
    top_k: int,
    candidate_k: int,
    per_chapter: int,
    passage_max_chars: int,
) -> Dict[str, object]:
    docs = index.get("docs", [])
    query_tokens = tokenize(query)
    query_token_set = set(query_tokens)
    names = load_character_names(project_root)
    query_entities = [n for n in names if n in query]

    max_no = max((int(d.get("chapter_no", 0)) for d in docs), default=0)
    coarse_scored = []
    for d in docs:
        s, reason = score_doc_coarse(d, query_tokens, query_token_set, query_entities, query)
        coarse_scored.append((s, reason, d))

    coarse_scored.sort(key=lambda x: x[0], reverse=True)
    candidate_pool = [x for x in coarse_scored if x[0] > 0][:candidate_k]
    if not candidate_pool:
        candidate_pool = coarse_scored[: min(candidate_k, len(coarse_scored))]

    fine_scored = []
    for _, _, d in candidate_pool:
        s, reason = score_doc_fine(d, query_tokens, query_token_set, query_entities, query, max_no)
        fine_scored.append((s, reason, d))
    fine_scored.sort(key=lambda x: x[0], reverse=True)

    picked = [x for x in fine_scored if x[0] > 0][:top_k]
    if not picked:
        picked = fine_scored[: min(top_k, len(fine_scored))]

    character_tracker = project_root / "00_memory" / "character_tracker.md"
    relation_snippets = extract_relation_snippets(character_tracker, query_entities)

    total_chars = 0
    retrieved = []
    for s, reason, d in picked:
        passages = top_passages(
            Path(str(d.get("chapter_path", ""))),
            query_tokens,
            query_entities,
            per_chapter=per_chapter,
            passage_max_chars=passage_max_chars,
        )
        total_chars += sum(len(str(p.get("text", ""))) for p in passages)
        retrieved.append({
            "score": round(s, 3),
            "reason": reason,
            "chapter_file": d.get("chapter_file"),
            "chapter_path": d.get("chapter_path"),
            "summary": d.get("summary", ""),
            "entities": d.get("entities", []),
            "events": d.get("events", []),
            "locations": d.get("locations", []),
            "foreshadow_refs": d.get("foreshadow_refs", []),
            "passages": passages,
        })

    return {
        "query": query,
        "query_entities": query_entities,
        "index_signature": index_signature(index),
        "retrieved": retrieved,
        "relation_snippets": relation_snippets,
        "retrieval_stats": {
            "docs_total": len(docs),
            "candidate_pool": len(candidate_pool),
            "rerank_topk": len(retrieved),
            "estimated_context_chars": total_chars,
        },
    }


def write_context_md(project_root: Path, result: Dict[str, object]) -> Path:
    retrieval_dir = project_root / "00_memory" / "retrieval"
    ensure_dir(retrieval_dir)
    out = retrieval_dir / "next_plot_context.md"

    lines = []
    lines.append("# 新剧情写作上下文建议（RAG）")
    lines.append("")
    lines.append(f"- 查询：{result.get('query', '')}")
    entities = result.get("query_entities", [])
    lines.append(f"- 命中角色：{', '.join(entities) if entities else '无'}")
    if result.get("cache_hit"):
        lines.append("- 缓存命中：是（复用历史检索结果）")
    if result.get("skipped"):
        lines.append(f"- 条件触发：跳过（{'; '.join(result.get('trigger_reason', []))}）")
    stats = result.get("retrieval_stats", {})
    if stats:
        lines.append(
            "- 检索统计：候选池={candidate_pool} / 总文档={docs_total} / 估算上下文字符={estimated_context_chars}".format(
                candidate_pool=stats.get("candidate_pool", 0),
                docs_total=stats.get("docs_total", 0),
                estimated_context_chars=stats.get("estimated_context_chars", 0),
            )
        )
    lines.append("")
    lines.append("## 建议先读（固定）")
    lines.append("- 00_memory/novel_plan.md")
    lines.append("- 00_memory/novel_state.md")
    lines.append("")
    if result.get("skipped"):
        lines.append("## 本次检索策略")
        lines.append("- 判定为轻场景或信息不足，本次跳过章节检索以节省上下文。")
        lines.append("- 如需强制检索，可使用 `--force`。")
        out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return out

    lines.append("## 建议回读章节（Top）")
    retrieved = result.get("retrieved", [])
    if not retrieved:
        lines.append("- 无可用章节")
    else:
        for i, r in enumerate(retrieved, 1):
            lines.append(f"{i}. `{r['chapter_file']}` | score={r['score']} | 命中={r['reason']}")
            lines.append(f"   摘要：{r['summary']}")
            meta_bits = []
            if r.get("events"):
                meta_bits.append("事件=" + ",".join(r["events"][:4]))
            if r.get("locations"):
                meta_bits.append("地点=" + ",".join(r["locations"][:3]))
            if r.get("foreshadow_refs"):
                meta_bits.append("伏笔=" + " / ".join(r["foreshadow_refs"][:2]))
            if meta_bits:
                lines.append("   元数据：" + "；".join(meta_bits))
            passages = r.get("passages", [])
            if passages:
                lines.append("   关键片段：")
                for p in passages:
                    lines.append(f"   - {p['text']} (reason={p['reason']}, score={p['score']})")

    lines.append("")
    lines.append("## 角色关系相关片段")
    snippets = result.get("relation_snippets", [])
    if not snippets:
        lines.append("- 无命中（可补充 character_tracker）")
    else:
        for i, s in enumerate(snippets, 1):
            lines.append(f"### 片段 {i}")
            lines.append("```")
            lines.append(s)
            lines.append("```")

    lines.append("")
    lines.append("## 写作前执行建议")
    lines.append("1. 读取上述 Top 章节，确认人物关系与伏笔状态。")
    lines.append("2. 若发现冲突，先执行 /检查一致性 再写作。")
    lines.append("3. 写作后继续执行门禁链路。")

    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="构建章节索引并按新剧情检索相关章节上下文")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="更新剧情索引")
    p_build.add_argument("--project-root", required=True)
    p_build.add_argument("--keyword-top-n", type=int, default=20)
    p_build.add_argument("--full-rebuild", action="store_true", help="禁用增量索引，强制全量重建")

    p_query = sub.add_parser("query", help="检索新剧情关联章节")
    p_query.add_argument("--project-root", required=True)
    p_query.add_argument("--query", required=True)
    p_query.add_argument("--top-k", type=int, default=4)
    p_query.add_argument("--auto-build", action="store_true")
    p_query.add_argument("--full-rebuild", action="store_true", help="与 --auto-build 联用时强制全量重建")
    p_query.add_argument("--passages-per-chapter", type=int, default=2, help="每章返回片段数量")
    p_query.add_argument("--candidate-k", type=int, default=12, help="粗筛候选池大小（两级检索第一阶段）")
    p_query.add_argument("--passage-max-chars", type=int, default=220, help="单片段最大字符数")
    p_query.add_argument("--conditional", dest="conditional", action="store_true", default=True, help="启用条件触发，轻场景跳过检索")
    p_query.add_argument("--no-conditional", dest="conditional", action="store_false", help="关闭条件触发，每次都检索")
    p_query.add_argument("--force", action="store_true", help="强制检索，忽略条件触发判定")
    p_query.add_argument("--use-cache", dest="use_cache", action="store_true", default=True, help="启用查询缓存")
    p_query.add_argument("--no-cache", dest="use_cache", action="store_false", help="禁用查询缓存")
    p_query.add_argument("--emit-json")

    return p.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).expanduser().resolve()

    if args.cmd == "build":
        index = build_index(
            project_root,
            keyword_top_n=args.keyword_top_n,
            incremental=not args.full_rebuild,
        )
        print(json.dumps({
            "ok": True,
            "cmd": "build",
            "chapter_count": index.get("chapter_count", 0),
            "reused_docs": index.get("reused_docs", 0),
            "rebuilt_docs": index.get("rebuilt_docs", 0),
            "index_file": str(project_root / "00_memory" / "retrieval" / "story_index.json"),
        }, ensure_ascii=False, indent=2))
        return 0

    retrieval_dir = project_root / "00_memory" / "retrieval"
    index_file = retrieval_dir / "story_index.json"
    if args.auto_build or not index_file.exists():
        index = build_index(project_root, incremental=not args.full_rebuild)
    else:
        index = json.loads(index_file.read_text(encoding="utf-8"))

    names = load_character_names(project_root)
    trigger = analyze_query_trigger(args.query, names)

    if args.conditional and not args.force and not trigger["should_trigger"]:
        result = {
            "query": args.query,
            "query_entities": trigger.get("entities", []),
            "skipped": True,
            "cache_hit": False,
            "trigger_reason": trigger.get("reason", []),
            "retrieved": [],
            "relation_snippets": [],
        }
        md_out = write_context_md(project_root, result)
        payload = {
            "ok": True,
            "cmd": "query",
            "context_file": str(md_out),
            "result": result,
        }
        if args.emit_json:
            jp = Path(args.emit_json).expanduser().resolve()
            ensure_dir(jp.parent)
            jp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    cache_file = retrieval_dir / "query_cache.json"
    idx_sig = index_signature(index)
    cache_key = make_cache_key(
        args.query,
        args.top_k,
        args.passages_per_chapter,
        args.passage_max_chars,
        f"{idx_sig}|cand={args.candidate_k}",
    )

    if args.use_cache:
        cache = load_cache(cache_file)
        entry = cache.get("entries", {}).get(cache_key)
        if entry and isinstance(entry, dict) and "result" in entry:
            result = entry["result"]
            result["cache_hit"] = True
            md_out = write_context_md(project_root, result)
            payload = {
                "ok": True,
                "cmd": "query",
                "context_file": str(md_out),
                "cache_hit": True,
                "result": result,
            }
            if args.emit_json:
                jp = Path(args.emit_json).expanduser().resolve()
                ensure_dir(jp.parent)
                jp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

    result = retrieve(
        index,
        project_root,
        args.query,
        args.top_k,
        candidate_k=max(args.top_k, args.candidate_k),
        per_chapter=args.passages_per_chapter,
        passage_max_chars=args.passage_max_chars,
    )
    result["cache_hit"] = False
    result["skipped"] = False
    result["trigger_reason"] = trigger.get("reason", [])

    if args.use_cache:
        cache = load_cache(cache_file)
        cache.setdefault("entries", {})
        cache["entries"][cache_key] = {
            "saved_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "result": result,
        }
        save_cache(cache_file, cache)

    md_out = write_context_md(project_root, result)

    payload = {
        "ok": True,
        "cmd": "query",
        "context_file": str(md_out),
        "cache_hit": False,
        "result": result,
    }

    if args.emit_json:
        jp = Path(args.emit_json).expanduser().resolve()
        ensure_dir(jp.parent)
        jp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
