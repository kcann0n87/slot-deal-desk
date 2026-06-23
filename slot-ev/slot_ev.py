#!/usr/bin/env python3
"""Slot Deal Desk — deterministic +EV engine for persistent-state slots.

Math-only advantage play. Given a machine and its current meter, returns
PLAY / THIN / PASS, EV per session in dollars, the break-even meter, and
worst-case downside. Python stdlib only, no dependencies.

This is the reference Python port of the engine embedded in index.html.
The two MUST stay in sync.

Counter must-hit-by (MHB):
    EV = U*bet - ((ceil - meter)/(div*accrual)) * bet * (1 - baseRTP)
    div = 2 for random must-hit-by, 1 for deterministic count-to-trigger
    break-even meter = ceil - (div*accrual*U)/(1 - baseRTP)   [bet-independent]

CALIBRATION HONESTY: only Buffalo Link is fully calibrated. For every other
game the reset & ceiling are reliable, but accrual & feature payout are
ESTIMATES, so their computed break-evens are not trustworthy yet. Replies for
those games carry a "verify constants" warning — keep it.

Usage:
    slot_ev.py <game> <meter> [bet]      e.g.  slot_ev.py buffalo 1620 5
    slot_ev.py <game> <meter> [bet] --sweep
    slot_ev.py <game> <meter> [bet] --log
    slot_ev.py list [filter]
    slot_ev.py --help
"""
import json
import math
import os
import sys
import time

# ----------------------------------------------------------------------------
# Machine database  (faithful port of GAMES in index.html)
#   counter : reset, ceil, accr, units, rtp, trig ('mhb' | 'fixed')
#   dollar  : dcur, dceil, dinc (% of coin-in), rtp
#   bank    : bspins, rtp
#   trap / notbeatable : no calc
# ----------------------------------------------------------------------------

def _bank(id, name, maker, key, note):
    return dict(id=id, name=name, maker=maker, type="bank",
                grp="Banking / vulture state", bspins=3, rtp=88, key=key, note=note)

def _trap(id, name, note):
    return dict(id=id, name=name, maker=None, type="trap",
                grp="Volatile / AP trap",
                key="random trigger - no guaranteed hit", note=note)

def _myth(id, name, note):
    return dict(id=id, name=name, maker=None, type="notbeatable",
                grp="Not advantage-playable", key="no trackable MHB", note=note)

