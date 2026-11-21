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
UPGRADE_PRIORITY = (
    "armor", "plating", "gun_damage", "gun_rate", "gun_mag", "gun_velocity",
    "laser_damage", "laser_charge", "laser_pierce", "mortar_reload", "mortar_splash",
    "mortar_velocity", "lightning_range", "lightning_efficiency", "lightning_chain",
    "sensors", "nanites", "servos", "reactor", "jets", "capacitor", "gyros",
)
COUNTERS = {"laser": "mortar", "mortar": "lightning", "lightning": "laser"}
COUNTER_BONUS = 1.35
COUNTER_PENALTY = 0.7
LASER_LEAD_S = 0.05
LASER_MAX_VERTICAL_SPEED = 7.0
MORTAR_MAX_TRACK_AGE_S = 0.6
MORTAR_MOVING_FLIGHT_S = 2.5
MORTAR_STATIONARY_SPEED = 1.0
MORTAR_SOLVE_PASSES = 5
MORTAR_SEGMENT_M = 8.0
MORTAR_PATH_TOLERANCE_M = 1.0
DODGE_LOOKAHEAD_S = 0.5
DODGE_BUFFER_M = 0.75
DODGE_STEP_M = 3.0
STRAFE_SPEED_FRACTION = 0.55
COVER_RADII_M = (3, 6, 9, 12)
COVER_SEARCH_INTERVAL_S = 0.8
COVER_TARGET_MOVE_M = 6.0
COVER_LOW_HP = 0.55
COVER_RECOVER_HP = 0.8
COVER_REACHED_M = 1.2
LOOT_WINDOW_S = 60.0
LOOT_CRATE_RANGE_M = 50.0
LOOT_VERTICAL_REACH_M = 4.0
LOOT_ZONE_MARGIN_M = 3.0
LOOT_PICKUP_BONUS_M = 16.0

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
