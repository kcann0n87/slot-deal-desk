---
description: +EV verdict for a persistent-state slot — PLAY/THIN/PASS, EV, break-even
argument-hint: <game> <meter> [bet] [--sweep] [--log]
allowed-tools: Bash(python3 ~/.claude/skills/slot-ev/slot_ev.py:*)
---

Run the Slot Deal Desk engine and report the result verbatim — do not recompute
the math by hand.

```bash
python3 ~/.claude/skills/slot-ev/slot_ev.py $ARGUMENTS
```

Then, in one or two lines: give the verdict (PLAY / THIN / PASS), the EV per
session, the break-even meter, and the worst-case loss. If the output includes
the `! VERIFY` banner, keep it — only Buffalo Link is fully calibrated; for every
other game the accrual and feature payout are estimates, so the break-even is a
placeholder until real floor numbers are dialed in.

If no arguments were given, show usage: `python3 ~/.claude/skills/slot-ev/slot_ev.py --help`