GAMES = [
    # ===== CALIBRATED =====
    dict(id="buffalo-link", name="Buffalo Link / Lightning Buffalo Link",
         maker="Aristocrat", type="counter", grp="* Calibrated",
         reset=100, ceil=1800, accr=1.7, units=20, rtp=85, trig="mhb", verified=True,
         key="reset 100 - MHB 1800 - ~1.7/spin",
         note="The one fully-calibrated game. Head counter resets to 100, feature "
              "must hit by 1800, heads accrue ~1.7/spin, feature averages 20-30x bet. "
              "Break-even lands ~1,230 (aggressive, 25-unit) to ~1,347 (neutral, "
              "20-unit). The 'play over 1200' rule only holds at the highest bet / "
              "25-unit assumption - below ~1,300 you are usually paying the house. "
              "Higher bet = higher RTP = slightly lower threshold."),

    # ===== COUNTER / MUST-HIT-BY =====
    dict(id="phoenix-link", name="Phoenix Link", maker="Aristocrat", type="counter",
         grp="Counter / must-hit-by",
         reset=100, ceil=1888, accr=1.7, units=20, rtp=88, trig="mhb",
         key="reset random 100-1500 - MHB 1888",
         note="Phoenix counter resets to a RANDOM value between 100 and 1500, must "
              "hit by 1888. Because resets can be high, the playable window near 1888 "
              "is narrow and rarely found. Accrual & feature values are estimates - verify."),
    dict(id="regal-link", name="Regal Link: Lion / Raven", maker=None, type="counter",
         grp="Counter / must-hit-by",
         reset=175, ceil=200, accr=1, units=15, rtp=88, trig="mhb",
         key="5 tiers, e.g. diamond 175->200",
         note="Five accruing free-games wild tiers (MHB): amber 30->50, sapphire "
              "40->60, amethyst 50->75, emerald 75->100, diamond 175->200. Preset "
              "shows the tightest (diamond) tier - change reset/ceiling to whichever "
              "tier you are tracking. Accrual/feature are estimates."),
    dict(id="rocket-rumble", name="Rocket Rumble", maker=None, type="counter",
         grp="Counter / must-hit-by",
         reset=50, ceil=100, accr=1, units=12, rtp=88, trig="mhb",
         key="tiers 8->15, 10->20, 20->35, 50->100",
         note="Four MHB free-games meters: blue 8->15, green 10->20, purple 20->35, "
              "red 50->100. Preset = red tier. Swap reset/ceiling per tier. "
              "Accrual/feature estimated."),
    dict(id="stack-up", name="Stack Up Pays / Ascending Fortunes", maker=None,
         type="counter", grp="Counter / must-hit-by",
         reset=250, ceil=350, accr=1, units=15, rtp=88, trig="mhb",
         key="5 tiers, mega 250->350 ... mini 75->125",
         note="Five MHB meters that add reel expansions: mini 75->125, minor "
              "100->150, major 150->200, grand 200->250, mega 250->350. Preset = "
              "mega. Accrual/feature estimated."),
    dict(id="regal-riches", name="Regal Riches / Prosperity Pearl", maker="IGT",
         type="counter", grp="Counter / must-hit-by",
         reset=5, ceil=50, accr=0.4, units=8, rtp=88, trig="mhb",
         key="blue wilds 5->50 - FG 75/100/125",
         note="Blue-wild counter (base game) resets to 5; the bank of wilds triggers "
              "RANDOMLY - usually around 8-12 collected, roughly every 20 spins - and "
              "is guaranteed by 50 (rare above 12; highest seen ~22). So the real read "
              "is simple: PLAY AT 8+, higher is better. The climb-to-50 break-even "
              "below is just the hard backstop; this game pays off well before that "
              "because it fires randomly. Free-games tiers are separate MHB meters "
              "(purple 75, green 100, yellow 125). a.k.a. Prosperity Pearl."),
    dict(id="golden-beasts", name="Golden Beasts / Golden Elements", maker=None,
         type="counter", grp="Counter / must-hit-by",
         reset=0, ceil=180, accr=1, units=14, rtp=88, trig="mhb",
         key="super-spin MHB by 180",
         note="Super-spin feature must hit by 180 collected symbols. "
              "Accrual/feature estimated."),
    dict(id="jewel-collection", name="Jewel Collection: Dragon / Vault", maker=None,
         type="counter", grp="Counter / must-hit-by",
         reset=0, ceil=777, accr=1, units=18, rtp=88, trig="mhb",
         key="scatter meter MHB by 777",
         note="Mystery free-games scatter meter guaranteed by 777. Wild meters "
              "(amethyst/sapphire/emerald/ruby) are NOT must-hit-bys. "
              "Accrual/feature estimated."),
    dict(id="treasure-shot", name="Treasure Shot: Pirate Ship / Robin Hood",
         maker=None, type="counter", grp="Counter / must-hit-by",
         reset=0, ceil=100, accr=1, units=12, rtp=88, trig="mhb",
         key="FG MHB blue 100 - green/purple 75 - bags hit by 10",
         note="Free-games chest wilds are MHB: blue 100, green 75, purple 75. Bag "
              "wilds guaranteed once 10 collected. Preset = blue chest. "
              "Accrual/feature estimated."),

    # ===== COUNT TO TRIGGER (deterministic) =====
    dict(id="diamond-collector", name="Diamond Collector: Wolfpack / Elite 7s",
         maker=None, type="counter", grp="Count to trigger",
         reset=0, ceil=15, accr=0.6, units=10, rtp=88, trig="fixed",
         key="free spins at 15 diamonds",
         note="Free spins trigger once 15 diamonds collected - deterministic, so "
              "play when most are already banked. Accrual/feature estimated."),
    dict(id="hyper-orbs", name="Hyper Orbs: King of the Seas / Dragon Sense",
         maker=None, type="counter", grp="Count to trigger",
         reset=0, ceil=15, accr=0.6, units=10, rtp=88, trig="fixed",
         key="free spins at 15 orbs",
         note="Bonus at 15 orbs collected. Same logic as Diamond Collector. "
              "Accrual/feature estimated."),
    dict(id="lunar-disc", name="Lunar Disc / Fortune Disc", maker="Konami",
         type="counter", grp="Count to trigger",
         reset=0, ceil=6, accr=0.4, units=6, rtp=88, trig="fixed",
         key="wild feature at 6 discs",
         note="Six discs collected -> turns a random symbol fully wild. Short cycle. "
              "Accrual/feature estimated."),
    dict(id="dragon-unleashed", name="Dragon Unleashed", maker=None, type="counter",
         grp="Count to trigger",
         reset=0, ceil=6, accr=0.5, units=8, rtp=88, trig="fixed",
         key="hold & spin at 6 orbs",
         note="Six orbs (they shift down each spin) trigger hold & spin. Position of "
              "orbs matters too. Accrual/feature estimated."),
    dict(id="power-push", name="Power Push: Jin Gou / Long De Xiyue", maker=None,
         type="counter", grp="Count to trigger",
         reset=0, ceil=300, accr=2, units=20, rtp=88, trig="mhb",
         key="guaranteed push by 300 coins (12x25)",
         note="Push bonus guaranteed after 12 full stacks (300 coins). "
              "Accrual/feature estimated."),
    dict(id="treasure-hunter", name="Treasure Hunter", maker="IGT", type="counter",
         grp="Count to trigger",
         reset=0, ceil=3, accr=0.2, units=25, rtp=88, trig="fixed",
         key="jackpot at 3 pearls (per tier)",
         note="Three pearls under a jackpot (mini/minor/maxi/major) awards it. Play "
              "when a jackpot sits at 2 pearls. Accrual/feature estimated."),
    dict(id="golden-jungle", name="Golden Jungle Grand", maker=None, type="counter",
         grp="Count to trigger",
         reset=0, ceil=10, accr=1, units=8, rtp=88, trig="fixed",
         key="10-spin cycle, 2 buddhas -> wild reel",
         note="Ten-game cycle; reels holding two buddhas turn wild after spin 10. "
              "Value depends on buddhas already banked late in the cycle. Treat as a "
              "cycle play. Accrual/feature estimated."),
    dict(id="lucky-coin-link", name="Lucky Coin Link: Asian Dreaming / Atlantica",
         maker=None, type="counter", grp="Count to trigger",
         reset=0, ceil=5, accr=0.4, units=7, rtp=88, trig="fixed",
         key="respin at 5 coin holders filled",
         note="Respin when all 5 holders fill. Highest bet resets with 3 already "
              "filled, so check higher bets. Accrual/feature estimated."),
    dict(id="piggy-bankin", name="Piggy Bankin' (classic 3-reel)", maker="WMS",
         type="counter", grp="Count to trigger",
         reset=0, ceil=510, accr=3, units=18, rtp=90, trig="fixed",
         key="bonus guaranteed by 510 coins / 9 pigs",
         note="The genuine Piggy Bankin' advantage play (the old WMS 3-reel cabinet). "
              "510 coins sit across 9 piggy banks with one random lucky coin; 3x wilds "
              "deposit coins and the progressive is GUARANTEED before the coins "
              "deplete, so it is a count-to-trigger. You read PIGS REMAINING (9 -> 0); "
              "each pig is ~57 coins, so coins collected ~ (9 - pigs)*57. Heuristic: "
              "past halfway is worth a look, 3 pigs or fewer = sit down. Accrual "
              "(coins/spin) and progressive payout are estimates - verify."),

    # ===== DOLLAR MUST-HIT-BY =====
    dict(id="river-dragons", name="River Dragons / Fire Wolf 2 / Wolf Queen",
         maker="AGS", type="dollar", grp="Dollar must-hit-by",
         dcur=300, dceil=500, dinc=1.0, rtp=90,
         key="MHB jackpots $500 and $5,000",
         note="Two dollar MHB jackpots: $500 and $5,000 ceilings. The $500 is the "
              "practical play. You need the meter increment rate (meter $ per $ "
              "coin-in) - it is hidden, so the % is an estimate. Rule of thumb "
              "without it: play only in the top ~10-15% of the reset->ceiling band."),
    dict(id="igt-classic",
         name="IGT Classic Hits: Coyote Moon / Money Storm / Lobstermania Dlx",
         maker="IGT", type="dollar", grp="Dollar must-hit-by",
         dcur=0, dceil=0, dinc=1.0, rtp=90,
         key="3 MHB progressives x 5 bet levels",
         note="Each title has top/middle/bottom MHB progressives across 5 bet levels "
              "(15 total). Read the posted reset & ceiling for the specific bet "
              "level, enter both, and supply the increment rate. All values here are "
              "placeholders."),
    dict(id="g-plus", name="G+ Deluxe style two-tier MHB", maker=None, type="dollar",
         grp="Dollar must-hit-by",
         dcur=35, dceil=50, dinc=0.6, rtp=90,
         key="e.g. $25->$50 and $50->$500",
         note="Classic two-tier MHB layout (one jackpot ~$25 must-hit-by $50, another "
              "~$50 must-hit-by $500). Penny-slow meters. Increment is an estimate - "
              "confirm before trusting EV."),
    dict(id="ainsworth-mhb",
         name="Ainsworth Must-Hit-By (Mustang Money / King Carlos / Cash Odyssey)",
         maker="Ainsworth", type="dollar", grp="Dollar must-hit-by",
         dcur=400, dceil=500, dinc=1.0, rtp=90,
         key="coin-in MHB progressives, multiple tiers",
         note="Ainsworth's mystery progressives are genuine must-hit-bys: a fixed % "
              "of coin-in feeds the meter and the jackpot is forced before a posted "
              "ceiling. Read the reset & ceiling off the belly glass and enter both. "
              "Two cautions: the meter moves SLOWLY on low denominations (a $200 "
              "must-hit on a 25c game can still be deeply -EV from far away - people "
              "have buried $30k chasing a $10k that sat at $9,900), and the increment "
              "% is hidden, so the default is an estimate. Without it, play only the "
              "top ~10-15% of the reset->ceiling band."),

    # ===== BANKING / VULTURE STATE =====
    dict(id="ocean-magic", name="Ocean Magic / Ocean Magic Grand", maker="IGT",
         type="bank", grp="Banking / vulture state", bspins=3, rtp=96, cal="sourced",
         key="wild bubbles rise 1 row/spin",
         note="The most widely hustled banking play (IGT, ~96% base return). Wild "
              "bubbles rise one row per spin and vanish at the top; the play is "
              "sitting where the prior player left bubbles still low on the screen, "
              "about to rise into coin symbols (a bubble landing on an Ocean Magic "
              "symbol expands to every adjacent spot). It pays LEFT-TO-RIGHT, so "
              "bubbles stranded in column 5 are near-worthless - ignore them. Estimate "
              "the credits the near-hit bubbles are worth and the spins to cash them. "
              "(Grand uses giant bubbles; the 'bubble boost' bet adds bubbles via a "
              "horn.) Sourced mechanic + RTP; the board value is still what you read."),
    _bank("big-ocean", "Big Ocean Jackpots", None, "jackpot/wild bubbles rise 1/spin",
          "Like Ocean Magic but with jackpot bubbles. Rich state = a jackpot or wild "
          "bubble one or two rows below a coin symbol. Value the imminent hit vs "
          "spins to reach it."),
    _bank("pillars", "Pillars of Cash: Celestial / Festive Fortune", None,
          "tall pillars + gold dragon",
          "Each reel pillar holds a credit prize and a 3-spin life. A tall pillar "
          "(gold dragon lit) about to be awarded is the play; a low pillar resets and "
          "is worthless. Collect = prize on the pillar; cost = spins to land the coin."),
    _bank("aztec-vault", "Aztec Vault / Cleopatra's Vault", None,
          "near-full coin columns",
          "Columns above the reels fill with coin prizes; a full column pays out then "
          "clears the whole board. A nearly-full high-value column left behind is the play."),
    _bank("sumo-kitty", "Sumo Kitty / Lucha Kitty", None, "connected gold frames",
          "Gold frames lock in place; a coin landing in a frame pays the total of all "
          "connected frames. A big connected cluster of frames left on the board is "
          "the play - collect within a spin or two before they clear."),
    _bank("block-bonanza", "Block Bonanza: Hawaii / Rio", None,
          "high block credit values",
          "Credit blocks sit above each reel and pay when dollar symbols line up "
          "below. Play when the block values are far above typical. Value = blocks "
          "you can realistically collect."),
    _bank("prize-pool", "Prize Pool: Cactus Cash / Fierce Dragon", None,
          "high block credit values",
          "Same idea as Block Bonanza - colored blocks pay when 4+ scatters land. "
          "Rich = unusually high block values."),
    _bank("crackin-cash", "Crackin' Cash", None,
          "high balloons near top + jackpot balloons",
          "Balloons float up each spin; rockets award them. Play when high-value or "
          "jackpot balloons sit near the top, about to be awarded or pushed off."),
    _bank("temple-falls", "Temple Falls", None, "rich coin grid (red 12.5x+)",
          "5x7 coin grid drains over coin-collect features and ALL coins eventually "
          "pay. A grid loaded with red (12.5x+) coins or a wheel coin is the play. "
          "Value the grid total vs spins to drain it."),
    _bank("wof4d-ce", "Wheel of Fortune 4D Collector's Edition", None,
          "high prize above a reel",
          "Each reel grows a credit prize; a Collect symbol awards it. A reel with a "
          "large built-up prize left behind is the play."),
    _bank("dragon-crosslink", "Dragon Spin CrossLink: Air/Earth/Fire/Water", None,
          "full gold bags",
          "Five bags fill with gold; fuller bags add bigger credit prizes when Dragon "
          "Spin triggers. Play when bags are well-filled (the trigger itself is "
          "random, so weigh volatility)."),
    _bank("cash-falls", "Cash Falls: Huo Zhu / Pirate's Trove / Island Bounty", None,
          "coins on reels w/ 3-spin counter",
          "Coins land with a 3-spin counter; fill a reel before it expires to win all "
          "its coins. A reel mostly filled with coins and fresh spins left is the play."),
    _bank("uflcf", "Ultimate Fire Link Cash Falls: China / Olvera Street", None,
          "fireballs on reels w/ 3-spin counter",
          "Same coin-counter mechanic as Cash Falls, plus a Fire Link trigger "
          "fireball. Mostly-filled reel with spins remaining (especially holding the "
          "trigger fireball) is the play."),
    _bank("wof4d", "Wheel of Fortune 4D", None, "1 of 2 dollar symbols collected",
          "Two dollar symbols fill a holder and turn a reel wild for 2 spins. A reel "
          "sitting at 1 of 2 left behind is a small, cheap edge."),
    _bank("golden-egypt", "Golden Egypt Grand", None, "coin holder near full",
          "Fill a coin holder -> that reel goes wild for 2-4 spins. A nearly-full "
          "holder is the play."),
    _bank("red-silk", "Red Silk / Aztec Chief", None, "1 of 2 coins collected",
          "Two coins fill a holder -> reel wild for 2 spins. Reel at 1 of 2 left "
          "behind = cheap edge."),
    _bank("joe-blow", "Joe Blow Diamonds / Gold", None, "2 of 3 dynamite collected",
          "Three dynamite sticks -> reel wild for 3 spins. A reel at 2 of 3 (or "
          "several reels loaded) left behind is the play."),
    _bank("lucky-empress", "Lucky Empress / Inca Empress", None,
          "high multipliers queued",
          "Multipliers (up to 12x) queue on the left of each row and apply to the "
          "next line hit. A row with a high multiplier already active / queued is the play."),
    _bank("grand-buddha", "Grand Buddha Link / Grand Cat Link", None,
          "persistent 5x/6x/8x multipliers active",
          "Line-hit symbols become multipliers (up to 8x) that persist 8 spins. "
          "Sitting down with strong left-side multipliers still live is the edge."),
    _bank("frankenstein", "Frankenstein", "IGT", "high multipliers on jackpot prizes",
          "Power-Up symbols add multipliers to the prizes above; It's Alive awards "
          "them. Play when big multipliers sit on the larger prizes. Multipliers "
          "reset after the feature."),
    _bank("diamonds-devils", "Diamonds & Devils Dlx / Jade Monkey Dlx", None,
          "2-of-3 diamonds + built prizes (removal risk)",
          "Prizes build above reels; 3 diamonds award them - BUT a devil/jade symbol "
          "removes a diamond and can reset the reel. High built value + 2 diamonds is "
          "the play, with reset risk priced in."),
    _bank("magic-nile", "Magic of the Nile", None, "obelisk at 2 of 3 segments",
          "Three obelisks each need 3 segments to trigger a bonus. An obelisk at 2 of "
          "3 left behind is the play."),
    dict(id="scarab", name="Scarab (IGT)", maker="IGT", type="bank",
         grp="Banking / vulture state", bspins=3, rtp=96, cal="sourced",
         key="10-spin cycle, wilds lock & pay on spin 10",
         note="The model advantage play (IGT, ~96% base return). A fixed 10-spin "
              "cycle: every scarab that lands gets a gold border and locks, and on "
              "spin 10 all gold-bordered positions turn WILD and pay. It pays "
              "left-to-right, so locked scarabs on the LEFT reels are worth most. The "
              "play: sit at a machine someone abandoned with lots of gold borders and "
              "few spins remaining (the counter shows X of 10) - you know the exact "
              "cost up front (remaining spins x bet) and the high base return makes the "
              "bleed tiny. Enter the credit value you expect the spin-10 wilds to pay "
              "and the spins left in the cycle. Sourced from published AP analysis; the "
              "per-position value still depends on the board you actually find."),
    _bank("ultra-rush",
          "Ultra Rush Gold: African Adventure / Mythical Phoenix / Tiger Run", None,
          "scatters near 6 (3-spin lock)",
          "Six locked scatters trigger the bonus; each new scatter resets a 3-spin "
          "lock. Several scatters already locked with spins remaining is the play."),
    _bank("cash-cano", "Cash Cano: Roman Riches / Tiki", None,
          "gems toward unlocked jackpot rows",
          "Hold-and-spin collects gems toward four jackpot rows. State value depends "
          "on gems banked toward unlocked rows."),
    _bank("bc-cruise", "Brian Christopher's World Cruise", None,
          "fat ducks (high bonus meters)",
          "Three duck bonuses fatten as scatters land; a fatter duck pays better when "
          "triggered. Play the fattest ducks."),
    dict(id="super-bowl", name="Super Bowl Jackpots", maker=None, type="bank",
         grp="Banking / vulture state", bspins=4, rtp=88,
         key="2-min drill every 22/24/26 min; prizes persist",
         note="A bank-wide 2-Minute Drill fires every 22-26 minutes. The drill itself "
              "is not +EV, but collected prizes PERSIST after it ends - a machine left "
              "with banked prizes is the play. Time the drill and grab abandoned banks."),

    # ===== VOLATILE / AP TRAP =====
    _trap("dragon-lights", "Dragon Lights: Fortune Skies / Mystical Falls",
          "Four free-games meters that are NOT must-hit-bys - triggers are fully "
          "random. Extremely volatile; only deep-bankroll APs, and even then it is "
          "closer to gambling than a clean edge."),
    _trap("life-of-luxury", "Life of Luxury Hot Diamonds",
          "Car/boat/plane free-games meters with random (non-MHB) triggers. Dangerous "
          "and volatile - easy to misread as a play when it is not."),
    _trap("raise-sails", "Raise the Sails / San Xing Riches",
          "Bronze/silver/gold meters with random triggers (no MHB). High variance, no "
          "guaranteed hit point - not a clean play."),
    _trap("rich-piggies", "Rich Little Piggies: Hog Wild / Meal Ticket",
          "Pigs fatten as features build, but triggers are random, not must-hit-by. A "
          "fatter pig is NOT closer to hitting - classic trap."),
    _trap("azure-dragon", "Azure Dragon / Emerald Guardian",
          "Four free-games meters with random triggers (not MHB). Looks like a play, "
          "isn't a guaranteed one."),
    _trap("fu-dai", "Fu Dai Lian Lian: Boost Peacock / Boost Tiger",
          "Bags fill and 'boost' the bonus, but fuller bags do NOT make the bonus "
          "closer to hitting. The boost only improves the bonus IF it hits. Trap."),
    _trap("captain-riches", "Captain Riches / Tiki Fortune / Mine Blast",
          "Coin-holder wild mechanic that the source itself flags as a borderline AP "
          "trap. Understand the exact rules before risking anything."),
    _trap("magic-treasures", "Magic Treasures: Dragon / Tiger",
          "Money Balls accumulate but the feature triggers RANDOMLY (counter resets "
          "to 5). Not a must-hit-by."),
    _trap("bustin-money", "Bustin' Money",
          "Three safes build features, but a fatter safe is NOT more likely to "
          "trigger. Build state is cosmetic for trigger odds - caution."),

    # ===== NOT BEATABLE (myth-buster) =====
    _myth("lightning-link", "Lightning Link (standard)",
          "No trackable must-hit-by on the playable tiers. Fast-tapping, "
          "denom-switching, 'it's due' are all myths. Not advantage-playable. "
          "(Buffalo Link and the classic Scarab are the beatable cousins - both are "
          "in this list.)"),
    _myth("dragon-link", "Dragon Link",
          "No must-hit-by thresholds on any version; Major caps at ~2x its start. "
          "Hitting the Major/Grand is pure luck - not advantage-playable."),
    _myth("dollar-storm", "Dollar Storm",
          "Adds a Super Grand Chance but still no trackable guaranteed trigger you "
          "can exploit. Not advantage-playable."),
    _myth("lock-it-link", "Lock It Link",
          "No exploitable persistent must-hit-by. Not advantage-playable."),
    _myth("spooky-link", "Spooky Link",
          "Aristocrat hold-and-spin Link game (Mo' Mummy family, Baron Portrait "
          "cabinet) with Go Yeti / Vault free-spins. Mini & minor jackpots are FIXED "
          "by denom; Grand/Major are standard random progressives, NOT must-hit-by, "
          "and the hold-and-spin coins do not persist for the next player. No "
          "trackable guaranteed trigger to exploit - same bucket as Lightning Link. "
          "If the glass actually shows a 'MUST HIT BY' ceiling on the Major/Grand, "
          "that one jackpot becomes a dollar-MHB play - send the reset & ceiling and "
          "I'll add it."),
    _myth("lock-it-piggy", "Lock It Link: Piggy Bankin' / Piggy N' More Bankin'",
          "The MODERN linked hold-and-spin version (big GRAND/MAJOR progressives - "
          "what you most often see now) - NOT the classic play. Piggy banks lock in "
          "place and break open during free spins for credit prizes, but the trigger "
          "is random, the linked progressives are not must-hit-by, and nothing "
          "persists for the next player. Do not confuse it with the classic 3-reel "
          "Piggy Bankin', which IS an advantage play (see the 'Piggy Bankin' classic "
          "3-reel' entry)."),
    _myth("bao-zhu-zhao-fu", "Bao Zhu Zhao Fu Blast",
          "Aristocrat hold-and-spin game (Asian Festival series, built from Mighty "
          "Cash Ultra + Fu Dai Lian Lian) with a 'Blast' wheel. Three hold-and-spin "
          "styles (Ultra / Double Up / Extra Spins) and four jackpots, but every "
          "trigger is RANDOM, the jackpots are flat / not must-hit-by, and the coins "
          "build only during a feature YOU triggered - nothing persists for the next "
          "player. The on-screen 'building' is the trap, not a left-behind vulture "
          "state. Not advantage-playable - same family as Fu Dai Lian Lian."),
    _myth("wicked-wheel", "Smokin' Hot Stuff Wicked Wheel",
          "Everi 243-ways with four progressives (Major ~$40, Mega ~$100, Ultra "
          "~$800, Grand ~$10,000). Looks AP-able because of the wheel and big Grand, "
          "but the Progressive Pick Bonus is PREDETERMINED - the prize is set before "
          "you pick, so pick order/timing changes nothing - and it triggers randomly "
          "with no readable must-hit-by ceiling. Not advantage-playable. (Only worth a "
          "look as a plain high-progressive +EV bet if a Grand has climbed far above "
          "its $10k reset, and even then the contribution rate is unknown.)"),
]

