# Novel Creator Skill 审计报告

- 审计日期: 2026-03-04
- 审计对象: `leenbj/novel-creator-skill`
- 本地路径: `/Users/ethan/Desktop/小说/novel-creator-skill`
- 审计基线提交: `6dcbab3`
- 审计框架:
  - `code-review-expert`（工程代码审计）
  - `skill-forge`（技能工程质量审计）
- 审计结论: `REQUEST_CHANGES`

---

## 1. 执行摘要

本次审计发现该仓库存在阻塞级问题（P0），导致核心命令链路在默认环境下无法稳定执行：

1. `one-click` 流程因 `performance.py` 的 `Any` 未导入触发运行时错误。
2. `content_expansion_engine.py` 存在语法错误，导致相关模块与测试不可用。

同时存在高优先级工程问题：

1. 技能元数据版本与文档版本漂移（`v8.0` vs `7.2.0`）。
2. `SKILL.md` 引用不存在文档 `references/tutorials.md`。
3. 安装脚本在 `--force` + 自定义 `--dest` 场景缺乏危险路径保护。

从 `skill-forge` 标准看：该 skill “结构合法且可触发”，但未达到“高质量技能”标准（缺 Iron Law、缺可勾选 checklist、引用失配、测试健康度不足）。

---

## 2. 审计范围与方法

### 2.1 范围

- 仓库总文件: 79
- `scripts/`: 23
- `references/`: 7
- 关键入口:
  - `SKILL.md`
  - `scripts/novel_flow_executor.py`
  - `scripts/chapter_gate_check.py`
  - `scripts/plot_rag_retriever.py`
  - `scripts/novel_chapter_writer.py`
  - `scripts/install-portable-skill.sh`

### 2.2 方法

- 静态检查:
  - 结构与元数据一致性检查
  - 安全与可靠性扫描（路径、子进程、异常处理、数据写入）
  - 规则合规检查（`skill-forge`）
- 动态验证:
  - 运行回归测试
  - 运行 `one-click` 关键链路
  - Python 语法编译检查

---

## 3. 关键验证结果（证据）

### 3.1 测试结果

1. `PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_novel_flow_executor.py`
   - 结果: 6 项测试，失败 5 项。
2. `python3 -m unittest discover -s scripts/tests -p 'test_*.py'`
   - 结果: 41 项测试，`1 fail + 4 error`。

### 3.2 编译结果

1. `PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile scripts/*.py`
   - 结果: `scripts/content_expansion_engine.py` 语法错误（行 235）。

### 3.3 关键命令链路

1. `python3 scripts/novel_flow_executor.py one-click ...`
   - 返回 `ok: false`
   - `index_result.stderr` 报错: `NameError: name 'Any' is not defined`
   - 根因定位: `scripts/performance.py` 使用 `Any` 但未导入。

---

## 4. 分级问题清单

## P0 - Critical

### 4.1 核心流程启动失败（`one-click` 默认不可用）

- 位置:
  - `scripts/performance.py:15`
  - `scripts/performance.py:251`
  - `scripts/novel_flow_executor.py:1241`
- 问题描述:
  - `SimpleCache` 类型注解使用 `Any`，但 `typing` 未导入该符号，触发 `NameError`。
- 影响:
  - 新项目初始化流程失败，阻断主产品价值路径。
- 建议修复:
  - 在 `performance.py` 中补充 `Any` 导入。
  - 增加 `one-click` smoke test 作为发布前门禁。

### 4.2 内容扩充模块语法错误

- 位置:
  - `scripts/content_expansion_engine.py:235`
- 问题描述:
  - f-string 内混用单双引号导致语法错误。
- 影响:
  - 模块不可导入，依赖测试与功能不可执行。
- 建议修复:
  - 修正字符串模板引号结构。
  - 在 CI 增加 `py_compile` 或 `compileall` 作为语法门禁。

## P1 - High

### 4.3 版本元数据漂移

- 位置:
  - `README.md:1`（宣称 v8.0）
  - `novel-creator.json:5`（`"version": "7.2.0"`）
- 影响:
  - 多工具安装时能力认知和行为可能不一致。
- 建议修复:
  - 建立单一版本源（例如 `VERSION` 文件），打包/发布自动注入。

### 4.4 文档断链（引用不存在文件）

- 位置:
  - `SKILL.md:49`
  - `SKILL.md:106`
- 问题描述:
  - 引用了 `references/tutorials.md`，仓库中不存在该文件。
- 影响:
  - 按技能文档执行会中断。
- 建议修复:
  - 补齐文档或改为现有文档路径。

### 4.5 安装脚本存在高破坏误操作风险

- 位置:
  - `scripts/install-portable-skill.sh:79`
- 问题描述:
  - `--force` 且 `--dest` 自定义时直接 `rm -rf "$DEST"`，缺少关键路径保护。
- 影响:
  - 用户误传路径可能删除非目标目录。
