# 门禁产物规范

每章都必须在以下目录产生产物：
- `04_editing/gate_artifacts/<chapter_id>/`

必需文件：
1. `memory_update.md`
2. `consistency_report.md`
3. `style_calibration.md`
4. `copyedit_report.md`
5. `publish_ready.md`
6. `gate_result.json`（由校验脚本自动生成）

## 生成与校验顺序
1. `/更新记忆` 生成 `memory_update.md`
2. `/检查一致性` 生成 `consistency_report.md`
3. `/风格校准` 生成 `style_calibration.md`
4. `/校稿` 生成 `copyedit_report.md` 与 `publish_ready.md`
5. `/门禁检查` 执行脚本写入 `gate_result.json`

## 通过标准
- 所有必需文件存在且非空。
- 文件修改时间不早于章节文件。
- `publish_ready.md` 必须包含发布关键词（默认：可发布/通过/PASS）。
