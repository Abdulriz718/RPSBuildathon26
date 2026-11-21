"""Every tunable number lives here. Change one per submission and log it in EXPERIMENTS.md."""

NAME = "rps-mech"
MODE = "farm"  # "farm" for practice (kill house bots 1v1), "ffa" for the final (survive)

# Timing
TICK_SOFT_LIMIT_MS = 35.0  # past this, main.py returns the last safe action

# Tracking and arm gun
TRACK_VELOCITY_GAP_S = 0.35      # largest gap for a position-based velocity estimate
TRACK_AIM_MEMORY_S = 0.75        # keep facing a lost track briefly
TRACK_SOUND_LOOK_S = 0.75        # look toward a nearby shot when no threat is tracked
TRACK_SHOT_SOUNDS = frozenset({"gun", "mortar", "laser", "laser_charge", "lightning"})
GUN_AIM_FRACTION = 0.8          # stay inside this fraction of the target's hit radius

# Upgrade preference, best first. Unknown ids rank after these.
UPGRADE_PRIORITY = ["armor", "hp", "gun_rate", "laser_damage", "lightning_damage", "mortar_damage", "sensors"]

# Navigation (nav.py)
NAV_CELL = 3.0            # m per coarse nav cell
NAV_MAX_UP = 1.8          # max rise between neighbouring nav cells (m)
NAV_DROP = 2.0            # stepping into a wall-adjacent cell is fine if it's this much lower (dropping off)
NAV_BUDGET_MS = 8.0       # A* time per tick
NAV_MAX_EXPAND = 60000    # give up and use the closest node after this many expansions
NAV_HEURISTIC_W = 1.3     # >1 = weighted A*: far fewer expansions, paths a few % longer
NAV_REPLAN_S = 2.0        # replan at least this often
NAV_REPLAN_GOAL_MOVE = 10.0  # replan when the goal moves this far
NAV_LOOKAHEAD = 2         # steer at the waypoint this many cells ahead
STUCK_S = 1.0             # window for stuck detection
STUCK_DIST = 1.5          # moved less than this in STUCK_S while commanding a move = stuck
UNSTICK_S = 0.6           # sidestep + jump + jet for this long

# Zone (brain.py)
ZONE_MARGIN = 0.75        # aim for a point at this fraction of the next radius from its center
ZONE_SAFETY_S = 8.0       # boost if reaching the safe circle would take longer than time left minus this
HURT_LOOK_S = 3.0         # after taking damage, look toward its bearing this long
SCAN_RAD_PER_TICK = 0.35  # sweep speed when standing with nobody in sight (turn rate is ~4 rad/s)

# Phase 2: fight / retreat / heal (brain.py)
COVER_RINGS = (6, 10, 15, 21, 28, 36)  # m, candidate cover distances tried nearest first
COVER_ANGLES = 16
COVER_CACHE_S = 1.0       # reuse a cover point this long
RETREAT_HP = 0.40         # break off and take cover below this fraction of max HP
HEAL_TO_HP = 0.85         # stay in cover until healed to this fraction
RETREAT_ON_RELOAD_M = 60  # also duck out while reloading if the target is closer than this
STRAFE_S = 1.3            # flip strafe direction this often while fighting
STRAFE_PROBE_M = 5.0      # check walkability this far ahead before strafing
KEEP_OFF_LIGHTNING_M = 55 # back away from lightning carriers to this range (its range is 45)

# Phase 2: loot route (brain.py)
LOOT_UNTIL_S = 150        # actively route to loot before this match time
LOOT_RADIUS = 90          # only detour this far for loot
LOOT_ZONE_FRAC = 0.9      # loot must lie within this fraction of the next zone radius
CRATE_SHOOT_M = 60        # stop and shoot crates from this range
NPC_FARM_M = 70           # attack NPC drones closer than this when no mech is around
NPC_FARM_HP = 0.7         # ... and our HP is above this fraction
LOOT_FORGET_M = 20        # forget remembered loot when this close and it isn't listed