# ----------------------------------------------------------------------------
# Engines  (faithful port of evCounter / evDollar / evBank in index.html)
# ----------------------------------------------------------------------------

def ev_counter(g, st, bet):
    M = float(g["ceil"]); V = min(float(st), M)
    a = float(g["accr"]); U = float(g["units"]); r = float(g["rtp"]) / 100.0; b = float(bet)
    climb = max(M - V, 0.0)
    div = 1 if g.get("trig") == "fixed" else 2      # fixed = full climb; MHB = midpoint
    exp_spins = climb / (div * a) if a else 0.0
    exp_coin = exp_spins * b
    bleed = exp_coin * (1 - r)
    feature = U * b
    ev = feature - bleed
    be = M - (div * a * U) / (1 - r) if (1 - r) else M
    worst_spins = climb / a if a else 0.0
    worst_loss = -(worst_spins * b * (1 - r))
    edge = ev / exp_coin if exp_coin > 0 else 0.0
    return dict(ev=ev, be=be, worst_loss=worst_loss, edge=edge, exp_coin=exp_coin,
                gauge=dict(lo=float(g["reset"]), hi=M, cur=V, be=be))

def ev_dollar(g, st, bet):
    M = float(g["dceil"]); V = min(float(st), M)
    inc = float(g["dinc"]) / 100.0; r = float(g["rtp"]) / 100.0; b = float(bet)
    climb = max(M - V, 0.0)
    exp_coin = climb / (2 * inc) if inc > 0 else 0.0
    bleed = exp_coin * (1 - r)
    jp = (V + M) / 2.0
    ev = jp - bleed
    k = (1 - r) / inc if inc > 0 else 0.0
    be = M * (k - 1) / (k + 1) if (k + 1) != 0 else M
    worst_loss = -((climb / inc if inc > 0 else 0.0) * (1 - r))
    edge = ev / exp_coin if exp_coin > 0 else 0.0
    return dict(ev=ev, be=be, worst_loss=worst_loss, edge=edge, exp_coin=exp_coin,
                gauge=dict(lo=0.0, hi=M, cur=V, be=be))

