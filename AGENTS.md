# Agent notes

- Read `PLAN.md` first (strategy, module ownership, phases). Full game rules: `protocol.md`.
- Bot code is in `bot/` (entry `bot/main.py`); `Dockerfile` at the top builds it.
- Tunables go in `bot/config.py`, never inline.
- Before any PR, both must pass:
  - `python tools/bench.py`
  - `python mechfight-kit/mechfight-kit/check/check.py -- python -u bot/main.py`
- Log every practice submission in `EXPERIMENTS.md`.
