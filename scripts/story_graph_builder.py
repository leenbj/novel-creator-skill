#!/usr/bin/env python3
"""知识图谱构建器。

子命令：
1. init       — 初始化空图谱
2. add-node   — 添加节点
3. update-node — 更新已有节点字段
4. add-edge   — 添加边
5. export     — 导出 Mermaid 关系图
6. validate   — 图谱一致性校验
"""

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import ensure_dir, load_json, save_json, slugify

# ── 常量 ──────────────────────────────────────────────────────────

NODE_TYPES: Set[str] = {
    "character", "location", "faction", "item",
    "event", "foreshadow", "worldrule", "power_system",
}

EDGE_TYPES: Set[str] = {
    "ally", "enemy", "mentor", "subordinate", "romantic",
    "belongs_to", "located_at", "triggers", "foreshadows", "owns",
}

# ── 配置 ──────────────────────────────────────────────────────────

@dataclass
class GraphConfig:
    graph_rel_path: str = "00_memory/story_graph.json"
    version: str = "1.0"
    default_indent: int = 2
    export_default_direction: str = "LR"
    allowed_node_types: Set[str] = field(default_factory=lambda: set(NODE_TYPES))
    allowed_edge_types: Set[str] = field(default_factory=lambda: set(EDGE_TYPES))


# ── 内部工具 ──────────────────────────────────────────────────────

def _graph_path(project_root: Path, cfg: GraphConfig) -> Path:
    return project_root / cfg.graph_rel_path


def _empty_graph(cfg: GraphConfig) -> Dict[str, Any]:
    return {
        "version": cfg.version,
        "last_updated_chapter": 0,
        "updated_at": dt.datetime.now().isoformat(),
        "nodes": [],
        "edges": [],
        "timeline": [],
    }


def _load_graph(path: Path, cfg: GraphConfig) -> Dict[str, Any]:
    g = load_json(path, default=_empty_graph(cfg))
    for key in ("nodes", "edges", "timeline"):
        if not isinstance(g.get(key), list):
            g[key] = []
    g.setdefault("version", cfg.version)
    return g


def _save_graph(path: Path, graph: Dict[str, Any], cfg: GraphConfig) -> bool:
    graph["updated_at"] = dt.datetime.now().isoformat()
    return save_json(path, graph, indent=cfg.default_indent)


def _parse_json_arg(raw: str) -> Dict[str, Any]:
    if not raw or raw == "{}":
        return {}
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError("attrs 必须是 JSON 对象")
    return obj


def _make_node_id(node_type: str, name: str) -> str:
    return f"{node_type}_{slugify(name)}"


def _make_edge_id(edge_type: str, source: str, target: str) -> str:
    return f"{edge_type}_{slugify(source)}_{slugify(target)}"


def _index_nodes(graph: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(n["id"]): n
        for n in graph.get("nodes", [])
        if isinstance(n, dict) and n.get("id")
    }


# ── 子命令 ────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace, cfg: GraphConfig) -> Dict[str, Any]:
    project_root = Path(args.project_root).expanduser().resolve()
    path = _graph_path(project_root, cfg)
    ensure_dir(path.parent)

    if path.exists() and not args.force:
        graph = _load_graph(path, cfg)
        return {
            "ok": True, "command": "init",
            "graph_file": str(path), "created": False,
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
            "message": "图谱已存在；如需覆盖请加 --force",
        }

    graph = _empty_graph(cfg)
    ok = _save_graph(path, graph, cfg)
    return {"ok": ok, "command": "init", "graph_file": str(path), "created": ok}


def cmd_add_node(args: argparse.Namespace, cfg: GraphConfig) -> Dict[str, Any]:
    project_root = Path(args.project_root).expanduser().resolve()
    path = _graph_path(project_root, cfg)
    graph = _load_graph(path, cfg)

    if args.type not in cfg.allowed_node_types:
        return {"ok": False, "command": "add-node", "error": f"非法节点类型: {args.type}"}

    attrs = _parse_json_arg(args.attrs)
    node_id = args.id or _make_node_id(args.type, args.name)

    if any(str(n.get("id")) == node_id for n in graph["nodes"] if isinstance(n, dict)):
        return {"ok": False, "command": "add-node", "error": f"节点已存在: {node_id}"}

    node: Dict[str, Any] = {
        "id": node_id,
        "type": args.type,
        "name": args.name,
        "created_at": dt.datetime.now().isoformat(),
        "last_updated": args.last_updated or 0,
    }
    node.update(attrs)
    graph["nodes"].append(node)
    ok = _save_graph(path, graph, cfg)
    return {
        "ok": ok, "command": "add-node",
        "graph_file": str(path), "node": node,
        "node_count": len(graph["nodes"]),
    }


