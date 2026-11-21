# Agent notes

- Read `PLAN.md` first (strategy, module ownership, phases). Full game rules: `protocol.md`.
- Bot code is in `bot/` (entry `bot/main.py`); `Dockerfile` at the top builds it.
- Tunables go in `bot/config.py`, never inline.
- Before any PR, both must pass:
  - `python tools/bench.py` (must say 0 decision errors)
  - `python tools/test_hardening.py` (sparse fields, full 8-minute match: time and memory)
  - `python tools/test_brain_fuzz.py` (drives every mode with faked drops, late game, FFA, all weapons)
  - `python mechfight-kit/mechfight-kit/check/check.py -- python -u bot/main.py`
- Log every practice submission in `EXPERIMENTS.md`.
- Before submitting a behaviour change, compare it in the duel simulator against the current defaults:
  `python tools/duel.py --n 80 --skill hard` and `--skill expert`, plus `--set KEY=VALUE` for config variants.
  Use `--hunters 2` for multi-attacker cases. A change should win clearly here before it costs a submission.
