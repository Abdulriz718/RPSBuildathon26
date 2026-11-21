# Submission log

Noise is about ±0.5. Trust a change only if it moves the score by more than 0.7, or repeats.

| # | time | commit | change (one thing) | score | keep? |
|---|------|--------|--------------------|-------|-------|
| 1 | Phase 0 | main @ Phase 0 merge | Kit example behaviour in our module layout (baseline) | 1.13 | yes (= kit 1.15 within noise) |
| 2 | Phase 1 | main @ a1d4ea6 | Phase 1: nav + zone hold (A), lead aiming + LOS-gated fire + threat bearing (B) | 1.52 | yes (+0.37, borderline vs noise) |
| 3 | Phase 2 | main @ 9444dad | Phase 2 A + B merged | 0.17 | NO: merge left two cover_goal/cover_from defs and two decide bodies; decide() threw on 251/300 replay ticks, so the bot mostly didn't shoot. bench.py showed it (753 errors) but wasn't run |
| 4 | Phase 3 | main @ 6cfb5ff | Crash fix + single brain + Phase 3 (drops, late-zone anchor, endgame) all ON | 1.88 | yes (+0.36 over #2). Top teams ~6.3 |
| 5 | Phase 4 | main @ 5b7cdd2 | Phase 4 hardening (timing only) | 2.02 | yes: new baseline for queue A-D |

## Queue: one config change each, all against #5 (main @ Phase 4, 2.02)

Practice place is roughly 16 minus the number of house bots dead before us, and they only die to us
(or the zone). 1.88 means we lose around the 2nd or 3rd duel. These test what limits duels most.

| id | change in bot/config.py | question it answers |
|----|--------------------------|---------------------|
| A | ~~`GUN_AIM_FRACTION = 1.3`~~ | answered by the simulator, now default |
| B | ~~`COVER_LOW_HP`~~ | answered by the simulator (0.0), now default |
| C | `NPC_FARM_M = 130`, `NPC_FARM_HP = 0.5` | Do more early cubes (+4% HP and damage each) win later duels? |
| D | `MODE = "ffa"` | Does avoiding fights beat taking them in practice? (also our only data on the final's mode) |

Keep a change only if it beats 2.02 by more than about 0.7, or repeats.

### How to run the queue (all four variants already pass bench, hardening and check.py)

1. Merge Phase 4 to main, submit it once as the new baseline (#5). Phase 4 only changed timing, so expect about 1.88.
2. For each of A, B, C, D, in order: change only that line on main, commit as `exp A: GUN_AIM_FRACTION 1.3` (etc.), push, submit, log the score here, then **revert the line** before the next one. Never stack two variants.
3. 4 submissions per hour: baseline + A, B, C fit in the first hour, D in the next.
4. After the queue: combine only the winners (each > baseline + 0.7) into one commit and submit it twice to confirm.
5. Whichever commit has the best confirmed score is what you lock at the cutoff. Leave `MODE = "farm"` unless D wins clearly.

## Duel simulator results (tools/duel.py, 60-80 duels each, gun vs gun unless noted)

Win % for our bot against one scripted hunter. The hunter knows where we are, closes on A*, strafes and leads its shots.

| config | easy | medium | hard | expert | 2x medium (kills/duel) |
|---|---|---|---|---|---|
| Phase 4 defaults (submitted 2.02) | 52 | - | 0 | 0 | 0.01 |
| `COVER_LOW_HP=0` | 97 | - | 43 | - | - |
| `COVER_LOW_HP=0`, `GUN_AIM_FRACTION=1.3` (new defaults) | 96 | 85 | 82 | 34 | 0.34 |
| new defaults + we hold a laser | - | - | 100 | 100 | - |
| new defaults, both hold gun+laser | - | - | 75 | - | - |

- Old bot spent 45-60% of each duel in RECOVER with its trigger off, while the hunter followed and kept shooting.
- `STRAFE_S` 0.6 vs 2.5: no difference.
- With 2 hunters, 15% of damage taken is from behind (x1.5).
- Not modelled: trees, hunters using cover, crates/drones/zone. Use for comparisons, not absolute numbers.

With 40 floor weapons (a quarter on roofs) and hunters that loot them and use mortar/lightning/laser (100 duels each):

| config | hard | expert | our end loadout (of 100) |
|---|---|---|---|
| new defaults, no weapon policy | 72 | 48 | gun-only 64-70 |
| + WEAPON mode (now default) | 79 | 65 | gun-only 28-31, laser 32-37 |

Expert, 200 duels, win % by what we held at the end: gun+laser 91, gun+mortar 50, gun+lightning 48, gun only 36.
Variants (fetch range 250 m, swap range 90 m, bigger laser bonus, ignore fights under 40 m) all 65-66%: defaults kept.

| 6 | | | `COVER_LOW_HP=0`, `GUN_AIM_FRACTION=1.3`, `ENDGAME_LOW_HP=0` (sim: hard 0% -> 82%) | 2.31 (per PLAN.md note) | yes |
| 7 | | | #6 + WEAPON mode: fetch best seen floor weapon (laser > lightning > mortar), sweep torso while unarmed, swap up to laser within 45 m (sim expert: 48% -> 65%) | 3.23 | yes: current best (main @ 1079658 behaviour) |

## Sample replay (play.joinbuilders.org/replays/mechanics-v2-16.jsonl.gz): 16 house bots, FFA

`python tools/replay_stats.py replays/mechanics-v2-16.jsonl.gz --mech 9`
- Every bot that lasted took a 2nd weapon 2-10 s after spawn. Winner (brawler): lightning at 10 s.
- Gun hit rate 60-89% (median about 70%). This is the bar for H1.
- 10-45% of time on roofs (expert 45%). We never climb (H6).
- Always moving: 7-8.5 m/s average, boosting 20-28% of the time.
- Winner farmed hard: drone at 14 s, crates, 16 cubes, a drop, gun_damage x2 + lightning upgrades, 7794 damage.
- Median hit range 45-75 m. Match ended at 3:30 with one survivor.

## Deaths observed (fill in from replays of our matches)

| match | t | killed by / weapon | what our bot was doing (mode, label) | fix idea |
|-------|---|--------------------|--------------------------------------|----------|

## Defensive evasion (Codex, `DEFENSIVE_EVASION`, off by default) — sim A/B, 100 duels each

| setup | off | on |
|---|---|---|
| hard x1 | 81% | 78% |
| expert x1 | 65% | 61% |
| medium x2 | 37% | 36% (AVOID 4% of time) |
| hard x2 | 29% | 29% (AVOID 3% of time) |

No measurable gain; leave off. Same session, no gain either (expert x1 / hard x2, 100 each):
`GUN_AIM_FRACTION` 1.7 (62/28) or 2.2 (67/29), `COVER_RADII_M=()` (64/31), `KEEP_OFF_LIGHTNING_M=0` (62/30).
Config tuning has plateaued in the sim: next gains need new behaviour (two-hunter play, roofs, cubes).

## Two-hunter fights (sim, hard x2 unless noted, 100-120 duels each)

Diagnostics (`duel.py` now prints them for 2+ hunters): hunters >90 deg apart 33-34% of the time, both in our
view only 21-22%, target switches 0.8/duel, first kill median 15 s. Win % by end loadout: gun+laser 58,
gun+lightning 31, gun+mortar 7, gun only 6.

| tried | hard x2 | medium x2 | kept? |
|---|---|---|---|
| baseline | 28-29% | 34-37% | - |
| kite away from both attackers when spread > 70 deg (visible tracks only) | 30% (ran 2% of the time) | - | no |
| + unseen attackers from `damaged` bearings and gunshot sounds | 28% (ran 7%), rear damage 15% unchanged | - | no |
| shoot nearest instead of weakest | 28% | 33% | no |

Conclusion: in the sim, 1-vs-2 is a damage race. Positioning and target choice don't move it; holding a laser does
(58% vs 6%). Code for the tries above was removed; only the diagnostics stay.
