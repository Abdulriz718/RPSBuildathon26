# Mech Royale: team plan

Two people: **A** (Claude Code) and **B** (Codex). One repo, one bot, `main` is always submittable.

## 0. Facts that drive the strategy

1. **No local simulator.** `check/check.py` only replays 300 recorded observations; it doesn't react to you. The only real signal is the practice score (48 matches, 4 submissions/hour). stderr and debug drawings are not shown back to you.
   → Submissions are our experiments. Log every one (§5). Change one thing per submission.
2. **Practice score is noisy.** Placement over 48 matches has a std error of roughly ±0.5. A change has to be big to show up. Don't chase 0.2 differences.
3. **In practice, house bots never fight each other.** They only die to us or the zone. So our practice place ≈ 16 − (house bots dead before us). **Kills matter in practice**, because nobody else thins the field. Baseline 1.15 ≈ "kills about one bot, then dies."
4. **They hunt us weakest-first, one at a time early, more as we thin them, all of them late.** Early fights are 1v1 against an easy bot. That is the farm: kill the early hunters one at a time, heal between fights (regen 45 HP/s after 5 s with no damage), collect their cubes.
5. **The final is different:** 16 team bots, free-for-all, everyone fights everyone. There, *survival and positioning* beat aggression (third-partying, avoiding fights, holding zone edge). Practice only decides whether we make the top 32. **Build for both:** a "duel/farm" mode for practice and a "survive" mode we can tune for the FFA. Both need the same foundation.
6. **50 ms per tick, 1 CPU, 512 MB.** Target ≤ 15 ms per tick. Heavy stuff (nav grid, LOS grid) gets precomputed at `docker build` time or during the 20 s `hello` budget.
7. Rear hits do ×1.5. Always face the enemy you're fighting (legs and torso are independent: strafe while aiming).
8. Weapon triangle: laser > mortar, mortar > lightning, lightning > laser, gun neutral. Laser cook-off on mortar carriers (+60%).

## 1. Tech choice

