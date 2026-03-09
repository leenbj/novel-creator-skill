#!/usr/bin/env python3
"""章节级知识图谱更新器（门禁 Step 5 图谱回写）。

从已完成的章节正文中提取实体和事件信息，
生成更新指令供 AI 审核后批量写入知识图谱。

与 story_graph_builder.py 的区别：
- builder: 手动 CRUD，适合初始化和精确修改
- updater: 章节完成后自动扫描提取，生成更新建议

子命令：
1. extract  — 从章节文本生成图谱更新建议（JSON 指令列表）
2. apply    — 执行更新指令列表（调用 story_graph_builder.py）
3. diff     — 对比章节前后图谱差异
4. cascade  — 改纲后按章节阈值标记受影响节点并生成级联报告
"""

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import ensure_dir, load_json, read_text, save_json

# -- 配置 ------------------------------------------------------------------

@dataclass
class UpdaterConfig:
    graph_rel_path: str = "00_memory/story_graph.json"
    updates_rel_dir: str = "00_memory/graph_updates"
    default_indent: int = 2

    # 死亡/受伤关键词（用于提取角色状态变化）
    death_keywords: List[str] = field(default_factory=lambda: [
        "死了", "阵亡", "牺牲", "殒命", "离世", "不治", "身亡",
    ])
    injury_keywords: List[str] = field(default_factory=lambda: [
        "受伤", "中箭", "负伤", "重伤", "轻伤", "身受重创",
    ])

    # 关系变化关键词
    ally_keywords: List[str] = field(default_factory=lambda: [
        "结盟", "合作", "共同", "并肩", "联手", "携手",
    ])
    enemy_keywords: List[str] = field(default_factory=lambda: [
        "背叛", "决裂", "反目", "翻脸", "为敌", "仇敌",
    ])


# -- 内部工具 ---------------------------------------------------------------

def _updates_dir(root: Path, cfg: UpdaterConfig) -> Path:
    return root / cfg.updates_rel_dir


def _update_file_path(root: Path, chapter: int, cfg: UpdaterConfig) -> Path:
    return _updates_dir(root, cfg) / f"ch{chapter:04d}_updates.json"


def _load_graph(root: Path, cfg: UpdaterConfig) -> Dict[str, Any]:
    return load_json(root / cfg.graph_rel_path, default={"nodes": [], "edges": []})


def _extract_known_names(graph: Dict[str, Any]) -> List[str]:
    """从图谱中提取已知角色名称。"""
    names: List[str] = []
    for n in graph.get("nodes", []):
        if isinstance(n, dict) and n.get("type") == "character":
            name = n.get("name", "")
            if name and len(name) >= 2:
                names.append(name)
    return names


def _scan_status_changes(
    text: str,
    known_names: List[str],
    chapter: int,
    cfg: UpdaterConfig,
) -> List[Dict[str, Any]]:
    """扫描章节文本，检测角色状态变化。"""
    updates: List[Dict[str, Any]] = []

    for name in known_names:
        if name not in text:
            continue

        # 检测死亡
        for kw in cfg.death_keywords:
            if kw in text:
                # 死亡信号在角色名附近（前后50字）
                idx = text.find(name)
                while idx != -1:
                    context = text[max(0, idx - 50): idx + len(name) + 50]
                    if kw in context:
                        updates.append({
                            "type": "update-node",
                            "node_id": f"character_{name}",
                            "chapter": chapter,
                            "attrs": {"status": "dead", "death_chapter": chapter},
                            "confidence": "medium",
                            "evidence": context[:80],
                        })
                        break
                    idx = text.find(name, idx + 1)

        # 检测受伤（只在未死亡时）
        for kw in cfg.injury_keywords:
            if kw in text:
                idx = text.find(name)
                while idx != -1:
                    context = text[max(0, idx - 50): idx + len(name) + 50]
                    if kw in context:
                        updates.append({
                            "type": "update-node",
                            "node_id": f"character_{name}",
                            "chapter": chapter,
                            "attrs": {"status": "injured"},
                            "confidence": "low",
                            "evidence": context[:80],
                        })
                        break
                    idx = text.find(name, idx + 1)

    return updates


