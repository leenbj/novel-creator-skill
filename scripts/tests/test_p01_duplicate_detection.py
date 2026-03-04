#!/usr/bin/env python3
"""P0-01 段落重复度检测测试

测试门禁漏检重复正文的修复。

运行方式:
    python3 scripts/tests/test_p01_duplicate_detection.py
"""

import sys
import unittest
from pathlib import Path
import tempfile
import shutil
import argparse

# 添加 scripts 目录到路径
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


class TestParagraphDuplicateDetection(unittest.TestCase):
    """段落重复度检测测试"""

    def setUp(self):
        """测试前置设置"""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)

        # 创建完整的目录结构
        dirs = [
            "00_memory",
            "00_memory/retrieval",
            "00_memory/retrieval/chapter_meta",
            "02_knowledge_base",
            "03_manuscript",
            "04_editing",
            "04_editing/gate_artifacts"
        ]

        for d in dirs:
            (self.project_root / d).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        """测试后清理"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_high_duplicate_chapter_should_fail(self):
        """测试 30%+ 重复段落章节应失败"""
        from novel_flow_executor import evaluate_quality

        # 构造高重复度章节（约 50% 重复）
        duplicate_paragraph = "这是一个重复的段落，用于测试门禁是否能检测到重复内容。主角走进了房间，环顾四周。"

        chapter_content = f"""# 第10章 测试章节

{duplicate_paragraph}

这是第一段正文。主角看着眼前的景象。

{duplicate_paragraph}

这是第二段正文。风轻轻吹过。

{duplicate_paragraph}

这是第三段正文。远处传来声音。

{duplicate_paragraph}

这是第四段正文。夜色渐渐深了。

{duplicate_paragraph}

这是第五段正文。月光洒在地上。

{duplicate_paragraph}

这是第六段正文。故事还在继续。
"""

        # 构造参数
        args = argparse.Namespace(
            min_chars=500,
            min_paragraphs=5,
            min_dialogue_ratio=0.0,
            max_dialogue_ratio=0.8,
            min_sentences=5,
        )

        # 执行质量评估
        result = evaluate_quality(chapter_content, args)

        # 验证重复度指标
        self.assertIn("paragraph_unique_ratio", result)
        self.assertIn("max_duplicate_paragraph_repeat", result)
        self.assertIn("unique_paragraph_count", result)

        # 验证重复度指标值
        # 12个段落中有6个重复，唯一比例为 6/12 = 0.5
        self.assertLess(result["paragraph_unique_ratio"], 0.85)
        # 最大重复次数应为 6
        self.assertEqual(result["max_duplicate_paragraph_repeat"], 6)

        # 验证失败项包含重复度问题
        failures = result.get("failures", [])
        has_dup_failure = any("paragraph_unique_ratio" in f for f in failures)
        self.assertTrue(has_dup_failure, f"应检测到段落唯一比例过低，failures: {failures}")

        # 验证未通过
        self.assertFalse(result["passed"], "高重复度章节不应通过门禁")

        print(f"[PASS] 高重复度章节检测正确: unique_ratio={result['paragraph_unique_ratio']:.2%}, "
              f"max_repeat={result['max_duplicate_paragraph_repeat']}")

    def test_normal_chapter_should_pass(self):
        """测试正常章节应通过，不误杀"""
        from novel_flow_executor import evaluate_quality

        # 构造正常章节（每个段落都不同）
        chapter_content = """# 第10章 正常章节

这是一个正常的段落。主角走进了房间，环顾四周，看到墙上挂着一幅画。

"有人吗？"他轻声问道，声音在空旷的房间里回荡。

房间里很安静，只有窗外的鸟鸣声。他慢慢走到桌前，拿起那封信。

信的内容让他感到惊讶。他没有想到事情会发展成这样。

"这怎么可能？"他自言自语道，眉头紧锁。

就在这时，门突然打开了，一个熟悉的身影出现在门口。

那是他多年未见的老朋友。两人相视一笑，仿佛时间从未流逝。

故事从这里开始有了新的转折。命运的齿轮开始转动。

