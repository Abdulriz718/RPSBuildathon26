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

| 8 | | | #7 behaviour + ROOF_CLIMB (jet onto roofs for roof weapons; 96% of test climbs succeed). Survival gameplans added but OFF | | |

## Survival gameplans (Abdul's tips) in the free-for-all sim (`tools/ffa.py`, 16 mechs, house-bot skill mix, 240 paired seeds)

| variant | vs baseline | died 13th-16th (of 240) |
|---|---|---|
| baseline (farm mode, roofs on) | 10.73 | 42 |
| `MODE='ffa'`: only fight attackers or weak lone targets, avoid the rest | **+1.05 +-0.31** | 29 |
| ffa + hold near zone edge (`ZONE_MARGIN=0.92`) | +1.10 +-0.30 | 25 |
| hold near zone edge alone | +0.06 +-0.14 | 39 |
| `AVOID_FIGHT_SOUNDS`: hold away from fights heard/seen | -0.12 +-0.12 | 44 |
| `MULTI_DISENGAGE`: back off when 2+ attackers | -0.01 +-0.12 | 35 |
| roof climbing off | -0.01 +-0.07 | 42 |

Practice-style duels (hunters chase us, 120 each, hard x1 / hard x2): baseline 80/30, AVOID_FIGHT_SOUNDS 79/30,
MULTI_DISENGAGE 79/31, `MODE='ffa'` 69/14 (hurts practice), roof on vs off 61/30 vs 61/27 (expert x1 / hard x2).

So: `ffa` mode is the one survival plan that works, and only in a real free-for-all. Next: detect FFA during the match
(other mechs damaging each other never happens in practice) and switch to it automatically.

Sim fixes this round (earlier numbers were wrong): (1) worker processes kept one variant's config overrides for the
next variant, so everything after `MODE='ffa'` in a comparison silently ran in ffa mode; now each job reloads
`bot/config.py`. (2) A*, cover search and the tick guard ran on wall-clock budgets, so results depended on CPU load;
the sim now gives them room, and a repeated seed reproduces exactly.

| 9 | | | Abdul's 3 requests: zig-zag+hop under fire, AVOID_PEOPLE+MULTI_DISENGAGE+AVOID_FIGHT_SOUNDS, laser-only + laser roam | 2.75 | NO: practice sim predicted the drop (0.92 vs ~2.2 on 12 matches). Best is still 3.40 |
| 10 | | | 3.40 behaviour + STYLE='kite' (hold 120-170 m, boost away when closer) | | |

## Practice sim (`tools/practice.py`): calibrated on 8 scored versions, correlation 0.94 with real scores

Sim scores run ~1.3 below real. Model: 15 house bots as one squad (no friendly fire), 1 hunter at start, +1 per kill,
all hunt after 300 s; cubes, upgrades, 12 NPC drones, zone, 40 floor weapons.

What-if (144 paired): start with laser +1.10, 10 cubes +0.50, laser+10 cubes +1.68, lightning -0.48, mortar -0.24.
Config/feature tries, no gain (vs base): ffa mode -0.94, retreat at 30% -0.35, zone centre -0.19, zone edge +0.05,
disengage -0.05, avoid sounds +0.01, aim 2.0 +0.10, cube collection 0, drone farming -0.08, laser-only +0.03..+0.12,
combined gun+laser fire -0.01.

Play styles, 48-match screen (vs default): kite 120-170 m +0.44, kite 170-220 +0.35, kite 90-140 +0.27,
assassin -0.15, rush -0.23, zigzag under fire -0.50, roof camping -1.17, kite without boost -0.12.
Confirmed (144): kite 120-170 +0.33 +-0.12, with boost at 20+ energy +0.35 +-0.13 -> new default.
Caveat: the sim has no trees; real sight lines are shorter, so the real gain may be smaller.

## New cycle, Phase 1 — measurement only

The team confirmed that commit `5e443a9` earned the official practice score of **3.25**.
The Phase 1 benchmark used that same bot revision.

- `tools/duel.py` runs the bot and expert Hunter decisions every two simulation ticks.
  `tools/sim.py` applies movement, rotation, energy, weapon triggers, projectile travel,
  damage and regen at 20 Hz. Grounded jump starts flight; airborne boost spends jet
  energy for upward acceleration. `Weapons.dodge` handles projectile/charge threats;
  experimental all-direction escape scoring is behind the existing defensive flag.