def _scan_new_events(
    text: str,
    chapter: int,
    known_names: List[str],
) -> List[Dict[str, Any]]:
    """从章节文本扫描可能的新事件节点。

    这是一个启发式提取，准确率有限，需要人工确认。
    """
    updates: List[Dict[str, Any]] = []

    # 提取章节标题作为事件名
    title_match = re.search(r"^#\s+(.+)", text, re.MULTILINE)
    chapter_title = title_match.group(1).strip() if title_match else f"第{chapter}章事件"

    # 检测到场角色
    participants = [n for n in known_names if n in text]

    updates.append({
        "type": "add-node",
        "node_type": "event",
        "name": chapter_title,
        "chapter": chapter,
        "attrs": {
            "participants": participants[:5],
            "chapter": chapter,
        },
        "confidence": "high",
        "note": "自动从章节标题生成，请核实事件描述",
    })

    return updates


def _scan_foreshadows(text: str, chapter: int) -> List[Dict[str, Any]]:
    """检测章节中可能的伏笔。"""
    updates: List[Dict[str, Any]] = []

    # 简单的伏笔信号词检测
    foreshadow_signals = ["不知为何", "心中一动", "忽然想起", "某种预感", "隐约感觉"]
    for sig in foreshadow_signals:
        idx = text.find(sig)
        if idx != -1:
            context = text[max(0, idx - 20): idx + 60]
            updates.append({
                "type": "add-node",
                "node_type": "foreshadow",
                "name": f"第{chapter}章伏笔_{sig}",
                "chapter": chapter,
                "attrs": {
                    "planted_chapter": chapter,
                    "status": "active",
                    "hint": context[:60],
                },
                "confidence": "low",
                "note": "疑似伏笔，请人工确认是否需要追踪",
            })
            break  # 每章最多提取一个

    return updates


# -- 子命令 -----------------------------------------------------------------

def cmd_extract(args: argparse.Namespace, cfg: UpdaterConfig) -> Dict[str, Any]:
    """从章节文本生成图谱更新建议。"""
    root = Path(args.project_root).expanduser().resolve()
    chapter = args.chapter

    chapter_path = Path(args.chapter_file)
    if not chapter_path.is_absolute():
        chapter_path = root / chapter_path

    if not chapter_path.exists():
        return {
            "ok": False, "command": "extract",
            "error": f"章节文件不存在: {chapter_path}",
        }

    text = read_text(chapter_path)
    graph = _load_graph(root, cfg)
    known_names = _extract_known_names(graph)

    all_updates: List[Dict[str, Any]] = []

    # 状态变化扫描
    status_updates = _scan_status_changes(text, known_names, chapter, cfg)
    all_updates.extend(status_updates)

    # 事件节点提取
    if args.extract_events:
        event_updates = _scan_new_events(text, chapter, known_names)
        all_updates.extend(event_updates)

    # 伏笔检测
    if args.extract_foreshadows:
        foreshadow_updates = _scan_foreshadows(text, chapter)
        all_updates.extend(foreshadow_updates)

    # 保存更新建议
    output = {
        "chapter": chapter,
        "chapter_file": str(chapter_path),
        "graph_file": str(root / cfg.graph_rel_path),
        "extracted_at": dt.datetime.now().isoformat(),
        "known_names_count": len(known_names),
        "updates": all_updates,
        "update_count": len(all_updates),
        "note": "以下更新建议需要人工审核后再执行 apply 命令",
    }

    update_path = _update_file_path(root, chapter, cfg)
    ensure_dir(update_path.parent)
    save_json(update_path, output, indent=cfg.default_indent)

    return {
        "ok": True, "command": "extract",
        "update_file": str(update_path),
        "chapter": chapter,
        "update_count": len(all_updates),
        "known_names": known_names[:10],
        "status_updates": len(status_updates),
        "message": (
            f"已生成 {len(all_updates)} 条更新建议。"
            "请审核 update_file 后执行 apply 命令写入图谱。"
        ),
    }


