# 新剧情写作上下文建议（RAG）

- 查询：主角在站台发现名单并与同伴发生冲突
- 命中角色：无
- 检索统计：候选池=1 / 总文档=1 / 估算上下文字符=74

## 建议先读（固定）
- 00_memory/novel_plan.md
- 00_memory/novel_state.md

## 建议回读章节（Top）
1. `第1章-开篇待写.md` | score=5.5 | 命中={'token_overlap': 2, 'summary_overlap': 2, 'entity_overlap': 0, 'event_overlap': 1, 'recency': 1.0, 'conflict_bonus': 0.2}
   摘要：# 第1章 开篇 <!-- NOVEL_FLOW_STUB --> ## 本章目标 - 建立主角目标：明确主角核心目标 - 落地核心冲突：主线冲突待细化 ## 场景草图 - 起始地点： - 冲突触发点： - 章末钩子： ## 正文 [待写]
   元数据：事件=冲突
   关键片段：
   - ## 本章目标
- 建立主角目标：明确主角核心目标
- 落地核心冲突：主线冲突待细化 (reason={'token_overlap': 2, 'entity_overlap': 0}, score=2.0)
   - ## 场景草图
- 起始地点：
- 冲突触发点：
- 章末钩子： (reason={'token_overlap': 1, 'entity_overlap': 0}, score=1.0)

## 角色关系相关片段
- 无命中（可补充 character_tracker）

## 写作前执行建议
1. 读取上述 Top 章节，确认人物关系与伏笔状态。
2. 若发现冲突，先执行 /检查一致性 再写作。
3. 写作后继续执行门禁链路。