- In arena evaluation, 16 mechs start on walkable ground inside the first circle.
  Fifteen expert opponents target their nearest living rival. The shrinking circle
  interpolates center and radius, damages outside mechs without armor, and interrupts
  regen. Rank uses death tick, shared placement on ties, and HP for clock survivors.
  Points are 16 minus place. This expert FFA differs from official coordinated practice.
- The zone uses the protocol's phase holds, shrink durations, radii and DPS. The
  evaluation-only time/radius scales and seeded center drift live beside `MatchZone` in
  `tools/sim.py`. The reference clip covers only the opening, so the protocol supplies
  the full approximately 6:55 collapse. The limit is eight minutes.
- `tools/bench.py --matches` compares farm and FFA modes, four test starting kits
  (gun alone or paired with laser, mortar or lightning), all 16 ordered 1v1 kit pairs
  per seed, and mixed kits plus floor pickups in arena matches. Duels keep their kits
  fixed. The simulator omits upgrade offers, NPCs, crates and supply drops. Numeric
  weapon stats are the baseline rules; this is not an exhaustive upgrade sweep.
- Metrics: 1v1 evasion is damage-free 20 Hz ticks divided by ticks with a firing enemy
  or hostile projectile in flight. This measures exposure, including cover and misses;
  it is not per-shot dodge probability. Direction is commanded movement relative to
  torso yaw. Per-weapon rows group by expert starting kit. Jet efficiency is positive
  vertical metres during powered flight per jet energy spent across both scenario types.
  Zone survival counts arena matches without zone-caused death, including combat deaths.
- Local checks: 16 unit tests passed, sparse and full-match hardening passed, farm/FFA
  fuzz p99 4.8 ms. Replay bench: 900 decisions, p99 0.71 ms, zero errors/fallbacks.
  Official checker: 300/300 on time, p99 2.3 ms.

### Baseline observations

One fixed seed (1) and one fresh random seed (5335629), shared across modes. Replay
the matrix with `python tools/bench.py --matches --seeds 1 5335629 --random-seeds 0`.
Each mode played 8 arena matches and 32 duels. These two seed clusters are a small
baseline for paired changes, not a leaderboard forecast.

| Metric | Farm | FFA |
|---|---:|---:|
| Arena points by seed, within seed gun / laser / mortar / lightning | 3,9,8,8 / 5,6,7,7 | 3,8,7,8 / 9,9,8,7 |
| overall_score | 6.625 | 7.375 |
| Arithmetic difference vs official 3.25 (different opponent format) | +3.375 | +4.125 |
| 1v1_evasion_rate | 6533/7098 | 10981/11594 |
| jetpack_efficiency (metres/energy) | 101.46/171 | 301.995/597.75 |
| zone_survival_rate | 8/8 | 8/8 |

Damage-free / pressured ticks by direction and by expert kit:

| Group | Farm | FFA |
|---|---:|---:|
| Front | 0/0 | 12/12 |
| Front-left | 0/0 | 0/0 |
| Left | 3622/3913 | 3448/3606 |
| Back-left | 32/44 | 1177/1193 |
| Back | 29/33 | 1431/1436 |
| Back-right | 60/92 | 212/248 |
| Right | 2044/2270 | 3249/3645 |
| Front-right | 48/48 | 38/40 |
| Still | 698/698 | 1414/1414 |
| Gun only | 1517/1722 | 1809/2025 |
| Gun + laser | 1188/1334 | 1493/1643 |
| Gun + mortar | 2599/2605 | 6204/6243 |
| Gun + lightning | 1229/1437 | 1475/1683 |

0/0 means no exposure observed. No policy update or training occurred.

## New cycle, Phase 2 — directional evasion and jetpack

The team reports an official **3.4**. Local comparisons use the latest merged
revision, `dd6ac5d`. The log does not associate the 3.4 submission with a SHA.
This comparison uses Abdul's merged zone simulator with current-circle observations.
Its scores should be compared within this table because the arena changed after
Phase 1 and official practice uses coordinated opponents.