def cmd_apply(args: argparse.Namespace, cfg: UpdaterConfig) -> Dict[str, Any]:
    """执行图谱更新指令列表。"""
    root = Path(args.project_root).expanduser().resolve()
    chapter = args.chapter

    update_path = _update_file_path(root, chapter, cfg)
    if not update_path.exists():
        return {
            "ok": False, "command": "apply",
            "error": f"更新文件不存在: {update_path}，请先执行 extract",
        }

    update_data = load_json(update_path, default={})
    updates = update_data.get("updates", [])

    if not updates:
        return {
            "ok": True, "command": "apply",
            "chapter": chapter,
            "applied": 0,
            "message": "没有待执行的更新",
        }

    builder = SCRIPT_DIR / "story_graph_builder.py"
    applied = 0
    errors: List[str] = []

    for u in updates:
        # 低置信度跳过（除非强制）
        if u.get("confidence") == "low" and not args.force_low_confidence:
            continue

        cmd_type = u.get("type")
        try:
            if cmd_type == "update-node":
                cmd = [
                    sys.executable, str(builder), "update-node",
                    "--project-root", str(root),
                    "--node-id", u["node_id"],
                    "--chapter", str(u.get("chapter", chapter)),
                    "--attrs", json.dumps(u.get("attrs", {}), ensure_ascii=False),
                ]
            elif cmd_type == "add-node":
                cmd = [
                    sys.executable, str(builder), "add-node",
                    "--project-root", str(root),
                    "--type", u["node_type"],
                    "--name", u["name"],
                    "--last-updated", str(u.get("chapter", chapter)),
                    "--attrs", json.dumps(u.get("attrs", {}), ensure_ascii=False),
                ]
            else:
                errors.append(f"未知指令类型: {cmd_type}")
                continue

            proc = subprocess.run(cmd, capture_output=True, text=True)
            result = json.loads(proc.stdout) if proc.stdout.strip() else {}
            if result.get("ok"):
                applied += 1
            else:
                errors.append(f"{cmd_type} {u.get('node_id', u.get('name', '?'))}: {result.get('error', 'failed')}")

        except Exception as exc:
            errors.append(f"{cmd_type} error: {repr(exc)}")

    return {
        "ok": len(errors) == 0,
        "command": "apply",
        "chapter": chapter,
        "total_updates": len(updates),
        "applied": applied,
        "errors": errors,
        "message": f"已应用 {applied}/{len(updates)} 条更新",
    }


def cmd_cascade(args: argparse.Namespace, cfg: UpdaterConfig) -> Dict[str, Any]:
    """改纲后按章节阈值标记受影响节点，生成结构化级联影响报告。

    注意：本命令仅追加 cascade_pending 标记，不清理历史标记。
    多次改纲时图谱中可能存在残留旧标记，报告中已注明。
    """
    root = Path(args.project_root).expanduser().resolve()
    from_chapter = int(args.from_chapter)
    change_description = str(args.change_description or "").strip()
    graph_path = root / cfg.graph_rel_path

    if from_chapter <= 0:
        return {
            "ok": False,
            "command": "cascade",
            "error": "from_chapter_must_be_positive",
        }

    if not graph_path.exists():
        return {
            "ok": False,
            "command": "cascade",
            "error": f"图谱文件不存在: {graph_path}，请先执行 one-click 初始化",
        }

    graph = _load_graph(root, cfg)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    def _as_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    # 找出受影响的节点（改纲章节及之后被写过的节点）
    affected_nodes = [
        n for n in nodes
        if isinstance(n, dict) and _as_int(n.get("last_updated")) >= from_chapter
    ]
    # 找出受影响的边（改纲章节及之后建立的关系）
    affected_edges = [
        e for e in edges
        if isinstance(e, dict) and _as_int(e.get("since_chapter")) >= from_chapter
    ]

    # 在受影响节点上追加 cascade_pending 标记（不清理旧标记）
    marked_at = dt.datetime.now().isoformat()
    for node in affected_nodes:
        node["cascade_pending"] = True

    graph["updated_at"] = marked_at
    save_ok = save_json(graph_path, graph, indent=cfg.default_indent)

    # 生成可读报告行
    cascade_report_lines: List[str] = [
        f"改纲生效章节：第{from_chapter}章",
        f"变更描述：{change_description or '未提供'}",
        f"受影响节点：{len(affected_nodes)} 个（已标记 cascade_pending=True）",
        f"受影响边：{len(affected_edges)} 条",
        "注意：本次仅追加标记，不自动清理历史 cascade_pending 旧标记。",
    ]
    for node in affected_nodes[:20]:
        cascade_report_lines.append(
            "- 节点 [{id}] type={type} name={name} last_updated={last_updated}".format(
                id=node.get("id", ""),
                type=node.get("type", ""),
                name=node.get("name", ""),
                last_updated=node.get("last_updated", 0),
            )
        )
    if len(affected_nodes) > 20:
        cascade_report_lines.append(f"  ...共 {len(affected_nodes)} 个节点，仅显示前 20 个")
    for edge in affected_edges[:20]:
        cascade_report_lines.append(
            "- 边 [{id}] type={type} {source}->{target} since_chapter={since}".format(
                id=edge.get("id", ""),
                type=edge.get("type", ""),
                source=edge.get("source", ""),
                target=edge.get("target", ""),
                since=edge.get("since_chapter", 0),
            )
        )
    if len(affected_edges) > 20:
        cascade_report_lines.append(f"  ...共 {len(affected_edges)} 条边，仅显示前 20 条")

    return {
        "ok": save_ok,
        "command": "cascade",
        "graph_file": str(graph_path),
        "from_chapter": from_chapter,
        "change_description": change_description,
        "affected_nodes_count": len(affected_nodes),
        "affected_edges_count": len(affected_edges),
        "affected_node_ids": [str(n.get("id", "")) for n in affected_nodes],
        "affected_edge_ids": [str(e.get("id", "")) for e in affected_edges],
        "cascade_report_lines": cascade_report_lines,
        "marked_at": marked_at,
        "error": None if save_ok else "save_graph_failed",
    }