def ev_bank(g, st, bet):
    C = float(st); s = float(g["bspins"]); b = float(bet); r = float(g["rtp"]) / 100.0
    cost = s * b * (1 - r)
    ev = C - cost
    edge = ev / (s * b) if (s * b) > 0 else 0.0
    return dict(ev=ev, be=cost, worst_loss=-(s * b * (1 - r)), edge=edge,
                exp_coin=s * b, gauge=None)

def verdict(r):
    if r["ev"] > 0 and r["edge"] >= 0.02:
        return "PLAY"
    if r["ev"] > 0:
        return "THIN EDGE"
    return "PASS"

def evaluate(g, st, bet):
    if g["type"] == "counter":
        return ev_counter(g, st, bet)
    if g["type"] == "dollar":
        return ev_dollar(g, st, bet)
    if g["type"] == "bank":
        return ev_bank(g, st, bet)
    return None

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def fmt(n, d=0):
    sign = "-" if n < 0 else ""
    return "{}${:,.{}f}".format(sign, abs(n), d)

def fmt_ev(ev):
    d = 2 if abs(ev) < 100 else 0
    return ("+" if ev >= 0 else "-") + "${:,.{}f}".format(abs(ev), d)

def find_game(q):
    """Return (game, []) on a confident match, else (None, candidates)."""
    ql = q.strip().lower()
    for g in GAMES:                                  # exact id
        if g["id"] == ql:
            return g, []
    starts = [g for g in GAMES if g["id"].startswith(ql)]
    if len(starts) == 1:
        return starts[0], []
    subs = [g for g in GAMES
            if ql in g["id"] or ql in g["name"].lower()
            or (g.get("maker") and ql in g["maker"].lower())]
    if len(subs) == 1:
        return subs[0], []
    if not subs and starts:
        subs = starts
    return None, subs