The `DUEL_EVASION` experiment compares the existing movement command with eight
directions, grounded jumps, and short jet bursts when one opponent is tracked.
It keeps the existing command unless it predicts projectile contact and finds a
safer path. It factors in acceleration, gravity, terrain, charge slowdown,
energy reserve, and both current and next circles. Roof pickup navigation is
provided by the merged bot.

| Metric | Farm default | Farm + evasion | FFA default | FFA + evasion |
|---|---:|---:|---:|---:|
| Mean arena placement points | 7.375 | 7.125 | 6.000 | 7.375 |
| Damage-free ticks under pressure in 1v1 | 92.03% | 93.72% | 94.71% | 95.47% |
| Powered ascent metres | 90.78 | 128.92 | 294.14 | 406.30 |
| Jet energy spent | 153.00 | 222.00 | 594.00 | 807.75 |
| Metres per jet energy | 0.5933 | 0.5807 | 0.4952 | 0.5030 |
| Arena matches without a zone death | 8/8 | 8/8 | 8/8 | 8/8 |

`python tools/bench.py --matches --seeds 1 5335629 --random-seeds 0` runs the
default. Append `--set DUEL_EVASION=True` to run the candidate. Eight arenas
and 32 duels per mode per variant. Both configured modes with the candidate
produced observations in all eight movement directions. Direction coverage is
uneven. Candidate farm front and front-left had 30 and 32 pressured ticks.

Decision: leave `DUEL_EVASION` off by default. The two seed clusters show lower
farm placement and higher FFA placement.
Local checks passed: 17 focused tests, hardening, replay benchmark, fuzz with
 the candidate enabled, and 300/300 protocol observations answered on time.

Practice follow-up (team-reported): the next submission scored **3.17**,
**0.23 below 3.4**. The checked-in `c3ef5f8` config has `DUEL_EVASION=False`.
The scorer's submitted SHA and flag setting are unconfirmed, so the result is
recorded without attributing the change to evasion. **3.4 remains the best
confirmed score.**

## New cycle, Phase 3 — offline movement tuning

Farm mode on `c3ef5f8`. Training seeds 1 and 5335629, holdout seeds 271828 and
7813031. Each row represents 8 arenas and 32 expert duels. The higher reserve
candidate changed only the Phase 2 jet energy reserve from 25 to 45. It tied the
original evasion candidate on training, so the original advanced to holdout.

| Split and setting | Mean arena points | Duel wins | Damage-free pressured ticks | Jet metres/energy | No zone death |
|---|---:|---:|---:|---:|---:|
| Training, default | 7.375 | 16/32 | 92.03% | 90.78/153.00 | 8/8 |
| Training, evasion | 7.125 | 21/32 | 93.72% | 128.92/222.00 | 8/8 |
| Training, evasion with reserve 45 | 7.125 | 21/32 | 93.72% | 128.92/222.00 | 8/8 |
| Holdout, default | 8.625 | 17/32 | 94.46% | 275.01/463.50 | 8/8 |
| Holdout, evasion | 8.875 | 22/32 | 95.52% | 302.975/525.00 | 8/8 |

Evasion gained five duel wins on each split and raised jet energy use. Its arena
placement changed by -0.25 on training and +0.25 on holdout. The default passed
the selection gate because the evasion candidate failed to improve both splits.
These are simulated placements with a small number of distinct arena seeds.
The official record remains 3.4 followed by 3.17. No submission was made.

Reproduce with `python tools/bench.py --tune-movement --seeds 1 5335629 --holdout-seeds 271828 7813031 --workers 4`.
The replay benchmark measured 1.88 ms p99 with zero fallbacks. All 17 unit tests
passed and the protocol checker received all 300 answers on time.

## Sim hunter accuracy check (handoff step 1): no recalibration needed

The handoff said real house bots hit 60-89% and the sim's 32% on us made real fights look half as deadly. Checked:

- Real replay `mechanics-v2-16` pooled over all 16 bots: 1061 gun shots, 433 hits on mechs (41%) + 171 on drones
  (16%) = 57%. The 60-89% figures were per-bot and included drone hits. With drone shots removed (hit at ~85%),
  mech-on-mech accuracy is about **50%**. `duel-hard-4` (hard vs hard 1v1): 66% on 77 shots.
