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
    codex) echo "$HOME/.codex/skills/novel-claude-ai" ;;
    claude-code) echo "$HOME/.claude/skills/novel-claude-ai" ;;
    opencode) echo "$HOME/.opencode/skills/novel-claude-ai" ;;
    gemini-cli) echo "$HOME/.gemini/skills/novel-claude-ai" ;;
    antigravity) echo "$HOME/.antigravity/skills/novel-claude-ai" ;;
    *)
      echo "不支持的工具: $1" >&2
      exit 2
      ;;
  esac
}

is_protected_dest() {
  local raw="$1"
  local trimmed="${raw%/}"

  # 禁止危险目标：空路径、根目录、HOME、当前目录
  if [[ -z "$trimmed" || "$trimmed" == "/" || "$trimmed" == "$HOME" || "$trimmed" == "." ]]; then
    return 0
  fi

  # 若路径已存在，检查规范化后的真实路径
  if [[ -e "$raw" ]]; then
    local resolved=""
    resolved="$(cd "$raw" 2>/dev/null && pwd -P || true)"
    if [[ -z "$resolved" || "$resolved" == "/" || "$resolved" == "$HOME" ]]; then
      return 0
    fi
  fi

  return 1
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
  if is_protected_dest "$DEST"; then
    echo "拒绝删除危险路径: $DEST" >&2
    exit 4
  fi
  rm -rf "$DEST"
fi

mkdir -p "$DEST"

copy_core() {
  cp "$SRC_DIR/novel-creator.md" "$DEST/"
  cp "$SRC_DIR/novel-creator.json" "$DEST/"
  cp "$SRC_DIR/SKILL.md" "$DEST/"
  cp -R "$SRC_DIR/templates" "$DEST/"
  cp -R "$SRC_DIR/references" "$DEST/"
  cp -R "$SRC_DIR/scripts" "$DEST/"
  # 可选目录，存在时才复制
  [[ -d "$SRC_DIR/assets" ]] && cp -R "$SRC_DIR/assets" "$DEST/" || true
}

# Claude Code 专属：安装 Agent 定义文件到 ~/.claude/agents/
install_claude_agents() {
  local agents_src="$SRC_DIR/.claude/agents"
  if [[ ! -d "$agents_src" ]]; then
    return 0
  fi

  local agents_dest="$HOME/.claude/agents"
  mkdir -p "$agents_dest"

  local installed=0
  for agent_file in "$agents_src"/*.md; do
    [[ -f "$agent_file" ]] || continue
    local agent_name
    agent_name="$(basename "$agent_file")"
    local target="$agents_dest/$agent_name"

    if [[ -f "$target" && "$FORCE" != "1" ]]; then
      echo "[agents] 跳过（已存在，使用 --force 覆盖）：$target"
    else
      cp "$agent_file" "$target"
      echo "[agents] 已安装：$target"
      installed=$((installed + 1))
    fi
  done

  if [[ $installed -gt 0 ]]; then
    echo "[agents] 共安装 $installed 个编辑团队 Agent 到 $agents_dest"
  fi
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

# Claude Code 额外安装 Agent 文件
if [[ "$TOOL" == "claude-code" ]]; then
  install_claude_agents
fi

echo "安装完成"
echo "tool=$TOOL"
echo "dest=$DEST"
