"""Every tunable number lives here. Change one per submission and log it in EXPERIMENTS.md."""

NAME = "rps-mech"
MODE = "farm"  # "farm" for practice (kill house bots 1v1), "ffa" for the final (survive)

# Timing
TICK_SOFT_LIMIT_MS = 35.0  # past this, main.py returns the last safe action

# Behaviour (Phase 0: same as the kit example)
JUMP_EVERY_TICKS = 40
AIM_Z_OFFSET = 2.5  # aim this far above target feet

# Upgrade preference, best first. Unknown ids rank after these.
UPGRADE_PRIORITY = ["armor", "hp", "gun_rate", "laser_damage", "lightning_damage", "mortar_damage", "sensors"]