def cmd_update_node(args: argparse.Namespace, cfg: GraphConfig) -> Dict[str, Any]:
    """更新已有节点的字段（合并更新，不覆盖未指定字段）。"""
    project_root = Path(args.project_root).expanduser().resolve()
    path = _graph_path(project_root, cfg)
    graph = _load_graph(path, cfg)

    node_id = args.node_id
    target = None
    for n in graph["nodes"]:
        if isinstance(n, dict) and str(n.get("id")) == node_id:
            target = n
            break

    if target is None:
        return {"ok": False, "command": "update-node", "error": f"节点不存在: {node_id}"}

    updates = _parse_json_arg(args.attrs)
    if not updates:
        return {"ok": False, "command": "update-node", "error": "未提供更新字段"}

    # id 和 type 不允许修改
    updates.pop("id", None)
    updates.pop("type", None)

    target.update(updates)
    target["last_updated"] = args.chapter or target.get("last_updated", 0)
    ok = _save_graph(path, graph, cfg)
    return {
        "ok": ok, "command": "update-node",
        "graph_file": str(path), "node": target,
    }


def cmd_add_edge(args: argparse.Namespace, cfg: GraphConfig) -> Dict[str, Any]:
    project_root = Path(args.project_root).expanduser().resolve()
    path = _graph_path(project_root, cfg)
    graph = _load_graph(path, cfg)
    node_index = _index_nodes(graph)

    if args.type not in cfg.allowed_edge_types:
        return {"ok": False, "command": "add-edge", "error": f"非法边类型: {args.type}"}
    if args.source not in node_index:
        return {"ok": False, "command": "add-edge", "error": f"源节点不存在: {args.source}"}
    if args.target not in node_index:
        return {"ok": False, "command": "add-edge", "error": f"目标节点不存在: {args.target}"}

    attrs = _parse_json_arg(args.attrs)
    edge_id = args.id or _make_edge_id(args.type, args.source, args.target)

    if any(str(e.get("id")) == edge_id for e in graph["edges"] if isinstance(e, dict)):
        return {"ok": False, "command": "add-edge", "error": f"边已存在: {edge_id}"}

    edge: Dict[str, Any] = {
        "id": edge_id,
        "type": args.type,
        "source": args.source,
        "target": args.target,
        "since_chapter": args.since_chapter,
        "description": args.description or "",
    }
    edge.update(attrs)
    graph["edges"].append(edge)
    ok = _save_graph(path, graph, cfg)
    return {
        "ok": ok, "command": "add-edge",
        "graph_file": str(path), "edge": edge,
        "edge_count": len(graph["edges"]),
    }


def cmd_export(args: argparse.Namespace, cfg: GraphConfig) -> Dict[str, Any]:
    project_root = Path(args.project_root).expanduser().resolve()
    path = _graph_path(project_root, cfg)
    graph = _load_graph(path, cfg)
    node_index = _index_nodes(graph)

    direction = args.direction or cfg.export_default_direction
    lines: List[str] = [f"flowchart {direction}"]

    for n in graph["nodes"]:
        if not isinstance(n, dict) or not n.get("id"):
            continue
        nid = str(n["id"])
        label = str(n.get("name") or nid).replace('"', "'")
        lines.append(f'  {nid}["{label}"]')

    for e in graph["edges"]:
        if not isinstance(e, dict):
            continue
        src, tgt = str(e.get("source", "")), str(e.get("target", ""))
        et = str(e.get("type", "rel")).replace('"', "'")
        if src in node_index and tgt in node_index:
            lines.append(f"  {src} -- {et} --> {tgt}")

    mermaid = "\n".join(lines) + "\n"

    output_path: Optional[Path] = None
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        ensure_dir(output_path.parent)
        output_path.write_text(mermaid, encoding="utf-8")

    return {
        "ok": True, "command": "export",
        "graph_file": str(path),
        "output_file": str(output_path) if output_path else "",
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
        "format": "mermaid",
        "content": mermaid if args.inline else "",
    }


