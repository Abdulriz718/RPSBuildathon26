# Submission log

Noise is about ±0.5. Trust a change only if it moves the score by more than 0.7, or repeats.

| # | time | commit | change (one thing) | score | keep? |
|---|------|--------|--------------------|-------|-------|
| 1 | Phase 0 | main @ Phase 0 merge | Kit example behaviour in our module layout (baseline) | 1.13 | yes (= kit 1.15 within noise) |
| 2 | Phase 1 | main @ a1d4ea6 | Phase 1: nav + zone hold (A), lead aiming + LOS-gated fire + threat bearing (B) | 1.52 | yes (+0.37, borderline vs noise) |
| 3 | Phase 2 | main @ 9444dad | Phase 2 A + B merged | 0.17 | NO: merge left two cover_goal/cover_from defs and two decide bodies; decide() threw on 251/300 replay ticks, so the bot mostly didn't shoot. bench.py showed it (753 errors) but wasn't run |
| 4 | | | Fix: single brain (A modes + B Weapons/dodge/cover_pair), Phase 3 flags OFF (DROPS, LATE_ZONE, ENDGAME = False) | | |
| 5 | | | Same as #4 with Phase 3 flags ON (drops, deeper late-zone hold, safer endgame) | | |