CAL_BANNER = ("  * CALIBRATED - constants validated against real floor data.")
VERIFY_BANNER = ("  ! VERIFY: reset & ceiling are reliable, but accrual & feature "
                 "payout are\n    ESTIMATES. Treat the break-even as a placeholder "
                 "until you dial them in.")
SOURCED_BANNER = ("  ~ SOURCED: constants come from published AP analysis, not this "
                  "exact machine.\n    Better than a placeholder, shy of a full floor "
                  "calibration - tune base return & bet to your game.")

def cal_level(g):
    if g.get("verified"):
        return "floor"
    return g.get("cal", "estimate")

def type_label(g):
    return {
        "counter": "count-to-trigger" if g.get("trig") == "fixed" else "counter/MHB",
        "dollar": "dollar MHB",
        "bank": "banking/vulture",
        "trap": "volatile/trap",
        "notbeatable": "not beatable",
    }[g["type"]]

def state_label(g):
    return {
        "counter": "collected" if g.get("trig") == "fixed" else "meter",
        "dollar": "jackpot $",
        "bank": "collectable $",
    }.get(g["type"], "state")

# ----------------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------------

def header_line(g):
    cal = {"floor": "CALIBRATED", "sourced": "SOURCED"}.get(cal_level(g))
    tags = [t for t in (g.get("maker"), type_label(g), cal) if t]
    return "{}  [{}]".format(g["name"], " - ".join(tags))

