# Slot Deal Desk

A disciplined, **math-only** +EV calculator for persistent-state slot machines —
the advantage-play side that is actual arithmetic, not superstition. Give it a
machine and its current meter and it returns **PLAY / THIN / PASS**, the EV per
session in dollars, the **break-even meter**, and the worst-case downside.
Covers ~60 machines.

Two front ends, one engine:

| Front end | File | Use |
|-----------|------|-----|
| Mobile web tool | [`index.html`](index.html) | Phone-friendly; hosted on GitHub Pages |
| Claude Code skill + `/ev` command | [`slot-ev/`](slot-ev/) | `python3 slot_ev.py buffalo 1620 5` |

The Python engine in `slot-ev/slot_ev.py` is a faithful port of the JS engine in
`index.html`; **keep the two in sync** when the math or the machine DB changes.

## The math

Validated against Wizard of Odds and apcalculators. Counter must-hit-by:

```
EV = U*bet − ((ceiling − meter) / (div*accrual)) * bet * (1 − baseRTP)
div = 2 for random must-hit-by, 1 for deterministic count-to-trigger
break-even meter = ceiling − (div*accrual*U) / (1 − baseRTP)   [bet-independent]
```

Dollar must-hit-by and banking/vulture engines are in the same file. Verdict:
**PLAY** if EV>0 and edge ≥ 2%, **THIN** if EV>0, else **PASS**.

## Calibration honesty

Only **Buffalo Link** is fully calibrated (reset 100, ceiling 1800, ~1.7
heads/spin, ~85% base return, 20-unit feature → neutral break-even ≈ 1347). For
every other game the **reset and ceiling are reliable**, but **accrual and
feature payout are estimates** — so their break-evens are placeholders until you
dial in real floor data. Both front ends flag those games with a verify warning.
Keep it.

To calibrate the next game you need two numbers off the floor: **accrual** =
trigger-symbols collected per spin, and **average feature payout** (in × bet).
Put them in that game's `accr` and `units` (in both `slot_ev.py` and the `GAMES`
array in `index.html`) and its break-even becomes a real number.

## Use it on your phone (GitHub Pages)

`index.html` is already at the repo root. To publish:

1. Repo → **Settings** → **Pages**.
2. **Build and deployment → Source: Deploy from a branch.**
3. Branch: **`main`**, folder: **`/ (root)`** → **Save**.
4. After ~1 minute it is live at **https://kcann0n87.github.io/slot-deal-desk/**.

On the phone, open that URL → **Share → Add to Home Screen**. The manifest +
meta tags make it launch full-screen like a native app. (The PWA polish lives on
this branch — merge it to `main` first if you want the themed install icon.)

## Use it in Claude Code (skill + `/ev`)

From the repo root:

```bash
./install.sh
```

This copies the skill to `~/.claude/skills/slot-ev/` and the `/ev` command to
`~/.claude/commands/ev.md`. Then in Claude Code:

- Ask naturally: *"is Buffalo at 1620 +EV at $5?"*
- Or run the command: `/ev buffalo 1620 5`
- Or shell out directly:

```bash
python3 ~/.claude/skills/slot-ev/slot_ev.py buffalo 1620 5
python3 ~/.claude/skills/slot-ev/slot_ev.py buffalo 1800 5 --sweep
python3 ~/.claude/skills/slot-ev/slot_ev.py list ocean
```

`--sweep` shows EV across the whole reset→ceiling band; `--log` appends each
evaluation to `~/.claude/state/slot-ev/log.ndjson` to build your own dataset.

## Reality check

+EV is a long-run average; sessions swing hard and the feature often pays near
zero. You need a bankroll that absorbs the variance, the good states get locked
up fast, and the discipline is playing **only** +EV states. If a session drifts
into "playing because I'm here," that's the stop-loss — walk. For informational
use; verify every constant against the real machine.