- Sim house bots shooting each other in `tools/ffa.py` (6 matches): easy 36%, medium 44%, hard 55%, expert 68%,
  pooled **51%**. That matches the real ~50%, so the aim model is already right.
- Against us in `tools/practice.py` they hit 32-33% of shots. Removing all aim noise and reaction delay only lifts it
  to 36%. Bullets that reach us miss by 0-2 m sideways: our bot changes direction during the 0.2-0.4 s flight.
  So the gap is our movement, not hunter skill. The real hit rate on us is unknown (no replays of our matches).
- New knobs kept for later what-ifs: `--squad noise_scale=0.5 react_scale=0.5`.

## Auto-detect free-for-all (`AUTO_FFA`, off by default)

Brain switches farm -> ffa once (alive drop) - (our `kill` events) >= 2 in the first 200 s. Practice house bots only
die to us, so this should never fire in practice.

| sim | variant | vs base | switched to ffa |
|---|---|---|---|
| practice, 144 paired | `AUTO_FFA=True` | -0.01 +-0.01 | 2/144 |
| practice, 144 paired | threshold 1 | -0.03 +-0.03 | 15/144 |
| ffa, 120 paired (base 10.91) | `AUTO_FFA=True` | -0.12 +-0.20 | 109/120, median t=18 s |
| ffa, 120 paired | `MODE='ffa'` always | +0.00 +-0.46 | 120/120 |

Detection works (fires early in a real FFA, almost never in practice), but ffa mode itself no longer beats farm in the
current FFA sim (the earlier +1.05 was before the `19050b9` sim-bot changes). Left off. Flip it on only if ffa mode
is re-tuned and wins again.

## Heal between kills (`HEAL_BETWEEN`, brain.py HEAL mode)

Below 70% HP, with no mech in sight and no hits either way for 3 s: break line of sight from the last threat, hold
fire (dealing damage resets regen too) and reload, until 95% HP. Any damage taken ends it, so we fight back.

- First try started after 1.5 s without being hit. That fired mid-fight during hunter reloads: 28 of 34 heal spells
  ended with us shot at lower HP. Practice sim -0.17 +-0.08. Fixed by requiring no visible mech and no hits either way.
- Fixed version, 12 matches instrumented: 8 heal spells, typically +10 to +40% HP before a hunter finds us.
- Practice sim, 144 paired: start 70% **+0.09 +-0.05**, start 90% +0.08 +-0.07. Small, but no harm.

| 11 | | | 3.40 behaviour + HEAL_BETWEEN (start 70%, stop 95%, calm 3 s), commit 372872f | 3.27 | inconclusive: within noise of 3.40 |

## Crate hunting for a laser (`CRATE_HUNT`, brain.py CRATE mode)

Crates (36 per match, 300 HP, 50% weapon drop) were only shot when idle: HOLD mode, drones first, within 90 m,
before 150 s. CRATE mode: while we hold no laser, before 240 s, nothing hit us for 2 s and no visible mech within
100 m, walk to the nearest remembered ground crate (up to 200 m, inside 90% of the next circle) and shoot it from
60 m. WEAPON mode, earlier in the cascade, picks up the drop (laser bonus 70 m).

Bug fixed on the way: a crate broken from range stayed in memory until we walked within 20 m, so the bot could stand
shooting at nothing. Now a remembered crate in plain view (in FOV or near range, line of sight) that isn't listed
is forgotten.

Not testable in the sims (no crates). Checked on the recorded stream plus a synthetic setup: walks to an 80 m crate,
stands and fires on 29/30 ticks at 30 m, forgets it once gone. `HEAL_BETWEEN` is off in this build so crates are
measured alone against 3.40.

| 12 | | | 3.40 behaviour + CRATE_HUNT (HEAL off) | 3.15 | inconclusive, below 3.40; off |

## The 3.40 behaviour was not the default after all

Identity check in the practice sim (same 24 seeds, exported `4af2045` vs current code): only **5/24** matches came
out identical. Three changes made after 3.40 were on by default, so #9-#12 were not "3.40 + one change":
`COMBINED_FIRE=True`, `CUBE_COLLECT=True`, and the torso weapon sweep continuing until a laser (3.40 stopped at any
2nd weapon). With those off (`COMBINED_FIRE=False`, `CUBE_COLLECT=False`, new `SWEEP_UNTIL_LASER=False`): **24/24**
identical, with `AUTO_FFA` on or off. Those are now the defaults.