def render_report(g, st, bet, res):
    lines = [header_line(g)]
    if g["type"] in ("counter", "dollar", "bank"):
        if g["type"] == "counter":
            lines.append("  {} {:g}  -  reset {:g} -> ceiling {:g}  -  bet {}".format(
                state_label(g), float(st), float(g["reset"]), float(g["ceil"]),
                fmt(bet, 2 if bet % 1 else 0)))
        elif g["type"] == "dollar":
            lines.append("  jackpot {}  -  ceiling {}  -  bet {}".format(
                fmt(float(st), 0), fmt(float(g["dceil"]), 0),
                fmt(bet, 2 if bet % 1 else 0)))
        else:
            lines.append("  collectable {}  -  {:g} spins to grab  -  bet {}".format(
                fmt(float(st), 0), float(g["bspins"]), fmt(bet, 2 if bet % 1 else 0)))
        call = verdict(res)
        lines.append("")
        lines.append("  VERDICT:  {:<10}   EV/session  {}".format(call, fmt_ev(res["ev"])))
        edge = res["edge"]
        lines.append("  edge {}{:.1f}%        {}  {}".format(
            "+" if edge >= 0 else "-", abs(edge) * 100,
            "cost to collect" if g["type"] == "bank" else "break-even " + state_label(g),
            fmt(res["be"], 2) if g["type"] == "bank" else "{:g}".format(round(res["be"]))))
        lines.append("  worst-case loss  {}".format(
            fmt(res["worst_loss"], 2 if abs(res["worst_loss"]) < 100 else 0)))
        lines.append("")
        lvl = cal_level(g)
        if lvl == "floor":
            lines.append(CAL_BANNER)
        elif lvl == "sourced":
            lines.append(SOURCED_BANNER)
        else:
            lines.append(VERIFY_BANNER)
    else:
        lines.append("  bet has no effect - this is not a math play.")
        lines.append("")
        lines.append("  VERDICT:  {}".format(
            "NOT BEATABLE" if g["type"] == "notbeatable" else "PASS"))
        lines.append("")
    lines.append("")
    lines.append("  " + g["note"])
    return "\n".join(lines)

