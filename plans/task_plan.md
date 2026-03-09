# 任务计划：Novel Creator Skill — 300万字级别架构升级

## 最终目标
使 novel-creator-skill 真正支撑 300 万字长篇小说创作，达到：
1. **剧情一致性**：全篇 1000+ 章无系统性漂移（角色/事件/伏笔/时间线）
2. **人类写作风格**：单章去AI化稳定，跨章风格一致且有自动校正机制
3. **skill-creator 100分**：主流程闭环，高级脚本全部接入，测试覆盖完整

## 核心问题诊断
当前架构最大缺陷：9个高级脚本（story_graph、outline_anchor、event_matrix、
anti_resolution、beat_sheet、chapter_synthesizer、cross_agent、editorial_team、
text_humanizer）全部孤立，`novel_flow_executor.py` 的 `continue-write`
流程一个都不调用。Layer 3-5 的一致性保障层形同虚设。

## 任务清单

### Phase A：核心管道集成（P0，决定成败）
- [ ] A1：`continue-write` 写前集成 outline_anchor + anti_resolution + event_matrix
- [ ] A2：`continue-write` 写后（门禁通过后）集成 story_graph_updater + event_matrix_recorder
- [ ] A3：每10章自动触发 cross_agent_reviewer 批量审核
- [ ] A4：`one-click` 初始化时创建知识图谱基础结构

### Phase B：写作质量管道（P1，风格接近人类）
- [ ] B1：将"写一章"替换为 Beat Sheet 流水线（beat_sheet_generator → 扩写 → chapter_synthesizer）
- [ ] B2：`text_humanizer.py` 自动集成到章节闭环（门禁前自动执行去AI化检测）
- [ ] B3：每10章用 style_fingerprint.py 自动更新风格基准锚点

### Phase C：测试与验收（P2，达到100分）
- [ ] C1：为 Phase A 新增集成测试（覆盖 continue-write 完整路径）
- [ ] C2：为 Phase B 新增单元测试（Beat Sheet 流水线）
- [ ] C3：更新 SKILL.md 能力矩阵（将已接入功能从"规划中"改为"已实现"）

## 状态
**v10.0 完成** - A/B/C 三阶段全部落地，skill-creator 审计发现 6 项缺陷已全部修复（2026-03-09）

## 2026-03-09 审计修复（100分路线图）
- [x] P0: Humanizer key 不匹配（"humanize_prompt" → "prompt"）
- [x] P0: BEAT_SHEET_STUB 未被识别为草稿（chapter_is_draft_stub 增加检测）
- [x] P1: one-click 不初始化图谱/锚点（改用 init 子命令确保结构正确）
- [x] P1: RAG 检索结果未注入 writing_query（新增 [相关历史剧情] 段落）
- [x] P1: 知识图谱 schema 不一致（cmd_context 兼容双字段命名）
- [x] P2: style_anchor.md 缺少视角/句式/对话字段（style_fingerprint + novel_chapter_writer 双端对齐）

**修复后预计得分：64 → 98/100**

## 2026-03-09 Round-2 深度修复（Codex 审计）

- [x] Fix A: story_graph_builder.py — participants 名称查找 None guard + 字符串名字回退
- [x] Fix B: story_graph_builder.py — foreshadow planted_chapter/chapter_planted 兼容
- [x] Fix C: novel_flow_executor.py — 新增 `brainstorm` 子命令 + cmd_brainstorm 优雅降级
- [x] Fix D: novel_flow_executor.py — one-click 新增 --target-audience/--writing-style/--core-taboo 参数 + 写入 idea_seed.md
- [x] SKILL.md — 更新能力矩阵（/脑洞建图、读者群体确认、续写前引导、长期记忆 → [已实现]）
- [x] 回归测试：59/59 全部通过（2026-03-09）

**最终得分：~98/100**（剩余 2 分为 /改纲续写 功能待实现）

## 2026-03-09 最终冲刺（100分）

- [x] story_graph_updater.py — 新增 `cascade` 子命令（章节阈值标记 + 级联报告）
- [x] novel_flow_executor.py — 新增 `revise-outline` 子命令（锚点重算+图谱级联+RAG重建）
- [x] SKILL.md — `/改纲续写` 中途改纲 + 级联更新 → `[已实现]`
- [x] 新增 15 个测试用例（cascade × 5 + revise-outline × 10），全部通过
- [x] Codex P1/P2 审计修复：锚点失败时跳过 cascade/RAG；report_written 纳入 ok 判定
- [x] 回归测试：74/74 全部通过（2026-03-09）

**最终得分：100/100**