| 13 | | | exact 3.40 behaviour (24/24 identical in sim) + AUTO_FFA on (FFA detector for the final) | 3.33 | consistent with 3.40; keep as base |

## Fight position scoring ("slicing the pie", `SLICE`, off)

Every 0.3 s in FIGHT, score ~37 ground spots within 16 m: line of sight to the target, -150 per other known enemy
that can see the spot, cover within 4 m, height, travel, range. Hide from all known enemies while reloading.
Optional `SLICE_LASER_PEEK`: charge the laser out of sight.

Mechanism check (12 practice-sim matches, share of FIGHT ticks where 2+ hunters can see us):

| build | seen by 2+ | kills | decide p99 / max |
|---|---|---|---|
| base | 19% | 25 | 2.4 / 13.9 ms |
| SLICE v1 (always go to best spot) | 26% | 23 | 6.6 / 8.4 ms |
| v1 with crossfire 150, cover 30 | 26% | 22 | 7.3 / 8.9 ms |
| v2 (relocate only when clearly better, else old peek/strafe) | 22% | 26 | 8.3 / 25.8 ms |

It didn't reduce crossfire. In half of the crossfire ticks the bot had never seen the second hunter (outside the
120-degree view), so no scoring can avoid it. v1 also stood still 74% of fight ticks, which made it easier to hit.
Left off; not submitted.

## Awareness: threat memory, always-on scanning, strafe jitter

Note: the server already reports a mech's real position for `vision.memory_s` (5 s) after it leaves view, so the
bot never "forgot" an enemy after 0.75 s; it kept fighting it for 5 s. These flags cover the time after that.

- `THREAT_MEMORY`: keep tracks 12 s. With nobody in view, face the newest lost enemy's predicted position
  (velocity, capped at 2 s) and hold the zone spot (WATCH mode) instead of farming drones or looting.
- `SCAN_ALWAYS`: sweep the torso whenever there's no target (3.40 swept only until it had a 2nd weapon); in a fight,
  look around while hidden in cover with more than 1.2 s of gun reload left and nothing else to fire.
- `STRAFE_JITTER`: random strafe flips in 0.6-1.4 s (was fixed 1.3 s), plus a flip when the target fires at us.

Mechanism screen, practice sim, 48 paired (rear dmg = share of damage taken in the rear arc, x1.5 damage):

| variant | vs base | hunters' hit% on us | rear dmg |
|---|---|---|---|
| base | - | 32 | 21% |
| THREAT_MEMORY | +0.02 +-0.06 | 33 | 19% |
| SCAN_ALWAYS | +0.00 +-0.08 | 30 | 19% |
| STRAFE_JITTER | -0.06 +-0.10 | 34 | 24% |
| jitter, random intervals only | -0.08 +-0.10 | 34 | 23% |
| all three | +0.02 +-0.13 | 31 | 21% |

Jitter makes us easier to hit (flipping more often than every 1.3 s means less net sideways speed): off.
Memory + scanning are on for the next submission. Flags off still plays 24/24 identical to the 3.40 build.

| 14 | | | 3.40 behaviour + THREAT_MEMORY + SCAN_ALWAYS | 3.38, 3.42 (resubmitted) | same as base; best so far |

## Server noise is small: tune on the server

Same commit (`296e04e`, #14) submitted twice: 3.38 and 3.42. Base-behaviour runs so far: 3.40, 3.33, 3.38, 3.42.
Noise is about +-0.05, not the +-0.5 assumed earlier, so a change of 0.1 or more on the server is real.
Plan: one setting per submission on the server, keep what goes up. Sim (96 paired) only orders the queue:
no drone farming +0.09 +-0.05, laser detour bonus 120 m +0.05 +-0.04, strafe flip 1.8 s +0.05 +-0.10;
aim tolerance 1.6 / 2.0, weapon swap 80 m, zone margin 0.9 and full-speed dodge were flat or worse.

| 15 | | | #14 + NPC_FARM_M=0 (no drone farming) | | |
