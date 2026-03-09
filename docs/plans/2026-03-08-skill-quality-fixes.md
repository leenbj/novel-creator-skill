# Novel Creator Skill 质量修复实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 skill-creator 评审识别的全部遗留问题，使 SKILL.md 达到 skill-forge 高质量标准。

**Architecture:** 三类修复——(1) 补全缺失参考文档；(2) 强化 SKILL.md 结构（Iron Law + Checklist）。所有修改在原工作目录直接执行，无需隔离工作区。

**Tech Stack:** Markdown 文档编写，Python 脚本结构了解，SKILL.md skill-forge 规范。

---

## Task 1：创建 references/humanizer-guide.md

**Files:**
- Create: `references/humanizer-guide.md`

**内容要求：**
- `/校稿` 命令的完整使用说明
- 两遍式润色流程（第一遍：清除AI模式；第二遍：自审+修改）
- 24类AI模式清单（翻译腔、过度总结、对话同质化等）
- text_humanizer.py 脚本用法（如存在）
- 与写作流程的集成说明

---

## Task 2：创建 references/editorial-team-protocol.md

**Files:**
- Create: `references/editorial-team-protocol.md`

**内容要求：**
- 编辑团队架构（总编辑/策划主编/写作特工/反AI编辑/连载核实官）
- 各角色职责与禁止行为
- 正文隔离协议（P0检测触发器）
- editorial_team_manager.py 脚本用法
- 人工介入条件与流程

---

## Task 3：SKILL.md 补充 Iron Law

**Files:**
- Modify: `SKILL.md`

**内容要求：**
- 在文件顶部（frontmatter 之后，第1节之前）插入 Iron Law 段落
- 使用 ⛔ 符号标记绝对禁止项
- 内容覆盖：绕过门禁、跳过确认步骤、混淆正文与元信息等核心约束

---

## Task 4：SKILL.md 主流程 Checklist 提升

**Files:**
- Modify: `SKILL.md`

**内容要求：**
- 在第4节"强制章节闭环"中，将5个步骤改为可勾选 Checklist 格式（`- [ ]`）
- 每步加上 ⚠️（警告）或 ⛔（禁止跳过）标记
- 说明跳过任一步骤的后果

---

## Task 5：更新 plans/task_plan.md

**Files:**
- Modify: `plans/task_plan.md`

**内容：** 标记所有任务完成，记录最终状态。
