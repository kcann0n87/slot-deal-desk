#!/usr/bin/env bash
# Install the Slot Deal Desk skill + /ev command into your local Claude Code.
#   ~/.claude/skills/slot-ev/{slot_ev.py,SKILL.md}
#   ~/.claude/commands/ev.md
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/slot-ev"
SKILL_DIR="${HOME}/.claude/skills/slot-ev"
CMD_DIR="${HOME}/.claude/commands"

mkdir -p "$SKILL_DIR" "$CMD_DIR"
cp "$SRC/slot_ev.py" "$SKILL_DIR/slot_ev.py"
cp "$SRC/SKILL.md"   "$SKILL_DIR/SKILL.md"
cp "$SRC/commands/ev.md" "$CMD_DIR/ev.md"
chmod +x "$SKILL_DIR/slot_ev.py"

echo "Installed:"
echo "  $SKILL_DIR/slot_ev.py"
echo "  $SKILL_DIR/SKILL.md"
echo "  $CMD_DIR/ev.md"
echo
echo "Smoke test:"
python3 "$SKILL_DIR/slot_ev.py" buffalo 1620 5
