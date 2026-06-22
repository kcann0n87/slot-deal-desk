---
name: slot-ev
description: >-
  Math-only advantage-play +EV calculator for persistent-state slot machines
  (the disciplined side of slot AP). Covers ~60 machines. Use whenever the user
  asks "is X +EV", "should I play X at <meter>", names a slot game with a meter
  value, says "deal desk", "advantage play", "must-hit-by", "break-even meter",
  or asks for EV / verdict / break-even on a slot. Returns PLAY / THIN / PASS,
  EV per session in dollars, the break-even meter, and worst-case downside.
---

# Slot Deal Desk — +EV engine

A deterministic engine that decides whether a persistent-state slot is worth
playing right now, given the machine and its current meter.

## Golden rule

**ALWAYS run the script for the math. Never recompute EV, break-even, or the
verdict by hand** — the numbers are subtle and the script is the source of truth.

```bash
python3 ~/.claude/skills/slot-ev/slot_ev.py <game> <meter> [bet]
```

Examples:
- `python3 ~/.claude/skills/slot-ev/slot_ev.py buffalo 1620 5`
- `python3 ~/.claude/skills/slot-ev/slot_ev.py scarab 60 5`
- `python3 ~/.claude/skills/slot-ev/slot_ev.py list ocean`
- Add `--sweep` to see EV across the whole reset→ceiling band.
- Add `--log` to append the evaluation to `~/.claude/state/slot-ev/log.ndjson`.

`<game>` is a fuzzy match on id or name (`buffalo`, `phoenix`, `ocean`). For
**dollar** games `<meter>` is the current jackpot in $, for **banking** games it
is the credit value you can collect off the abandoned machine.

## How to answer

1. Run the script with the user's game, meter, and bet (default bet $5).
2. Report the verdict, EV/session, break-even, and worst-case loss as given.
3. **Keep the calibration warning.** If the script prints the `! VERIFY` banner,
   pass it on — only **Buffalo Link** is fully calibrated. For every other game
   the reset & ceiling are reliable but accrual & feature payout are estimates,
   so the break-even is a placeholder until the user dials in real floor numbers.
4. If the game is a trap or not-beatable, say so and explain why — don't fish for
   a number that isn't there.

## The math (validated vs Wizard of Odds + apcalculators)

Counter must-hit-by:

```
EV = U*bet − ((ceiling − meter) / (div*accrual)) * bet * (1 − baseRTP)
div = 2 for random must-hit-by, 1 for deterministic count-to-trigger
break-even meter = ceiling − (div*accrual*U) / (1 − baseRTP)   [bet-independent]
```

Dollar-MHB and banking engines live in `slot_ev.py` as well. Verdict: **PLAY**
if EV>0 and edge≥2%, **THIN** if EV>0, else **PASS**.

## Calibration status (carry this honesty everywhere)

- **Buffalo Link only** is calibrated: reset 100, ceiling 1800, ~1.7 heads/spin,
  ~85% base return, 20-unit feature (range 20–30). Neutral break-even ≈ 1347
  (20-unit) or ≈ 1233 (25-unit, aggressive).
- Every other game: reset & ceiling RELIABLE; accrual & feature payout are
  ESTIMATES. Their computed break-evens aren't trustworthy yet. To calibrate a
  game from the floor you need two real numbers: **accrual** = trigger-symbols
  collected per spin, and **average feature payout** (in × bet). Edit that
  game's `accr` and `units` in `slot_ev.py` and re-run.

## Reality check (say this when it matters)

+EV is a long-run average; individual sessions swing hard and the feature often
pays near zero. Needs a bankroll that absorbs variance, and good states get
locked up fast by other players. The discipline is playing *only* +EV states —
if a session drifts into "playing because I'm here," that's the stop-loss. For
informational use; verify every constant against the real machine.