def render_sweep(g, bet, points=12):
    if g["type"] != "counter":
        return "  (sweep is only available for counter games)"
    lo, hi = float(g["reset"]), float(g["ceil"])
    out = ["  SWEEP  reset {:g} -> ceiling {:g}  (bet {})".format(
        lo, hi, fmt(bet, 2 if bet % 1 else 0)),
        "  {:>8}  {:>10}  {:>8}  {}".format("meter", "EV", "edge", "call")]
    step = (hi - lo) / points if points else 0
    seen_play = False
    for i in range(points + 1):
        m = lo + step * i
        res = ev_counter(g, m, bet)
        call = verdict(res)
        flag = ""
        if call.startswith("PLAY") and not seen_play:
            flag = "  <- flips to PLAY"
            seen_play = True
        out.append("  {:>8.0f}  {:>10}  {:>7.1f}%  {}{}".format(
            m, fmt_ev(res["ev"]), res["edge"] * 100, call, flag))
    out.append("  break-even meter = {:g}".format(round(ev_counter(g, lo, bet)["be"])))
    return "\n".join(out)

def log_event(g, st, bet, res):
    path = os.path.expanduser("~/.claude/state/slot-ev/log.ndjson")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rec = dict(ts=int(time.time()), id=g["id"], name=g["name"], type=g["type"],
               state=float(st), bet=float(bet), verified=bool(g.get("verified")))
    if res:
        rec.update(ev=round(res["ev"], 2), be=round(res["be"], 2),
                   edge=round(res["edge"], 4), call=verdict(res))
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return path

# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

USAGE = """Slot Deal Desk - +EV engine for persistent-state slots

  slot_ev.py <game> <meter> [bet]            evaluate one state (bet default $5)
  slot_ev.py <game> <meter> [bet] --sweep    table of EV across the meter band
  slot_ev.py <game> <meter> [bet] --log      also append to the ndjson dataset
  slot_ev.py list [filter]                   list machines (optionally filtered)
  slot_ev.py --help

  <game> is a fuzzy match on id / name, e.g. 'buffalo', 'scarab', 'ocean'.
  For dollar games <meter> is the current jackpot $, for banking games it is
  the credit value you can collect.
"""

def cmd_list(args):
    flt = args[0].lower() if args else None
    grp = None
    for g in GAMES:
        if flt and flt not in g["id"] and flt not in g["name"].lower() \
                and flt not in g["grp"].lower():
            continue
        if g["grp"] != grp:
            grp = g["grp"]
            print("\n" + grp)
        star = " *" if g.get("verified") else ""
        print("  {:<20} {}{}".format(g["id"], g["name"], star))
    print()

def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}

    if not args or "--help" in flags or "-h" in flags or args[0] in ("help", "--help"):
        print(USAGE)
        return 0
    if args[0] == "list":
        cmd_list(args[1:])
        return 0

    query = args[0]
    g, candidates = find_game(query)
    if g is None:
        if candidates:
            print("Ambiguous '{}' - did you mean:".format(query))
            for c in candidates[:12]:
                print("  {:<20} {}".format(c["id"], c["name"]))
        else:
            print("No machine matches '{}'. Try: slot_ev.py list".format(query))
        return 1

    if g["type"] in ("trap", "notbeatable"):
        print(render_report(g, 0, 0, None))
        return 0

    if len(args) < 2:
        print("Need a {} for {}.\n".format(state_label(g), g["name"]))
        print("  slot_ev.py {} <{}> [bet]".format(g["id"], state_label(g)))
        return 1

    try:
        st = float(args[1])
        bet = float(args[2]) if len(args) > 2 else 5.0
    except ValueError:
        print("Meter and bet must be numbers.")
        return 1

    res = evaluate(g, st, bet)
    print(render_report(g, st, bet, res))
    if "--sweep" in flags:
        print()
        print(render_sweep(g, bet))
    if "--log" in flags:
        path = log_event(g, st, bet, res)
        print("\n  logged -> {}".format(path))
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
