# 跨工具安装教程

本技能支持以下工具的一键安装：
- Codex
- Claude Code
- OpenCode
- Gemini CLI
- Antigravity

统一安装脚本：`scripts/install-portable-skill.sh`

## 1. Codex
```bash
bash scripts/install-portable-skill.sh --tool codex --force
```
默认安装到：`~/.codex/skills/novel-creator-skill`

## 2. Claude Code
```bash
bash scripts/install-portable-skill.sh --tool claude-code --force
```
默认安装到：`~/.claude/skills/novel-creator-skill`

## 3. OpenCode
```bash
bash scripts/install-portable-skill.sh --tool opencode --force
```
默认安装到：`~/.opencode/skills/novel-creator-skill`

## 4. Gemini CLI
```bash
bash scripts/install-portable-skill.sh --tool gemini-cli --force
```
默认安装到：`~/.gemini/skills/novel-creator-skill`

## 5. Antigravity
```bash
bash scripts/install-portable-skill.sh --tool antigravity --force
```
默认安装到：`~/.antigravity/skills/novel-creator-skill`

## 自定义目录
```bash
bash scripts/install-portable-skill.sh --tool <tool> --dest <目标目录> --force
```

## 安装后检查
确认以下文件存在：
- `SKILL.md`
- `novel-creator.md`
- `novel-creator.json`
- 对应工具入口文件（如 `CLAUDE.md` / `GEMINI.md` / `OPENCODE.md` / `ANTIGRAVITY.md`）
- `TOOL_COMPAT.json`
