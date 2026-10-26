#!/usr/bin/env bash
set -euo pipefail

# ~/.agents/skills is the one global source. Claude gets a real ~/.claude/skills with one
# symlink per skill, so what Claude Code writes there (claude.ai's synced/ skills) stays
# Claude-only instead of leaking into Codex and Antigravity through the shared source.
SOURCE="$HOME/.agents/skills"
CLAUDE_DIR="$HOME/.claude/skills"
GEMINI_CONFIG="$HOME/.gemini/config/skills.json"

[ -d "$SOURCE" ] || { echo "Missing global skill source: $SOURCE" >&2; exit 1; }
[ -L "$CLAUDE_DIR" ] && { echo "$CLAUDE_DIR is still a symlink; make it a directory first" >&2; exit 1; }
[ -e "$SOURCE/synced" ] && { echo "$SOURCE/synced belongs in $CLAUDE_DIR/synced (Claude-only)" >&2; exit 1; }
mkdir -p "$CLAUDE_DIR"

for skill in "$SOURCE"/*/; do
  name="$(basename "$skill")"
  link="$CLAUDE_DIR/$name"
  if [ -L "$link" ]; then
    [ "$(readlink "$link")" = "$SOURCE/$name" ] || ln -sfn "$SOURCE/$name" "$link"
  elif [ -e "$link" ]; then
    echo "Claude: $link is a real directory, not linking over it" >&2
  else
    ln -s "$SOURCE/$name" "$link"
  fi
done

# Drop links to global skills that no longer exist; leave Claude's own dirs alone.
for link in "$CLAUDE_DIR"/*; do
  [ -L "$link" ] || continue
  case "$(readlink "$link")" in "$SOURCE"/*) [ -e "$link" ] || rm "$link" ;; esac
done

mkdir -p "$(dirname "$GEMINI_CONFIG")"
printf '{\n  "entries": [{"path": "%s"}]\n}\n' "$SOURCE" > "$GEMINI_CONFIG"

echo "Codex: reads $SOURCE ($(find "$SOURCE" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ') skills)"
echo "Claude: $CLAUDE_DIR links $(find "$CLAUDE_DIR" -mindepth 1 -maxdepth 1 -type l | wc -l | tr -d ' ') global skills; own: $(find "$CLAUDE_DIR" -mindepth 1 -maxdepth 1 -type d | xargs -n1 basename 2>/dev/null | tr '\n' ' ')"
echo "Antigravity: registered $SOURCE"
