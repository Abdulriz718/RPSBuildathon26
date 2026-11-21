# Submission log

Noise is about ±0.5. Trust a change only if it moves the score by more than 0.7, or repeats.

| # | time | commit | change (one thing) | score | keep? |
|---|------|--------|--------------------|-------|-------|
| 1 | Phase 0 | main @ Phase 0 merge | Kit example behaviour in our module layout (baseline) | 1.13 | yes (= kit 1.15 within noise) |
| 2 | Phase 1 | main @ a1d4ea6 | Phase 1: nav + zone hold (A), lead aiming + LOS-gated fire + threat bearing (B) | 1.52 | yes (+0.37, borderline vs noise) |
| 3 | Phase 2 | main @ 9444dad | Phase 2 A + B merged | 0.17 | NO: merge left two cover_goal/cover_from defs and two decide bodies; decide() threw on 251/300 replay ticks, so the bot mostly didn't shoot. bench.py showed it (753 errors) but wasn't run |
| 4 | Phase 3 | main @ 6cfb5ff | Crash fix + single brain + Phase 3 (drops, late-zone anchor, endgame) all ON | 1.88 | yes (+0.36 over #2). Top teams ~6.3 |

## Queue: one config change each, all against #4 (main @ Phase 4)

Practice place is roughly 16 minus the number of house bots dead before us, and they only die to us
(or the zone). 1.88 means we lose around the 2nd or 3rd duel. These test what limits duels most.

| id | change in bot/config.py | question it answers |
|----|--------------------------|---------------------|
| A | `GUN_AIM_FRACTION = 1.3` (was 0.8) | Are we holding fire too often while the torso tracks? |
| B | `COVER_LOW_HP = 0.35` (was 0.55) | Are we breaking off duels we'd win? |
| C | `NPC_FARM_M = 130`, `NPC_FARM_HP = 0.5` | Do more early cubes (+4% HP and damage each) win later duels? |
| D | `MODE = "ffa"` | Does avoiding fights beat taking them in practice? (also our only data on the final's mode) |

Keep a change only if it beats 1.88 by more than about 0.7, or repeats.

### How to run the queue (all four variants already pass bench, hardening and check.py)

1. Merge Phase 4 to main, submit it once as the new baseline (#5). Phase 4 only changed timing, so expect about 1.88.
2. For each of A, B, C, D, in order: change only that line on main, commit as `exp A: GUN_AIM_FRACTION 1.3` (etc.), push, submit, log the score here, then **revert the line** before the next one. Never stack two variants.
3. 4 submissions per hour: baseline + A, B, C fit in the first hour, D in the next.
4. After the queue: combine only the winners (each > baseline + 0.7) into one commit and submit it twice to confirm.
5. Whichever commit has the best confirmed score is what you lock at the cutoff. Leave `MODE = "farm"` unless D wins clearly.
