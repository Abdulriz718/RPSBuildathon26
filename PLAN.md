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
