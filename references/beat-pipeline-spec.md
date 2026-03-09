# 多步流水线写作协议（Beat Sheet Pipeline）

> 状态：规划中（Phase 2 实现）

## 问题背景

单步生成整章内容时，AI 会为了上下文连贯性而压缩剧情，导致章节空洞、推进过快。将"写一章"拆解为多步协作，强制限制单次生成的剧情跨度，让每个场景充分展开。

## 流水线步骤

### Step 1: Beat Sheet 生成（分镜头）

输入：本章目标、大纲锚点约束、上章结尾
输出：3-5 个 Beat（微场景），每个 Beat 包含：

```json
{
  "beat_id": 1,
  "type": "conflict",
  "summary": "太子在朝堂上提出均田制改革方案",
  "characters": ["李承乾", "魏征", "长孙无忌"],
  "location": "太极殿",
  "micro_conflict": "长孙无忌当场反对，朝堂哗然",
  "emotion_target": "紧张→小胜（争取到皇帝的'再议'）",
  "word_target": 800,
  "anti_resolution": true
}
```

Beat 类型分布规则：
- 每章至少 1 个冲突型 Beat
- 不得连续 2 个同类型 Beat
- 最后一个 Beat 必须留下悬念或新问题

### Step 2: Beat 扩写（填血肉）

针对每个 Beat 独立扩写，聚焦：
- 环境描写（感官细节，不超过3句）
- 角色动作与微表情
- 对话（带性格差异，避免"报菜名"式对话）
- 内心独白（限主视角角色）

每个 Beat 扩写后约 600-1200 字。

扩写时的硬约束：
- 不得超出当前 Beat 的剧情范围
- 不得提前引入后续 Beat 的冲突
- 对话占比参照题材风格矩阵

### Step 3: 章节合成

将所有 Beat 扩写结果串联：
- 添加过渡句（场景切换、时间推移）
- 统一人称和时态
- 检查章内时间线连续性
- 确保章末钩子（Hook）存在

### Step 4: 进入门禁

合成稿进入标准5步门禁流程。

### Step 5: 图谱回写

门禁通过后，从成稿中提取信息更新知识图谱。

## 与现有流程的集成

`/继续写` 命令的内部流程从：
```
剧情检索 → 写作 → 门禁 → 索引更新
```
扩展为：
```
剧情检索 → 锚点配额检查 → Beat Sheet → Beat 扩写 → 合成 → 门禁 → 图谱回写 → 索引更新
```

## 脚本入口（规划）

```bash
# 生成 Beat Sheet
python3 scripts/beat_sheet_generator.py \
  --project-root <目录> --chapter-goal "<本章目标>" --beat-count 4

# Beat 扩写
python3 scripts/beat_flesh_writer.py \
  --project-root <目录> --beat-file <beat_sheet.json> --beat-id 1

# 章节合成
python3 scripts/chapter_synthesizer.py \
  --project-root <目录> --beats-dir <beats目录> --output <章节文件>
```