def cmd_validate(args: argparse.Namespace, cfg: GraphConfig) -> Dict[str, Any]:
    project_root = Path(args.project_root).expanduser().resolve()
    path = _graph_path(project_root, cfg)
    graph = _load_graph(path, cfg)
    node_index = _index_nodes(graph)

    errors: List[str] = []
    warnings: List[str] = []

    # 节点校验
    for n in graph["nodes"]:
        if not isinstance(n, dict):
            errors.append("node_not_object")
            continue
        nid = str(n.get("id", ""))
        ntype = str(n.get("type", ""))
        if not nid:
            errors.append("node_missing_id")
        if ntype not in cfg.allowed_node_types:
            errors.append(f"node_invalid_type:{nid}:{ntype}")

    # 边校验
    for e in graph["edges"]:
        if not isinstance(e, dict):
            errors.append("edge_not_object")
            continue
        eid = str(e.get("id", ""))
        etype = str(e.get("type", ""))
        src = str(e.get("source", ""))
        tgt = str(e.get("target", ""))
        if not eid:
            errors.append("edge_missing_id")
        if etype not in cfg.allowed_edge_types:
            errors.append(f"edge_invalid_type:{eid}:{etype}")
        if src not in node_index:
            errors.append(f"edge_source_missing:{eid}:{src}")
        if tgt not in node_index:
            errors.append(f"edge_target_missing:{eid}:{tgt}")

    # 已死亡角色不能参与新事件
    for n in graph["nodes"]:
        if not isinstance(n, dict) or n.get("type") != "event":
            continue
        ev_id = str(n.get("id", ""))
        ev_chapter = int(n.get("chapter", 0) or 0)
        participants = n.get("participants", [])
        if not isinstance(participants, list):
            continue
        for pid in participants:
            pn = node_index.get(str(pid))
            # 兼容 updater 写入名字字符串的情况：按名字回退查找
            if not pn and pid is not None:
                pid_name = str(pid).strip()
                pn = next(
                    (
                        node for node in graph["nodes"]
                        if isinstance(node, dict)
                        and node.get("type") == "character"
                        and str(node.get("name", "")).strip() == pid_name
                    ),
                    None,
                ) if pid_name else None
            if not pn:
                errors.append(f"event_participant_missing:{ev_id}:{pid}")
                continue
            if pn.get("type") != "character":
                continue
            status = str(pn.get("status", "")).lower()
            death_ch = int(pn.get("death_chapter", 0) or 0)
            if status in {"dead", "deceased"} and death_ch > 0 and ev_chapter >= death_ch:
                errors.append(f"dead_char_in_event:{pid}:death_ch={death_ch}:event_ch={ev_chapter}:{ev_id}")

    # 伏笔时间窗校验
    for n in graph["nodes"]:
        if not isinstance(n, dict) or n.get("type") != "foreshadow":
            continue
        nid = str(n.get("id", ""))
        planted = int(n.get("planted_chapter") or n.get("chapter_planted") or 0)
        target = int(n.get("target_chapter", 0) or 0)
        fstatus = str(n.get("status", ""))
        if planted > 0 and target > 0 and target < planted:
            errors.append(f"foreshadow_target_before_planted:{nid}")
        if fstatus == "expired":
            warnings.append(f"foreshadow_expired:{nid}")

    return {
        "ok": len(errors) == 0,
        "command": "validate",
        "graph_file": str(path),
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
        "errors": errors,
        "warnings": warnings,
    }