**Python 3.13 + numpy**, single process, starting from `python/mechfight.py`.
- numpy makes grid LOS, raycasts and pathfinding fast enough; plain Python loops per tick will not be.
- Pin everything: `FROM python:3.13.x-slim@sha256:...`, `pip install numpy==<exact>` system-wide (no `--user`).
- Precompute at build time (`RUN python build_grids.py`) and save `.npy` into the image (image size isn't capped, only the repo is 20 MB).

If either of us measures > 20 ms per tick in Python, we switch the hot path to TS/bun rather than micro-optimizing.

## 2. Repo layout (Dockerfile at top)

```
Dockerfile
bot/
  main.py          # entry: mf.run(Bot); timing guard, try/except → always answer
  mechfight.py     # kit wrapper (unchanged)
  world.py         # map load, height grid, LOS, raycast           [A]
  nav.py           # A* / flow field on grid, cover finding        [A]
  track.py         # enemy tracking, velocity est., threat memory  [B]
  combat.py        # aim lead, weapon choice, fire/charge, dodge   [B]
  loot.py          # crates, cubes, pickups, upgrade picks         [B]
  brain.py         # state machine: which mode, which target, where to go [A, B reviews]
  config.py        # every tunable number in one place
tools/
  build_grids.py   # precompute at docker build                    [A]
  replay_eval.py   # offline tests on check/stream.jsonl.gz       [B]
  bench.py         # per-tick timing on the recorded stream        [B]
arena/             # copy of the map, for build-time precompute
EXPERIMENTS.md     # submission log
AGENTS.md          # short: "read PLAN.md, rules in protocol.md" (Codex reads this)
CLAUDE.md          # same pointer for Claude Code
```

**Interface contract** (agree on this first, hour 0): `brain.decide(obs) -> action` calls
`world.los(a, b)`, `world.ground(x, y)`, `nav.next_step(pos, goal) -> (mx, my, jump, boost)`, `nav.cover_from(pos, threat_pos)`,
`track.update(obs)`, `track.targets() -> list[Target]`, `combat.engage(me, target, world) -> partial action`,
`loot.want(obs) -> goal | None`, `loot.pick_upgrade(offer, me) -> int`. Stub them all on day one so both people can work in parallel.

## 3. Phases

### Phase 0: skeleton that never dies of a bug (both, first 1–2 h)
- A: repo layout, Dockerfile at top, pinned numpy, stubs, push. Run the full sandbox `check.py` command from the kit README.
- B: `bench.py` and `replay_eval.py` on `stream.jsonl.gz`; `main.py` wraps `decide` in try/except and a time guard (if over ~35 ms, return last safe action).
- **Submit #1:** starter behavior in the new layout. Confirms the pipeline and gives our own baseline.

### Phase 1: don't die stupid (h 2–6)
- A `world.py`: rasterize prisms into a 1 m "top height" grid + terrain → walkable mask, LOS by sampling the grid along a line. `nav.py`: A* on a coarse (2–4 m) grid with step-up/slope rules, re-plan every ~1 s; stuck detection (pos not changing → jump+boost / pick a side).
- B `track.py` + `combat.py` v1: lead targets (bullet 252 m/s, solve intercept), aim at center mass, stop firing when there's no LOS, reload when out of sight, always keep the torso toward the nearest threat.
- Brain v1: stay inside `next_center`/`next_radius` early, move along the zone edge, never be outside the zone when `dps` is high.
- **Submit #2, #3.**

### Phase 2: win the 1v1s (h 6–14): biggest practice gain
- B: weapon logic. Laser: charge while target is in LOS and predictable, release when the beam will hit; cancel when shorted. Lightning: only inside 45 m and the 30° cone. Mortar: lob over cover at tracked-but-unseen targets; never stand in our own splash. Weapon choice by the triangle against what the target holds (`mechs[].weapons`).
- B: dodge. Sidestep when a visible enemy has `charging: true` aimed at us; sidestep incoming projectiles; strafe perpendicular to the shooter's line.
- A: cover-peek loop. Find a spot with LOS to target but a wall 1 step away; fight, duck behind cover when HP is low or the gun is reloading, wait 5 s to regen, peek again.
- A: early loot route: nearest weapon pickup + crates inside the next zone circle in the first ~60 s, before the hunters arrive.
- Upgrade picks: rank armor / hp / weapon-we-hold > sensors > rest (B, table in `config.py`).
- **Submit 2–3 times, one change each.**

### Phase 3: late game and the final (h 14+)
- Supply drops: go only when nobody is visible near the ring; +3 cubes + full HP is huge.
- Late zone: pre-position at the center of the *next* circle early, on high ground or behind cover; prefer the side away from the most recent sounds.
- Endgame: when ranked by HP at 8:00 or zone ticks matter, avoid all damage, keep HP high.
- **FFA mode** (`config.MODE = "ffa"`): fight only when attacked or a target is low HP and alone; otherwise hide and let others thin each other. We can't test FFA on the practice server, so keep it a config switch and decide at the cutoff which submission to lock (best practice score is the default; pick the FFA-tuned one only if its practice score is close and safely inside top 32).

The default remains `MODE = "farm"`. The late-zone anchor samples walkable ground inside
the next circle and scores elevation and cover from recent shots. Safe drop selection
checks recent mech tracks and the next circle. FFA can retaliate during zone movement
and avoids initiating fights with NPCs. The practice score for these changes is pending.

### Phase 4: hardening (last 2–3 h, no new features)
- Run `bench.py` worst case; make sure p99 < 25 ms.
- Rebuild from a clean clone with the exact sandbox flags.
- Tag the commit we lock. Keep the repo public until results come out.

## 4. How we split work

| | A (Claude Code) | B (Codex) |
|---|---|---|
| Owns | `world.py`, `nav.py`, `brain.py`, Dockerfile, `build_grids.py` | `track.py`, `combat.py`, `loot.py`, `tools/*` |
| Phase 2 focus | cover/peek, movement, zone | weapons, dodge, upgrades |
| Submits | whoever finishes a change; post the result in EXPERIMENTS.md | |

Rules:
- Short-lived branches (`a/nav-astar`, `b/laser-charge`), PR into `main`, other person skims it. Don't both edit `brain.py` at once: say so in chat first.
- Every PR must pass `python3 check/check.py -- python3 -u bot/main.py` and `bench.py`.
- Tunables go in `config.py`, never inline. Makes one-variable experiments easy.
- Both agents read `PLAN.md` + `protocol.md` before work. Keep `PLAN.md` current when decisions change.

## 5. Submission discipline (4/hour)

`EXPERIMENTS.md`, one line per submission:

```
| # | time | commit | change (one thing) | score | keep? |
```

- Expect ±0.5 noise. Only revert if a change drops > 0.7; only trust a gain > 0.7 or one that repeats.
- Use all 4 slots per hour early, when the changes are big. Later, resubmit a promising commit once to confirm before stacking more on it.
- Never submit something that hasn't passed the sandboxed `check.py`.

## 6. Offline testing we can do without a sim

- **Tracking/lead accuracy:** in `stream.jsonl.gz`, predict each enemy's position 0.1–1 s ahead and compare with later observations.
- **Timing:** replay all 300 observations through `decide`, report p50/p99 ms.
- **Nav sanity:** unit-test A* between random walkable points on the real map; plot the path grid with matplotlib once to eyeball it (dev only, not in the image).
- **Physics checks:** small tests for intercept math, mortar pitch for a given range (v = 72, g = 22), cone/range checks for lightning.

## 7. First hour checklist

- [ ] Create the public GitHub repo, move kit `python/` files to `bot/`, Dockerfile at top (A)
- [ ] Commit `AGENTS.md` and `CLAUDE.md` pointing to PLAN.md (A)
- [ ] Stub modules with the interface in §2 (A)
- [x] `bench.py` + `replay_eval.py` (B)
- [ ] Sandboxed `check.py` passes on the Docker image (A)
- [ ] Submission #1 (either)

---

# Phase 5+: closing the gap (2.02 → top teams ~6.3)

## 5.0 Where we stand

| # | Build | Score |
|---|---|---|
| 1 | Kit example behaviour | 1.13 |
| 2 | Nav + zone hold + lead aiming | 1.52 |
| 4 | Single brain + Phase 3 | 1.88 |
| 5 | Phase 4 hardening (timing only) | 2.02 |

**What the score means.** In practice, house bots only die to us or the zone, so our score ≈ house bots dead before
we die. 2.02 means we lose around the 2nd or 3rd hunter. 6.3 means the top teams beat about 6, or outlast them.
The squad sends its weakest hunters first, one at a time, then more, then everyone late. So the gap is
(a) **winning early 1v1s quickly and cheaply**, then (b) **surviving the late swarm**.

**Why progress is slow.** Every change so far was a guess scored by one noisy number (±0.5, 4 per hour). We've never
seen our bot play. Fixing that comes first.

## 5.1 Get eyes on the bot (do first, ~1 h)

The play client (`play.joinbuilders.org`) contains a replay viewer:
- `?replay=<url>` loads any `.jsonl.gz` replay. Default: `replays/mechanics-v2-16.jsonl.gz`, a real 16-mech match (485 KB).
- `?debug=<url>&debugslot=<slot>` overlays a bot's debug drawings. **B** toggles bot debug.
- ← / → seek 10 s, **R** kill replays, **N** nameplates.

Steps:
1. **[Abdul, 5 min]** On the Mech Royale track page (signed in), look at a scored submission for per-match replay or
   debug downloads ("watch", "replay", "download"). If they exist, open one in the viewer with `?replay=` and `?debug=`.
   This is the single most valuable thing on this list.
2. **[A]** Make the debug drawings worth watching: label = `mode | target id | hp | weapon state | why`, a line to the
   current goal, cover points, the predicted lead point. Cheap, and the viewer shows them.
3. **[A]** `tools/replay_stats.py`: parse a replay and print per-mech time alive, damage dealt and taken, shots vs hits,
   engagement ranges, time spent moving/boosting, where they died. Run it on the sample replay first, to learn how
   real bots (house bots included) fight: ranges, strafing, cover, weapons.
4. Watch 5 of our losses. Write each cause of death in `EXPERIMENTS.md` under "Deaths observed".
   Everything below is then ranked by what we actually see, not by guesses.

If the track page has no replays, use the sample replay for (3), and the duel harness (5.2) becomes our eyes.

## 5.2 Duel harness (A, ~half a day; only if 5.1 gives no replays of our own bot)

A local 1v1 simulator, not a full game: our real `Brain` vs a scripted hunter on the real map.
- Physics: accel toward commanded velocity, walls and step-up from `world`/`nav`, gravity/jump/jet, turn rate.
- Weapons: gun (projectile, spread, mag/reload) and laser (charge/hitscan). Rear ×1.5. Regen after 5 s.
- Vision: our `world.los` + FOV/near range + 5 s memory, producing real `obs` dicts.
- Hunter: walks at us on A*, strafes, leads its shots, at three accuracy levels (easy/hard/expert stand-ins).
- Output per duel: who won, time to kill, HP left, our hit rate. `tools/duel.py --n 200` gives a stable number in minutes.
- Calibrate hunter accuracy and movement against the sample replay's stats, so wins here mean something on the server.

This turns "one noisy number per 15 min" into "200 duels per minute", which is the only way to reach 6+.

## 5.3 Hypotheses, ranked, with the test for each

| # | Hypothesis | Owner | Test |
|---|---|---|---|
| H1 | **We miss a lot or hold fire** (tight aim gate, torso slew, target strafing) | B | hit rate in harness/replay; queued config A |
| H2 | **We retreat out of winnable duels** and take free shots while running | A | harness win rate vs `COVER_LOW_HP`; queued config B |
| H3 | **We fight with the starting gun only.** A charged laser does 315 damage; 40 floor weapons, ⅓ lasers | B + A | route to the nearest laser/mortar before the first hunter arrives; harness gun-only vs gun+laser |
| H4 | **Too few cubes.** Each cube is +4% HP/damage (cap 10); 12 drones × 2 cubes; crates 1 each | A | queued config C; harness with 0 vs 5 cubes |
| H5 | **We're easy to find.** Boosting/walking > 5 m/s makes steps audible up to 90 m | A | walk at < 5 m/s when holding; boost only for zone/retreat |
| H6 | **The late swarm overruns us in the open** | A | hold a covered anchor with one approach; or a **rooftop** (100 energy ≈ 60 m of climb; hunters must jet up one at a time). Needs jet navigation |
| H7 | **Wrong upgrades.** Survival first may be wrong for duels | B | harness: armor vs gun_rate/gun_damage first |
| H8 | **We fight at bad ranges** | B | from replay stats: the range where top bots win; hold it |

## 5.4 Split of work (same ownership as before)

**A (Claude Code):** debug drawings, `replay_stats.py`, duel harness, H2 / H4 / H5 / H6 (movement, cover,
roof/jet nav, late anchor), weapon-pickup routing for H3.
**B (Codex):** H1 (aim gate, lead, spread, slew-aware firing), H3 (laser charge timing in duels, swap policy), H7 (upgrades),
H8 (range control), plus tests in the harness for each.

Interfaces stay as they are: `combat.Weapons.decide/dodge`, `nav.*`, `brain.decide`. A new behaviour goes behind a
flag in `config.py`, defaulted off until it wins in the harness *and* on the server.

## 5.5 Submission discipline from here

- Keep running the queued config sweeps A–D (`EXPERIMENTS.md`) now; they cost nothing to build.
- After that, a change is submitted only if it wins clearly in the harness (or is a fix seen in replays).
- One flag per submission. Re-submit the current best every ~4 submissions so drift shows.
- Required before every PR, unchanged: `bench.py` (0 errors), `test_brain_fuzz.py`, `test_hardening.py`, `check.py`.

## 5.6 The final is not practice

The final is a 16-team free-for-all: bots fight each other, as in the video (5 dead by 1:04, 10 by 1:40). There, kills
matter less and survival more. The harness can run FFA-like scenes (2–3 hunters that also target each other) to tune
`MODE = "ffa"`. Lock for the final whichever commit is best on practice, unless the FFA build is close on practice and
clearly better in the harness's FFA scenes.

## 5.7 Status after building the duel simulator

- Track page has no replay downloads, so `tools/sim.py` + `tools/duel.py` are our eyes. `tools/replay_stats.py` reads both
  real replays and `--record` output.
- Found and fixed (config): RECOVER mode was losing nearly every duel (bot walked away with its trigger off while the
  hunter followed). New defaults beat hard hunters 82% of the time (was 0%), expert 34% (was 0%).
- **Next, biggest gain: H3, get a laser early.** With a laser we win 100% vs gun-only hard/expert hunters. Every house
  bot that lasted took a 2nd weapon within 10 s. Plan: from spawn, scan for pickups (turn the torso, since pickups show
  only while seen) and route to the nearest laser > lightning > mortar before the first hunter arrives. [A routes, B fires]
- Then: two-hunter fights (0% wins, 15% of damage from behind): keep both in front, back toward cover so they
  can't flank. [A]
- Sim fidelity work [B]: hunters that pick up weapons and use the laser, so "both have lasers" is the normal case.

### Defensive movement experiment

The browser recording shows the risk of staying exposed on approach. For scored bots, gun rounds travel
straight and mortar shells fall under gravity. The torso slews before it reaches commanded aim.
`DEFENSIVE_EVASION` is off by default for an isolated comparison with the reported 2.31 build.
When enabled, two nearby opponents can trigger a withdrawal. During withdrawal the bot compares
short movement paths for projectile contact, cover, enemy aim, recent shot bearings, and zone safety.
Between contacts it scans either side of its travel direction. Evaluate it against matched two-hunter
seeds before spending a practice submission.

First comparison (10 matched hard two-hunter seeds): both variants won 3/10. Hunter hit
rate fell from 48% to 42%, while rear hits rose from 19% to 24% of damage taken. Leave the
flag off pending a clearer win and better flank coverage.
