"""story_graph_builder generate-context 子命令测试。"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "story_graph_builder.py"


def _run(project_root: str, chapter: int = 0) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "generate-context",
         "--project-root", project_root, "--chapter", str(chapter)],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)


def _make_graph(tmp: Path, nodes: list) -> None:
    graph = {"version": "1.0", "nodes": nodes, "edges": [], "timeline": []}
    (tmp / "00_memory").mkdir(parents=True, exist_ok=True)
    (tmp / "00_memory" / "story_graph.json").write_text(
        json.dumps(graph), encoding="utf-8"
    )


def test_empty_graph_returns_empty_prompt():
    with tempfile.TemporaryDirectory() as tmp:
        _make_graph(Path(tmp), [])
        result = _run(tmp)
    assert result["ok"] is True
    assert result["context_prompt"] == ""
    assert result["character_count"] == 0


def test_character_location_injected():
    with tempfile.TemporaryDirectory() as tmp:
        _make_graph(Path(tmp), [
            {"id": "char_a", "type": "character", "name": "李逍遥",
             "location": "蜀山", "status": "正常"},
        ])
        result = _run(tmp)
    assert result["ok"] is True
    assert "李逍遥" in result["context_prompt"]
    assert "蜀山" in result["context_prompt"]
    assert result["character_count"] == 1


def test_dead_character_excluded():
    with tempfile.TemporaryDirectory() as tmp:
        _make_graph(Path(tmp), [
            {"id": "char_dead", "type": "character", "name": "赵灵儿",
             "location": "天界", "status": "dead"},
        ])
        result = _run(tmp)
    assert result["character_count"] == 0
    assert "赵灵儿" not in result["context_prompt"]


def test_unresolved_foreshadow_injected():
    with tempfile.TemporaryDirectory() as tmp:
        _make_graph(Path(tmp), [
            {"id": "fore_01", "type": "foreshadow", "description": "神秘玉佩",
             "resolved": False, "chapter_planted": 5, "chapter_deadline": 50},
        ])
        result = _run(tmp)
    assert "神秘玉佩" in result["context_prompt"]
    assert result["foreshadow_count"] == 1


def test_resolved_foreshadow_excluded():
    with tempfile.TemporaryDirectory() as tmp:
        _make_graph(Path(tmp), [
            {"id": "fore_02", "type": "foreshadow", "description": "已解决的伏笔",
             "resolved": True, "chapter_planted": 1, "chapter_deadline": 10},
        ])
        result = _run(tmp)
    assert result["foreshadow_count"] == 0


def test_recent_events_injected():
    with tempfile.TemporaryDirectory() as tmp:
        _make_graph(Path(tmp), [
            {"id": "ev_01", "type": "event", "chapter": 3,
             "description": "主角获得宝剑"},
            {"id": "ev_02", "type": "event", "chapter": 5,
             "description": "反派现身"},
        ])
        result = _run(tmp, chapter=5)
    assert "主角获得宝剑" in result["context_prompt"]
    assert "反派现身" in result["context_prompt"]
    assert result["event_count"] == 2


def test_future_events_excluded_by_chapter_filter():
    with tempfile.TemporaryDirectory() as tmp:
        _make_graph(Path(tmp), [
            {"id": "ev_future", "type": "event", "chapter": 10,
             "description": "未来才发生的事件"},
        ])
        result = _run(tmp, chapter=5)
    assert result["event_count"] == 0