def cmd_context(args: argparse.Namespace, cfg: GraphConfig) -> Dict[str, Any]:
    """生成写作上下文摘要，注入写前 query。

    从 story_graph.json 中提取：
    - 所有角色节点的当前位置和状态
    - 未解决的伏笔节点
    - 近期事件节点（按章节号倒序）
    并组合成可直接注入 writing_query 的中文摘要字符串。
    """
    root = Path(args.project_root).expanduser().resolve()
    graph = _load_graph(_graph_path(root, cfg), cfg)
    nodes = graph.get("nodes", [])

    chapter = args.chapter or 0
    max_foreshadows = args.max_foreshadows
    max_events = args.max_events

    # 1. 角色当前状态
    characters = [n for n in nodes if isinstance(n, dict) and n.get("type") == "character"]
    char_lines = []
    for c in characters:
        name = c.get("name", c.get("id", "未知"))
        loc = c.get("location", "未知")
        status = c.get("status", "正常")
        if status.lower() in {"dead", "deceased"}:
            continue  # 已死亡角色不注入
        char_lines.append(f"- {name}：当前位于「{loc}」，状态={status}")

    # 2. 未解决伏笔
    foreshadows = [
        n for n in nodes
        if isinstance(n, dict)
        and n.get("type") == "foreshadow"
        and not n.get("resolved", False)
    ]
    # 兼容两种字段命名：story_graph_updater 写 planted_chapter，旧数据用 chapter_planted
    def _foreshadow_planted(n: Dict[str, Any]) -> int:
        return int(n.get("planted_chapter") or n.get("chapter_planted") or 0)

    foreshadows_sorted = sorted(foreshadows, key=_foreshadow_planted)[:max_foreshadows]
    foreshadow_lines = [
        "- [{id}] {desc}（埋于第{planted}章，截止第{deadline}章）".format(
            id=n.get("id", ""),
            desc=n.get("description") or n.get("hint") or n.get("name", ""),
            planted=n.get("planted_chapter") or n.get("chapter_planted", ""),
            deadline=n.get("target_chapter") or n.get("chapter_deadline", "?"),
        )
        for n in foreshadows_sorted
    ]

    # 3. 近期事件（兼容 participants 为名字列表）
    events = [
        n for n in nodes
        if isinstance(n, dict)
        and n.get("type") == "event"
        and (chapter == 0 or int(n.get("chapter", 0) or 0) <= chapter)
    ]
    events_recent = sorted(
        events,
        key=lambda n: int(n.get("chapter", 0) or 0),
        reverse=True,
    )[:max_events]
    event_lines = []
    for n in events_recent:
        desc = n.get("description") or n.get("name", "")
        participants = n.get("participants", [])
        participant_str = (
            "（参与角色：" + "、".join(str(p) for p in participants if str(p).strip()) + "）"
            if isinstance(participants, list) and participants
            else ""
        )
        event_lines.append(f"- 第{n.get('chapter', '')}章：{desc}{participant_str}")

    # 组合上下文 prompt
    sections = []
    if char_lines:
        sections.append("【角色状态】\n" + "\n".join(char_lines))
    if foreshadow_lines:
        sections.append("【待回收伏笔】\n" + "\n".join(foreshadow_lines))
    if event_lines:
        sections.append("【近期事件】\n" + "\n".join(event_lines))

    context_prompt = "\n\n".join(sections) if sections else ""

    return {
        "ok": True,
        "command": "generate-context",
        "context_prompt": context_prompt,
        "character_count": len(char_lines),
        "foreshadow_count": len(foreshadow_lines),
        "event_count": len(event_lines),
        "graph_nodes_total": len(nodes),
        "message": "图谱上下文已生成" if context_prompt else "图谱为空，无上下文可注入",
    }


# ── CLI ───────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="知识图谱构建器")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="初始化空图谱")
    s.add_argument("--project-root", required=True)
    s.add_argument("--force", action="store_true", help="覆盖已存在图谱")

    s = sub.add_parser("add-node", help="添加节点")
    s.add_argument("--project-root", required=True)
    s.add_argument("--type", required=True, choices=sorted(NODE_TYPES))
    s.add_argument("--name", required=True)
    s.add_argument("--id", default="")
    s.add_argument("--last-updated", type=int, default=0)
    s.add_argument("--attrs", default="{}", help='额外字段 JSON，如 \'{"role":"protagonist"}\'')

    s = sub.add_parser("update-node", help="更新已有节点字段")
    s.add_argument("--project-root", required=True)
    s.add_argument("--node-id", required=True)
    s.add_argument("--chapter", type=int, default=0, help="触发更新的章节号")
    s.add_argument("--attrs", required=True, help='更新字段 JSON，如 \'{"status":"injured"}\'')

    s = sub.add_parser("add-edge", help="添加边")
    s.add_argument("--project-root", required=True)
    s.add_argument("--type", required=True, choices=sorted(EDGE_TYPES))
    s.add_argument("--source", required=True)
    s.add_argument("--target", required=True)
    s.add_argument("--id", default="")
    s.add_argument("--since-chapter", type=int, default=0)
    s.add_argument("--description", default="")
    s.add_argument("--attrs", default="{}", help="额外字段 JSON")

    s = sub.add_parser("export", help="导出 Mermaid 关系图")
    s.add_argument("--project-root", required=True)
    s.add_argument("--direction", default="LR", choices=["LR", "TD", "RL", "BT"])
    s.add_argument("--output", default="", help="输出文件路径")
    s.add_argument("--inline", action="store_true", help="在 JSON 中内联 Mermaid 文本")

    s = sub.add_parser("validate", help="校验图谱一致性")
    s.add_argument("--project-root", required=True)

    # generate-context 子命令
    s_ctx = sub.add_parser("generate-context", help="生成写作上下文摘要")
    s_ctx.add_argument("--project-root", required=True)
    s_ctx.add_argument("--chapter", type=int, default=0, help="当前章节号（用于过滤近期事件）")
    s_ctx.add_argument("--max-foreshadows", type=int, default=5, help="最多展示未解决伏笔数")
    s_ctx.add_argument("--max-events", type=int, default=5, help="最多展示近期事件数")

    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = GraphConfig()

    dispatch = {
        "init": cmd_init,
        "add-node": cmd_add_node,
        "update-node": cmd_update_node,
        "add-edge": cmd_add_edge,
        "export": cmd_export,
        "validate": cmd_validate,
        "generate-context": cmd_context,
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