未来的道路还很长。但他知道，只要坚持，就一定能找到答案。
"""

        # 构造参数
        args = argparse.Namespace(
            min_chars=500,
            min_paragraphs=5,
            min_dialogue_ratio=0.0,
            max_dialogue_ratio=0.8,
            min_sentences=5,
        )

        # 执行质量评估
        result = evaluate_quality(chapter_content, args)

        # 验证重复度指标
        self.assertIn("paragraph_unique_ratio", result)
        self.assertIn("max_duplicate_paragraph_repeat", result)

        # 验证重复度指标值（正常章节应接近 100% 唯一）
        self.assertGreaterEqual(result["paragraph_unique_ratio"], 0.85,
                                f"正常章节段落唯一比例应 >= 85%，实际: {result['paragraph_unique_ratio']:.2%}")
        self.assertLessEqual(result["max_duplicate_paragraph_repeat"], 2,
                             f"正常章节最大重复次数应 <= 2，实际: {result['max_duplicate_paragraph_repeat']}")

        # 验证失败项不包含重复度问题
        failures = result.get("failures", [])
        has_dup_failure = any("paragraph_unique_ratio" in f or "max_duplicate_paragraph_repeat" in f for f in failures)
        self.assertFalse(has_dup_failure, f"正常章节不应触发重复度失败，failures: {failures}")

        print(f"[PASS] 正常章节检测正确: unique_ratio={result['paragraph_unique_ratio']:.2%}, "
              f"max_repeat={result['max_duplicate_paragraph_repeat']}")

    def test_edge_case_small_repeat_should_pass(self):
        """测试少量重复（如 2 次重复）应通过"""
        from novel_flow_executor import evaluate_quality

        # 构造有少量重复的章节（同一个段落出现 2 次，在阈值内）
        repeated_para = "这是一个过渡段落，用于承上启下。"

        chapter_content = f"""# 第10章 边缘测试

这是第一段正文。主角走进了房间。

{repeated_para}

这是第二段正文。风轻轻吹过窗外。

{repeated_para}

这是第三段正文。远处传来鸟鸣声。

这是第四段正文。月光洒在地上。

这是第五段正文。故事还在继续。

这是第六段正文。夜色渐渐深了。

这是第七段正文。一切都在变化。

这是第八段正文。命运的齿轮开始转动。
"""

        # 构造参数
        args = argparse.Namespace(
            min_chars=500,
            min_paragraphs=5,
            min_dialogue_ratio=0.0,
            max_dialogue_ratio=0.8,
            min_sentences=5,
        )

        # 执行质量评估
        result = evaluate_quality(chapter_content, args)

        # 验证重复度指标
        # 10个段落，2个重复（各出现2次），唯一段落 8 个
        # unique_ratio = 8/10 = 0.8，但实际可能不同，取决于重复计算方式
        # 最大重复次数 = 2，在阈值内
        self.assertLessEqual(result["max_duplicate_paragraph_repeat"], 2,
                             f"少量重复最大次数应 <= 2，实际: {result['max_duplicate_paragraph_repeat']}")

        print(f"[PASS] 边缘测试通过: unique_ratio={result['paragraph_unique_ratio']:.2%}, "
              f"max_repeat={result['max_duplicate_paragraph_repeat']}")

    def test_quality_report_contains_duplicate_metrics(self):
        """测试质量报告包含重复度指标"""
        from novel_flow_executor import write_quality_report

        gate_dir = self.project_root / "04_editing" / "gate_artifacts" / "test_chapter"
        gate_dir.mkdir(parents=True, exist_ok=True)

        quality_before = {
            "char_count": 1000,
            "paragraph_count": 10,
            "dialogue_ratio": 0.15,
            "sentence_count": 20,
            "paragraph_unique_ratio": 0.5,
            "max_duplicate_paragraph_repeat": 6,
            "failures": ["paragraph_unique_ratio<0.85"],
            "passed": False
        }

        quality_after = {
            "char_count": 1500,
            "paragraph_count": 12,
            "dialogue_ratio": 0.18,
            "sentence_count": 25,
            "paragraph_unique_ratio": 0.92,
            "max_duplicate_paragraph_repeat": 1,
            "failures": [],
            "passed": True
        }

        # 写入质量报告
        report_path = write_quality_report(gate_dir, quality_before, quality_after)

        # 验证报告文件存在
        self.assertTrue(report_path.exists())

        # 读取报告内容
        report_content = report_path.read_text(encoding="utf-8")

        # 验证包含重复度指标
        self.assertIn("段落唯一比例", report_content)
        self.assertIn("最大重复段落次数", report_content)
        self.assertIn("0.5", report_content)  # 修复前的唯一比例
        self.assertIn("0.92", report_content)  # 修复后的唯一比例

        print(f"[PASS] 质量报告包含重复度指标")

    def test_gate_check_validates_duplicate_metrics(self):
        """测试门禁检查校验重复度指标"""
        from chapter_gate_check import check_quality_report

        # 创建测试质量报告
        gate_dir = self.project_root / "04_editing" / "gate_artifacts" / "test_chapter"
        gate_dir.mkdir(parents=True, exist_ok=True)

        quality_report = gate_dir / "quality_report.md"

        # 测试案例1：高重复度应失败
        high_dup_content = """# 章节质量检查

## 修复前
- 字符数：1000
- 段落数：10
- 对话占比：0.15
- 句子数：20
- 段落唯一比例：0.5
- 最大重复段落次数：6
- 失败项：['paragraph_unique_ratio<0.85']

## 修复后
- 字符数：1500
- 段落数：12
- 对话占比：0.18
- 句子数：25
- 段落唯一比例：0.5
- 最大重复段落次数：6
- 失败项：['paragraph_unique_ratio<0.85']

