# Novel Creator Skill v10.0 架构设计

> 目标：支撑 300 万字长篇小说创作，剧情不混乱，写作风格接近人类，skill-creator 100 分。

---

## 设计原则

1. **最大自动化**：所有高级功能默认开启，用户无需传额外参数
2. **最小介入**：用户唯一需要做的是确认剧情方向，其余全部自动化
3. **闭环保障**：每个功能的"写入"和"读取"必须同时存在，单向管道无效

---

## 完整管道设计

### continue-write 新流程

```
写前阶段：
  1. plot_rag_retriever query        ← 已有
  2. story_graph_builder generate-context  ← 新增：角色/地点/关系状态注入
  3. outline_anchor check            ← 已有（默认改为ON）
  4. anti_resolution check           ← 已有（默认改为ON）
  5. event_matrix recommend          ← 已有（默认改为ON）
  → 合并注入 writing_query

写作阶段：
  6. beat_sheet_generator generate   ← 新增：生成5-8个Beat节点
  7. LLM/模板 按Beat扩写             ← 新增：逐Beat生成正文段落
  8. chapter_synthesizer merge       ← 新增：合成完整章节草稿

门禁阶段：
  9. text_humanizer detect           ← 已有（自动运行）
  10. [AI模式>阈值] → build_humanize_prompt → 自动重写 → 重新检测（最多2轮）  ← 新增
  11. 质量评估 → 门禁检查            ← 已有

门禁通过后：
  12. story_graph_updater extract + apply  ← 修复：补充 apply 调用
  13. outline_anchor advance         ← 修复：补充 advance 调用
  14. [每10章] cross_agent_reviewer  ← 已有（默认改为ON）
  15. [每10章] style_fingerprint 更新风格基准  ← 新增
  16. plot_rag_retriever build       ← 已有
```

---

## 需要新增的功能

### A. story_graph_builder: generate-context 子命令

**输入**：project_root, chapter_no（可选：关注的角色名列表）
**输出**：JSON，包含：
```json
{
  "ok": true,
  "context_prompt": "当前已知角色状态：\n- 李逍遥：位于蜀山...\n- 赵灵儿：...\n关键关系：...\n活跃伏笔：...",
  "active_foreshadows": [...],
  "character_locations": {...},
  "recent_events": [...]
}
```

实现逻辑：从 `story_graph.json` 中提取：
- 所有 character 节点的 `location` 和 `status` 字段
- 所有 `foreshadow` 节点中 `resolved: false` 的条目
- 最近5个 `event` 节点的摘要

### B. text_humanizer 自动纠正循环

在 `write_gate_artifacts` 函数中扩展现有逻辑：

```
当前：detect → report（报告AI模式，不纠正）
新增：detect → [severity >= medium] → build_humanize_prompt → 写入章节文件 → 重新detect
      最多2轮，超过2轮则在报告中标记 "需要人工校稿"
```

### C. Beat Sheet 写作流水线

新增参数 `--use-beat-sheet`（默认True），替换当前的模板draft生成：

```python
# 替换 generate_draft_text() 调用
beats = run_python("beat_sheet_generator.py", ["generate", ...])
for beat in beats:
    segment = llm_write_segment(beat) or template_fill(beat)
chapter_draft = run_python("chapter_synthesizer.py", ["merge", segments])
```

降级策略：无LLM时，Beat节点作为提纲占位符，保留 `<!-- BEAT: xxx -->` 标记。

### D. story_graph_updater apply 补充

在 `--auto-graph-update` 逻辑中，在 `extract` 后立即调用 `apply`：

```python
run_python("story_graph_updater.py", ["extract", ...])
run_python("story_graph_updater.py", ["apply", ...])  # 新增
```

### E. outline_anchor advance 补充

门禁通过后，调用 `outline_anchor advance`：

```python
if gate_passed_final and args.enable_constraints:
    run_python("outline_anchor_manager.py", ["advance", ...])  # 新增
```

### F. style_fingerprint 每10章自动更新

新增参数 `--auto-style-update`（默认True），`--style-update-interval`（默认10）：

```python
if gate_passed_final and args.auto_style_update and chapter_count % args.style_update_interval == 0:
    run_python("style_fingerprint.py", ["extract", "--project-root", ...])
```

---

## 默认值变更

| 参数 | 旧默认 | 新默认 | 理由 |
|------|--------|--------|------|
| `--enable-constraints` | False | True | 核心保障层，应默认开启 |
| `--auto-graph-update` | False | True | 图谱不更新等于没有 |
| `--auto-batch-review` | False | True | 长篇必须有批量审核 |
| `--auto-research` | False | True | 知识缺口自动检测 |
| `--use-beat-sheet` | N/A | True | 新增，默认开启 |
| `--auto-style-update` | N/A | True | 新增，默认开启 |

---

## 验收标准

1. `continue-write` 不带任何额外参数，能自动执行完整16步管道
2. 连续执行50章，`story_graph.json` 中节点数随章节增加（验证图谱确实在更新）
3. 连续执行50章，`outline_anchor.json` 中 `current_chapter` 随章节推进（验证锚点确实在推进）
4. text_humanizer 检测 severity=high 时，输出文件的AI模式密度低于检测前
5. 第10/20/30章后，风格基准文件时间戳更新（验证风格锚点在自动更新）
6. 所有集成测试通过，`py_compile` 零错误
7. SKILL.md 能力矩阵全部功能状态更新为"已实现"

---

## 实施阶段划分

- **Phase A**（核心数据闭环）：E(advance) + D(apply) + A(generate-context) 接入
- **Phase B**（写作质量管道）：C(Beat Sheet) + B(humanizer纠正循环) + F(风格更新)
- **Phase C**（默认值 + 测试 + SKILL.md）：全部参数默认改为True + 集成测试 + 文档更新
