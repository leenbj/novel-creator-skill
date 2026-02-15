#!/usr/bin/env bash
set -euo pipefail

TOOL=""
DEST=""
FORCE="0"

usage() {
  cat <<'USAGE'
用法：
  install-portable-skill.sh --tool <codex|claude-code|opencode|gemini-cli|antigravity> [--dest <目录>] [--force]

示例：
  install-portable-skill.sh --tool codex
  install-portable-skill.sh --tool claude-code --dest ~/.claude/skills/novel-creator-skill
  install-portable-skill.sh --tool gemini-cli --dest ~/.gemini/skills/novel-creator-skill --force
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tool)
      TOOL="${2:-}"
      shift 2
      ;;
    --dest)
      DEST="${2:-}"
      shift 2
      ;;
    --force)
      FORCE="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$TOOL" ]]; then
  echo "缺少 --tool 参数" >&2
  usage
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

default_dest() {
  case "$1" in
    codex) echo "$HOME/.codex/skills/novel-creator-skill" ;;
    claude-code) echo "$HOME/.claude/skills/novel-creator-skill" ;;
    opencode) echo "$HOME/.opencode/skills/novel-creator-skill" ;;
    gemini-cli) echo "$HOME/.gemini/skills/novel-creator-skill" ;;
    antigravity) echo "$HOME/.antigravity/skills/novel-creator-skill" ;;
    *)
      echo "不支持的工具: $1" >&2
      exit 2
      ;;
  esac
}

if [[ -z "$DEST" ]]; then
  DEST="$(default_dest "$TOOL")"
fi

if [[ -e "$DEST" && "$FORCE" != "1" ]]; then
  echo "目标目录已存在：$DEST" >&2
  echo "如需覆盖请追加 --force" >&2
  exit 3
fi

if [[ -e "$DEST" && "$FORCE" == "1" ]]; then
  rm -rf "$DEST"
fi

mkdir -p "$DEST"

copy_core() {
  cp "$SRC_DIR/novel-creator.md" "$DEST/"
  cp "$SRC_DIR/novel-creator.json" "$DEST/"
  cp "$SRC_DIR/novel-analyzer.md" "$DEST/"
  cp "$SRC_DIR/novel-analyzer.json" "$DEST/"
  cp "$SRC_DIR/SKILL.md" "$DEST/"
  cp -R "$SRC_DIR/templates" "$DEST/"
  cp -R "$SRC_DIR/references" "$DEST/"
  cp -R "$SRC_DIR/scripts" "$DEST/"
  cp -R "$SRC_DIR/assets" "$DEST/"
}

write_entry() {
  local tool="$1"
  case "$tool" in
    codex)
      cat > "$DEST/ENTRYPOINT.md" <<'TXT'
# Codex 入口

直接使用 `SKILL.md` 作为技能入口。
推荐命令链路：`/新手模式 开启 -> /一键开书 -> /继续写 -> /修复本章(仅失败时)`
TXT
      ;;
    claude-code)
      cat > "$DEST/CLAUDE.md" <<'TXT'
# Claude Code 入口

请将本目录作为技能目录使用，核心入口为 `SKILL.md` 与 `novel-creator.md`。
章节发布必须执行：`/更新记忆 -> /检查一致性 -> /风格校准 -> /校稿 -> /门禁检查`。
新手建议：`/新手模式 开启 -> /一键开书 -> /继续写`；失败时执行 `/修复本章`。
TXT
      ;;
    opencode)
      cat > "$DEST/OPENCODE.md" <<'TXT'
# OpenCode 入口

将本目录作为技能包加载，入口说明见 `SKILL.md`。
章节发布必须执行：`/更新记忆 -> /检查一致性 -> /风格校准 -> /校稿 -> /门禁检查`。
新手建议：`/新手模式 开启 -> /一键开书 -> /继续写`；失败时执行 `/修复本章`。
TXT
      ;;
    gemini-cli)
      cat > "$DEST/GEMINI.md" <<'TXT'
# Gemini CLI 入口

将本目录作为项目提示技能目录，入口说明见 `SKILL.md`。
章节发布必须执行：`/更新记忆 -> /检查一致性 -> /风格校准 -> /校稿 -> /门禁检查`。
新手建议：`/新手模式 开启 -> /一键开书 -> /继续写`；失败时执行 `/修复本章`。
TXT
      ;;
    antigravity)
      cat > "$DEST/ANTIGRAVITY.md" <<'TXT'
# Antigravity 入口

将本目录作为代理技能目录，入口说明见 `SKILL.md`。
章节发布必须执行：`/更新记忆 -> /检查一致性 -> /风格校准 -> /校稿 -> /门禁检查`。
新手建议：`/新手模式 开启 -> /一键开书 -> /继续写`；失败时执行 `/修复本章`。
TXT
      ;;
  esac
}

write_manifest() {
  cat > "$DEST/TOOL_COMPAT.json" <<JSON
{
  "tool": "$TOOL",
  "installed_at": "$(date '+%Y-%m-%d %H:%M:%S')",
  "entry_files": [
    "SKILL.md",
    "novel-creator.md",
    "novel-creator.json"
  ],
  "chapter_release_pipeline": [
    "/更新记忆",
    "/检查一致性",
    "/风格校准",
    "/校稿",
    "/门禁检查"
  ],
  "recommended_prewrite": [
    "/继续写（内部已包含条件触发检索）"
  ],
  "recommended_postwrite": [
    "/继续写（内部已包含门禁与索引更新）"
  ],
  "recommended_beginner_flow": [
    "/新手模式 开启",
    "/一键开书",
    "/继续写",
    "/修复本章（仅失败时）"
  ]
}
JSON
}

copy_core
write_entry "$TOOL"
write_manifest

echo "安装完成"
echo "tool=$TOOL"
echo "dest=$DEST"