- 建议修复:
  - 增加白名单根目录校验（仅允许 `~/.codex/skills` 等预期目录）。
  - 显式禁止 `/`、`$HOME`、空路径、`.` 等危险目标。

## P2 - Medium

### 4.6 执行锁非原子，存在并发竞争窗口

- 位置:
  - `scripts/novel_flow_executor.py:70`
- 问题描述:
  - 锁逻辑先检查再写入，存在 TOCTOU。
- 影响:
  - 高并发下可能双写、重复执行。
- 建议修复:
  - 使用原子文件创建（`O_CREAT|O_EXCL`）或平台文件锁。

### 4.7 重复安全检查代码

- 位置:
  - `scripts/novel_flow_executor.py:926`
  - `scripts/novel_flow_executor.py:934`
- 问题描述:
  - 同一 `relative_to(project_root)` 检查块重复两次。
- 影响:
  - 维护成本上升，易出现修改不一致。
- 建议修复:
  - 合并为单函数 `validate_chapter_path()`。

### 4.8 门禁错误信息与测试预期不一致

- 位置:
  - `scripts/chapter_gate_check.py:81`
  - `scripts/tests/test_p01_duplicate_detection.py:308`
- 问题描述:
  - `quality_report` 为 False 时提前返回泛化消息，丢失重复度细节。
- 影响:
  - 诊断效率低，测试失败。
- 建议修复:
  - 无论总体通过与否，都输出具体失败项。

### 4.9 多处吞异常导致静默失败

- 位置示例:
  - `scripts/long_term_context_manager.py:168`
  - `scripts/long_term_context_manager.py:262`
- 问题描述:
  - `except Exception: pass/continue` 无日志。
- 影响:
  - 数据问题被隐藏，线上难排查。
- 建议修复:
  - 最低限度记录 warning（文件 + 异常信息）。

## P3 - Low

### 4.10 技能目录冗余文档（与 skill-forge 精简原则冲突）

- 位置:
  - `README.md`
- 问题描述:
  - `skill-forge` 倾向技能包最小化，不建议附加人类说明文档。
- 影响:
  - 非功能阻塞，主要是维护与一致性问题。
- 建议修复:
  - 保留必要资料到 `SKILL.md/references`，精简分发包。

---

## 5. Skill-Forge 质量审计

## 5.1 通过项

1. `SKILL.md` 体量合规（162 行，<500）。
2. Frontmatter 基本合法（`quick_validate.py` 通过）。
3. 描述字段具有中文高频触发词覆盖。
4. references 采用按需加载思路。

## 5.2 不通过项（高质量标准）

1. 缺少 Iron Law（硬约束）。
2. 缺少“可勾选 checklist + ⚠️/⛔”工作流结构。
3. 存在引用失配（`tutorials.md`）。
4. “脚本可执行”与“测试健康”状态不满足高质量要求。
5. 技能包冗余文档不符合极简打包建议。

## 5.3 质量结论

- 当前级别: “可用但未达高质量”
- 建议目标: 修复全部 P0/P1 后，再进行 skill 结构重构与二次验收。

---

## 6. 修复路线图（建议）

### 阶段 A（阻塞修复，1 天内）

1. 修复 `performance.py` 的 `Any` 导入问题。
2. 修复 `content_expansion_engine.py` 语法错误。
3. 让以下检查全部通过:
   - `python3 -m py_compile scripts/*.py`
   - `python3 scripts/test_novel_flow_executor.py`

### 阶段 B（高风险治理，1-2 天）

1. 安装脚本增加危险路径保护。
2. 统一版本号来源并同步 `README/SKILL/json`。
3. 修复文档断链。

### 阶段 C（质量提升，2-3 天）

1. 执行锁改原子化。
2. 移除重复安全检查。
3. 异常处理补充日志与上下文。
4. 门禁失败消息细化并与测试对齐。
5. `SKILL.md` 引入 Iron Law + checklist 结构。

---

## 7. 验收标准（DoD）

满足以下条件才可判定通过：

1. `one-click` 在本地默认参数返回 `ok: true`。
2. `py_compile` 全脚本通过。
3. 两组测试全部通过或有明确、可接受的跳过说明。
4. `SKILL.md` 不再引用不存在文件。
5. 安装脚本对危险路径具备硬防护。
6. 版本号在 `README/SKILL/json` 三处一致。
7. `skill-forge` 必选结构项（Iron Law、Checklist）补齐。

---

## 8. 附录：已执行命令（摘要）

```bash
git status -sb
python3 scripts/test_novel_flow_executor.py
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile scripts/*.py
python3 scripts/novel_flow_executor.py one-click --project-root /tmp/novel_audit_tmp ...
python3 /Users/ethan/.agents/skills/skill-forge/scripts/quick_validate.py .
```

---

## 9. 审计结论

当前版本不建议直接作为“稳定生产 skill”发布。  
建议先完成 P0/P1 修复，再执行一次回归审计和打包验收。