def cmd_diff(args: argparse.Namespace, cfg: UpdaterConfig) -> Dict[str, Any]:
    """对比章节前后图谱变化（通过 last_updated 字段）。"""
    root = Path(args.project_root).expanduser().resolve()
    chapter = args.chapter

    graph = _load_graph(root, cfg)

    # 找出在本章或之后被更新的节点
    updated_nodes = [
        n for n in graph.get("nodes", [])
        if isinstance(n, dict) and int(n.get("last_updated", 0) or 0) == chapter
    ]

    # 找出本章新增的边（通过 since_chapter）
    new_edges = [
        e for e in graph.get("edges", [])
        if isinstance(e, dict) and int(e.get("since_chapter", 0) or 0) == chapter
    ]

    return {
        "ok": True, "command": "diff",
        "chapter": chapter,
        "updated_nodes_count": len(updated_nodes),
        "new_edges_count": len(new_edges),
        "updated_nodes": [
            {"id": n.get("id"), "name": n.get("name"), "type": n.get("type")}
            for n in updated_nodes
        ],
        "new_edges": [
            {"id": e.get("id"), "type": e.get("type"), "source": e.get("source"), "target": e.get("target")}
            for e in new_edges
        ],
    }


# -- CLI -------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="章节级知识图谱更新器")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("extract", help="从章节生成图谱更新建议")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", type=int, required=True)
    s.add_argument("--chapter-file", required=True)
    s.add_argument("--extract-events", action="store_true", default=True,
                   help="提取事件节点（默认开启）")
    s.add_argument("--no-extract-events", dest="extract_events", action="store_false")
    s.add_argument("--extract-foreshadows", action="store_true", default=True,
                   help="检测伏笔（默认开启）")
    s.add_argument("--no-extract-foreshadows", dest="extract_foreshadows", action="store_false")

    s = sub.add_parser("apply", help="执行更新指令")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", type=int, required=True)
    s.add_argument("--force-low-confidence", action="store_true",
                   help="同时执行低置信度更新")

    s = sub.add_parser("diff", help="查看本章图谱变化")
    s.add_argument("--project-root", required=True)
    s.add_argument("--chapter", type=int, required=True)

    s = sub.add_parser("cascade", help="改纲后标记受影响节点并生成级联报告")
    s.add_argument("--project-root", required=True)
    s.add_argument("--from-chapter", type=int, required=True,
                   help="改纲生效章节号（含该章，必须 >= 1）")
    s.add_argument("--change-description", default="",
                   help="本次改纲说明（可选）")

    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = UpdaterConfig()

    dispatch = {
        "extract": cmd_extract,
        "apply": cmd_apply,
        "diff": cmd_diff,
        "cascade": cmd_cascade,
    }

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
