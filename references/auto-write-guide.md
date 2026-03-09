# 一键写书（自动化调度模式）指南

> 从 SKILL.md v8.0 第10节抽取，详细用法参考本文档。

> 能力状态：`[部分实现]`。调度框架、断点续写、进度报告已就绪。端到端全自动执行依赖知识图谱、大纲锚点等规划中机制的补全。

## 概述

`/一键写书 简介="..." [目标字数=200万] [调研深度=standard]`

用户提供简介和目标字数后，系统按调度框架自动编排写作流程。当前版本需要在关键节点（如卷间过渡、门禁反复失败时）进行人工确认；规划中的增强机制就位后可支撑完全无人干预的端到端执行。

## 执行流程

1. 解析简介，提取题材、核心冲突、主角目标
2. 运行 `/联网调研` 进行基础调研（按题材自动生成调研维度）
3. 自动执行 `/一键开书` 初始化项目（建模+建库+首章准备）
4. 循环执行（直到达到目标字数）：
   a. 分析本章知识需求，检测缺口
   b. `/联网调研` 补充缺失资料
   c. `/继续写` 完成写作+门禁
   d. 门禁失败 → 自动修复（最多3次）
   e. 每10章冲刺复盘
   f. 每卷结束输出进度报告
5. 生成完成报告

## 断点续写

中断后再次执行 `/一键写书`，系统自动从断点恢复。

## 脚本命令

```bash
# 生成执行计划（不实际执行）
python3 scripts/auto_novel_writer.py plan \
  --synopsis "<简介>" --target-chars 2000000 --genre <题材> --research-depth standard

# 启动全自动写作
python3 scripts/auto_novel_writer.py run \
  --project-root <目录> --synopsis "<简介>" --target-chars 2000000

# 查看当前进度
python3 scripts/auto_novel_writer.py report --project-root <目录>

# 更新进度（供外部脚本调用）
python3 scripts/auto_novel_writer.py progress \
  --project-root <目录> --chapter 15 --chars-added 3500 --gate-passed
```

## 支持的 LLM

- OpenAI (GPT-4 / GPT-4-Turbo)
- Anthropic (Claude 3/4)
- Kimi 2.5 (Moonshot)
- GLM-5 (智谱)
- MiniMax 2.5
- 任意 OpenAI 兼容 API

LLM 配置详见 `user-guide.md` 第3节。
