#!/usr/bin/env python3
"""novel_flow_executor 端到端回归测试。"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EXECUTOR = ROOT / "novel_flow_executor.py"
PY = "python3"


def run_cmd(args):
    proc = subprocess.run([PY, str(EXECUTOR), *args], capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        raise AssertionError(f"命令异常: rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}")
    try:
        payload = json.loads(proc.stdout)
    except Exception as exc:
        raise AssertionError(f"输出不是 JSON: {proc.stdout}") from exc
    return proc.returncode, payload


class TestNovelFlowExecutor(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="novel_flow_exec_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_one_click_init(self):
        _, payload = run_cmd([
            "one-click",
            "--project-root",
            str(self.tmpdir),
            "--title",
            "雾港回声",
            "--genre",
            "悬疑",
            "--idea",
            "主角在旧港区发现失踪名单",
        ])
        self.assertTrue(payload.get("ok"))
        self.assertTrue((self.tmpdir / "00_memory" / "novel_plan.md").exists())
        self.assertTrue((self.tmpdir / "03_manuscript" / "第1章-开篇待写.md").exists())

    def test_continue_write_auto_draft_and_gate(self):
        run_cmd([
            "one-click",
            "--project-root",
            str(self.tmpdir),
            "--title",
            "雾港回声",
            "--genre",
            "悬疑",
            "--idea",
            "主角在旧港区发现失踪名单",
        ])
        _, payload = run_cmd([
            "continue-write",
            "--project-root",
            str(self.tmpdir),
            "--query",
            "主角在站台发现名单并与同伴发生冲突",
        ])
        self.assertTrue(payload.get("ok"))
        self.assertFalse(payload.get("awaiting_draft"))
        self.assertTrue(payload.get("auto_draft_applied"))
        self.assertTrue(payload.get("gate_passed_final"))
        meta_file = self.tmpdir / "00_memory" / "retrieval" / "chapter_meta" / "第2章-待写.meta.json"
        self.assertTrue(meta_file.exists())
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        self.assertEqual(meta.get("chapter_file"), "第2章-待写.md")
        self.assertIn("events", meta)

    def test_continue_write_auto_retry_fix_kb(self):
        run_cmd([
            "one-click",
            "--project-root",
            str(self.tmpdir),
            "--title",
            "雾港回声",
            "--genre",
            "悬疑",
            "--idea",
            "主角在旧港区发现失踪名单",
        ])
        kb_bad = self.tmpdir / "02_knowledge_base" / "第99章-误放.md"
        kb_bad.write_text("误放章节", encoding="utf-8")

        _, payload = run_cmd([
            "continue-write",
            "--project-root",
            str(self.tmpdir),
            "--query",
            "主角在站台发现名单并与同伴发生冲突",
        ])
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("gate_passed_final"))
        actions = payload.get("auto_retry_actions", [])
        self.assertTrue(any("迁移误放章节" in x for x in actions))
        self.assertFalse(kb_bad.exists())

    def test_continue_write_idempotent_cache_hit(self):
        run_cmd([
            "one-click",
            "--project-root",
            str(self.tmpdir),
            "--title",
            "雾港回声",
            "--genre",
            "悬疑",
            "--idea",
            "主角在旧港区发现失踪名单",
        ])
        _, p1 = run_cmd([
            "continue-write",
            "--project-root",
            str(self.tmpdir),
            "--query",
            "主角在站台发现名单并与同伴发生冲突",
        ])
        _, p2 = run_cmd([
            "continue-write",
            "--project-root",
            str(self.tmpdir),
            "--chapter-file",
            p1.get("chapter_file"),
            "--query",
            "主角在站台发现名单并与同伴发生冲突",
        ])
        _, p3 = run_cmd([
            "continue-write",
            "--project-root",
            str(self.tmpdir),
            "--chapter-file",
            p1.get("chapter_file"),
            "--query",
            "主角在站台发现名单并与同伴发生冲突",
        ])
        self.assertTrue(p1.get("ok"))
        self.assertTrue(p2.get("ok"))
        self.assertTrue(p3.get("idempotent_hit"))

    def test_continue_write_rollback_on_failure(self):
        run_cmd([
            "one-click",
            "--project-root",
            str(self.tmpdir),
            "--title",
            "雾港回声",
            "--genre",
            "悬疑",
            "--idea",
            "主角在旧港区发现失踪名单",
        ])
        chapter = self.tmpdir / "03_manuscript" / "第2章-短章.md"
        chapter.write_text("# 第2章 短章\n\n这是一段极短正文。", encoding="utf-8")
        before = chapter.read_text(encoding="utf-8")

        _, payload = run_cmd([
            "continue-write",
            "--project-root",
            str(self.tmpdir),
            "--chapter-file",
            str(chapter),
            "--query",
            "主角推进剧情",
            "--no-auto-draft",
            "--no-auto-improve",
            "--no-auto-retry",
            "--min-paragraphs",
            "12",
            "--force-run",
        ])
        self.assertFalse(payload.get("ok"))
        self.assertTrue(payload.get("rollback_applied"))
        after = chapter.read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_continue_write_auto_fix_quality_baseline(self):
        run_cmd([
            "one-click",
            "--project-root",
            str(self.tmpdir),
            "--title",
            "雾港回声",
            "--genre",
            "悬疑",
            "--idea",
            "主角在旧港区发现失踪名单",
        ])
        chapter = self.tmpdir / "03_manuscript" / "第2章-短章.md"
        chapter.write_text("# 第2章 短章\n\n主角发现线索。", encoding="utf-8")

        _, payload = run_cmd([
            "continue-write",
            "--project-root",
            str(self.tmpdir),
            "--chapter-file",
            str(chapter),
            "--query",
            "主角继续调查并与同伴沟通",
            "--no-auto-draft",
            "--no-auto-improve",
            "--auto-retry",
            "--min-chars",
            "300",
            "--min-paragraphs",
            "4",
            "--min-sentences",
            "4",
            "--force-run",
        ])
        self.assertTrue(payload.get("ok"))
        self.assertTrue(payload.get("gate_passed_final"))
        actions = payload.get("auto_retry_actions", [])
        self.assertTrue(any("质量最小修复" in x for x in actions))


if __name__ == "__main__":
    unittest.main()