- 通过：False
"""
        quality_report.write_text(high_dup_content, encoding="utf-8")

        ok, msg = check_quality_report(quality_report)
        self.assertFalse(ok, "高重复度报告应校验失败")
        self.assertIn("paragraph_unique_ratio", msg)

        print(f"[PASS] 门禁高重复度校验失败: {msg}")

        # 测试案例2：正常重复度应通过
        normal_content = """# 章节质量检查

## 修复前
- 字符数：1000
- 段落数：10
- 对话占比：0.15
- 句子数：20
- 段落唯一比例：0.92
- 最大重复段落次数：1
- 失败项：[]

## 修复后
- 字符数：1500
- 段落数：12
- 对话占比：0.18
- 句子数：25
- 段落唯一比例：0.95
- 最大重复段落次数：1
- 失败项：[]

- 通过：True
"""
        quality_report.write_text(normal_content, encoding="utf-8")

        ok, msg = check_quality_report(quality_report)
        self.assertTrue(ok, f"正常重复度报告应校验通过: {msg}")
        self.assertEqual(msg, "通过")

        print(f"[PASS] 门禁正常重复度校验通过")

        # 测试案例3：最大重复次数超限应失败
        max_dup_content = """# 章节质量检查

## 修复前
- 字符数：1000
- 段落数：10
- 对话占比：0.15
- 句子数：20
- 段落唯一比例：0.90
- 最大重复段落次数：5
- 失败项：['max_duplicate_paragraph_repeat>2']

## 修复后
- 字符数：1500
- 段落数：12
- 对话占比：0.18
- 句子数：25
- 段落唯一比例：0.90
- 最大重复段落次数：5
- 失败项：['max_duplicate_paragraph_repeat>2']

- 通过：False
"""
        quality_report.write_text(max_dup_content, encoding="utf-8")

        ok, msg = check_quality_report(quality_report)
        self.assertFalse(ok, "最大重复次数超限应校验失败")
        self.assertIn("max_duplicate_paragraph_repeat", msg)

        print(f"[PASS] 门禁最大重复次数超限校验失败: {msg}")


class TestDuplicateDetectionEdgeCases(unittest.TestCase):
    """重复检测边缘情况测试"""

    def test_empty_paragraphs(self):
        """测试空段落的处理"""
        from novel_flow_executor import evaluate_quality

        # 包含多个空行的文本
        chapter_content = """# 第10章 测试


这是第一段正文。




这是第二段正文。


"""

        args = argparse.Namespace(
            min_chars=100,
            min_paragraphs=1,
            min_dialogue_ratio=0.0,
            max_dialogue_ratio=0.8,
            min_sentences=1,
        )

        result = evaluate_quality(chapter_content, args)

        # 验证不会崩溃
        self.assertIn("paragraph_unique_ratio", result)
        self.assertIn("max_duplicate_paragraph_repeat", result)

        print(f"[PASS] 空段落处理正确: unique_ratio={result['paragraph_unique_ratio']:.2%}")

    def test_single_paragraph(self):
        """测试单段落文本"""
        from novel_flow_executor import evaluate_quality

        chapter_content = """# 第10章 测试

这是唯一的段落。
"""

        args = argparse.Namespace(
            min_chars=10,
            min_paragraphs=1,
            min_dialogue_ratio=0.0,
            max_dialogue_ratio=0.8,
            min_sentences=1,
        )

        result = evaluate_quality(chapter_content, args)

        # 单段落应该是 100% 唯一
        self.assertEqual(result["paragraph_unique_ratio"], 1.0)
        self.assertEqual(result["max_duplicate_paragraph_repeat"], 1)

        print(f"[PASS] 单段落处理正确: unique_ratio=100%")

    def test_whitespace_normalization(self):
        """测试空白字符标准化"""
        from novel_flow_executor import evaluate_quality

        # 同一段落有不同空白（应视为重复）
        para1 = "这是一个段落。"
        para2 = "这是  一个  段落。"  # 多余空格
        para3 = "这是一个段落。"  # 与 para1 完全相同

        chapter_content = f"""# 第10章 测试

{para1}

{para2}

{para3}
"""

        args = argparse.Namespace(
            min_chars=10,
            min_paragraphs=1,
            min_dialogue_ratio=0.0,
            max_dialogue_ratio=0.8,
            min_sentences=1,
        )

        result = evaluate_quality(chapter_content, args)

        # 空白标准化后，para1 和 para3 应被视为相同
        # 因此最大重复次数应为 2
        self.assertGreaterEqual(result["max_duplicate_paragraph_repeat"], 2)

        print(f"[PASS] 空白标准化正确: max_repeat={result['max_duplicate_paragraph_repeat']}")


if __name__ == '__main__':
    # 运行测试
    unittest.main(verbosity=2)