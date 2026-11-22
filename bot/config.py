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
GUN_AIM_FRACTION = 1.3          # stay inside this fraction of the target's hit radius

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
# Experimental defensive movement. Compare against the scored farm build.
DEFENSIVE_EVASION = False
DUEL_EVASION = False  # experimental 1v1 projectile evasion, including jet bursts
DUEL_EVADE_ANGLES = (0, 45, -45, 90, -90, 135, -135, 180)
DUEL_JET_RESERVE = 25.0
DUEL_JET_COST = 0.45
DUEL_JUMP_COST = 0.15
DUEL_TURN_COST = 0.75
EVADE_HORIZON_S = 0.5
EVADE_STEPS = 5
EVADE_TURNS_DEG = (0, -35, 35, -70, 70, -105, 105)
EVADE_MAX_PROJECTILES = 16
EVADE_MAX_THREATS = 3
EVADE_THREAT_RANGE_M = 120.0
EVADE_MULTI_RANGE_M = 65.0
EVADE_CONTACT_WEIGHT = 12.0
EVADE_AIM_WEIGHT = 3.0
EVADE_COVER_WEIGHT = 2.0
EVADE_SOUND_WEIGHT = 1.5
EVADE_ENEMY_WEIGHT = 3.0
EVADE_SCAN_PERIOD_S = 2.0
EVADE_SCAN_ANGLE_DEG = 55
STRAFE_SPEED_FRACTION = 0.55
COVER_RADII_M = (3, 6, 9, 12)
COVER_SEARCH_INTERVAL_S = 0.8
COVER_TARGET_MOVE_M = 6.0
COVER_LOW_HP = 0.0   # sim: retreating while chased loses duels (hard: 0% -> 43% win at 0.0)
COVER_RECOVER_HP = 0.8
COVER_REACHED_M = 1.2
COVER_PAIR_BUDGET_MS = 4.0   # cover_pair search gives up after this
LOOT_WINDOW_S = 60.0
LOOT_CRATE_RANGE_M = 50.0
LOOT_VERTICAL_REACH_M = 4.0
LOOT_ZONE_MARGIN_M = 3.0
LOOT_PICKUP_BONUS_M = 16.0

# Navigation (nav.py)
NAV_CELL = 3.0            # m per coarse nav cell
NAV_MAX_UP = 1.8          # max rise between neighbouring nav cells (m)
NAV_DROP = 2.0            # stepping into a wall-adjacent cell is fine if it's this much lower (dropping off)
NAV_BUDGET_MS = 4.0       # A* time per tick (plans still finish in a few ticks)
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

# Phase 3 (brain.py). Each flag can be switched off on its own to test it.
DROPS = True              # go capture supply drops
DROP_MAX_M = 160          # ignore drops farther than this
DROP_EARLY_S = 4.0        # arrive at most this long before it lands (don't wait in the open)
DROP_CLEAR_M = 45         # skip a drop if a mech was seen this close to it in the last 2 s
DROP_STAND_M = 2.5        # close enough to the drop center to stand still
DROP_TRACK_S = 2.0
DROP_ZONE_BUFFER_M = 2.0
LATE_ZONE = True          # hold deeper inside small circles
LATE_ZONE_RADIUS = 200    # next radius below which ZONE_MARGIN_LATE applies
ZONE_MARGIN_LATE = 0.4
LATE_ANCHOR_MAX_OFFSET_M = 24.0
LATE_ANCHOR_REFRESH_S = 2.0
LATE_ANCHOR_HEIGHT_WEIGHT = 0.5
LATE_ANCHOR_CENTER_WEIGHT = 0.4
LATE_ANCHOR_COVER_BONUS_M = 12.0
LATE_ANCHOR_SOUND_DISTANCE_M = 55.0
LATE_ANCHOR_SOUND_AGE_S = 2.0
LATE_ANCHOR_AWAY_WEIGHT = 0.3
LATE_TINY_RADIUS_M = 5.0
LATE_TINY_REACH_M = 0.5
ENDGAME = True            # play safer late: earlier retreat, no looting
ENDGAME_ALIVE = 5         # endgame when this few mechs are alive...
ENDGAME_T = 360           # ...or after this match time (s)
ENDGAME_LOW_HP = 0.0      # retreat threshold in the endgame (normal: COVER_LOW_HP)

# FFA mode (final). MODE = "ffa" fights only attackers or weak lone targets, avoids the rest.
FFA_GRUDGE_S = 6.0        # fight back against anyone who hit us this recently
FFA_FINISH_HP = 450       # ...or a lone visible mech below this HP
FFA_FINISH_M = 90         # ...within this range
# Switch farm -> ffa mid-match when mechs die that we never hit. Practice house bots only die to us,
# so (deaths seen) - (our kill events) >= AUTO_FFA_DEATHS means a real free-for-all.
AUTO_FFA = True       # practice sim: fires 2/144, -0.01; FFA sim: fires 109/120 by t=18 s
AUTO_FFA_DEATHS = 2
AUTO_FFA_MAX_T = 200.0    # stop checking later: zone deaths start to muddy the count

# Heal between kills (brain.py HEAL mode): when hurt between fights, break line of sight and
# hold fire (dealing damage also resets the regen timer) until healed. Taking damage ends it: we fight back.
HEAL_BETWEEN = False  # server 3.27 (#11), within noise of 3.40; off while crates are tested alone
HEAL_START = 0.70          # start below this HP fraction...
HEAL_DONE = 0.95           # ...and keep healing until this
HEAL_CALM_S = 3.0          # start only after this long with no hits either way and no mech in sight

# Crate hunting for a laser (brain.py CRATE mode): crates drop a weapon half the time, and a laser is our biggest
# lever. While we hold no laser and nobody is in sight close by, go break the nearest remembered ground crate;
# WEAPON mode then picks up what falls out.
CRATE_HUNT = False    # server 3.15 (#12), within noise of 3.40
CRATE_HUNT_UNTIL_S = 240   # match time
CRATE_HUNT_M = 200         # walk this far for a crate
CRATE_FIGHT_M = 100        # a visible mech closer than this takes priority
CRATE_CALM_S = 2.0         # ...as does anything that hit us this recently

# Early weapon grab (brain.py WEAPON mode). Sim: a laser turns 34% into 100% vs expert hunters.
WEAPON_GRAB = True
WEAPON_RANK = {"mortar": 1, "lightning": 2, "laser": 3}   # swap up only to a higher rank
WEAPON_BONUS = {"laser": 70, "lightning": 30, "mortar": 0}  # metres of detour each kind is worth
WEAPON_MAX_M = 150         # fetch a first weapon up to this far
WEAPON_SWAP_M = 45         # swap to a better weapon only this close
WEAPON_FIGHT_M = 80        # with a visible mech closer than this...
WEAPON_GRAB_IN_FIGHT_M = 20  # ...only fetch weapons within this
SWEEP_FOR_WEAPONS = True   # turn the torso while walking until we hold a 2nd weapon
SWEEP_UNTIL_LASER = False  # keep sweeping until we hold a laser (not just any 2nd weapon); off = 3.40 behaviour

# Survival gameplans (brain.py). Off until they win in tools/ffa.py and tools/duel.py.
AVOID_FIGHT_SOUNDS = False  # hold away from fights we hear/see that aren't aimed at us
DANGER_SOUNDS = frozenset({"gun", "mortar", "explosion", "laser", "laser_charge", "lightning"})
DANGER_SOUND_DISTS = ("near", "mid")   # "near" < 60 m, "mid" < 160 m
DANGER_MEMORY_S = 6.0
DANGER_STEP_M = 40         # hold this far from where we are, away from the fights
DANGER_ZONE_FRAC = 0.85    # ...but inside this fraction of the next circle
MULTI_DISENGAGE = False    # back off to cover when 2+ attackers are on us
MULTI_FINISH_HP = 400      # ...unless our target is this close to dead

# Roof climbing (nav.py roof_step): reach weapons on roofs (a quarter of floor loot).
ROOF_CLIMB = True
ROOF_COST_M = 25           # a roof weapon counts as this much further away
ROOF_MAX_CLIMB_M = 50      # tallest wall we try (100 energy ~ 60 m)
ROOF_REGION_MAX = 4000     # cells searched per roof
ROOF_BASE_REACH_M = 4.0    # start the climb this close to the climb point
ROOF_ENERGY_SPARE = 15     # energy to keep beyond the climb itself
ROOF_REPLAN_S = 5.0

# Cube collection (brain.py CUBES mode). Each cube: +4% max HP and damage (cap 10); kills drop victim cubes + 2.
CUBE_COLLECT = False   # added after 3.40, was on in #9-#12; practice sim: no gain
CUBE_MAX_M = 50            # walk this far for a cube when nobody is close
CUBE_SAFE_M = 60           # "nobody close" = our target is farther than this
CUBE_FIGHT_M = 12          # mid-fight, still grab cubes this close

# Fire the gun together with lightning/laser, and only lob mortars when the gun can't hit (combat.py)
COMBINED_FIRE = False  # added after 3.40, was on in #9-#12; practice sim: -0.01

# Abdul's requests (not sim-tested by request):
# 1. under fire: zig-zag across the attacker's line and hop with short jet bursts
ZIGZAG_UNDER_FIRE = False  # scored 2.75 on the server together with AVOID_PEOPLE/MULTI_DISENGAGE/laser-only
ZIGZAG_HURT_S = 1.5        # "under fire" = hit within this long, or a shot about to land
ZIGZAG_S = 0.45            # flip direction this often
ZIGZAG_KEEP = 0.5          # how much of the mode's own movement to keep while weaving
ZIGZAG_HOP_EVERY_S = 1.2   # jump this often while under fire...
ZIGZAG_HOP_ENERGY = 35     # ...if energy is at least this
ZIGZAG_JET_S = 0.35        # jet this long after each jump
# 2. stay away from people: hold away from mechs seen recently; don't start fights with far mechs
AVOID_PEOPLE = False
AVOID_PEOPLE_M = 200       # mechs within this count as people to keep away from
AVOID_ENGAGE_M = 90        # don't start a fight with a mech farther than this...
AVOID_PROVOKED_S = 4.0     # ...unless it hit us this recently
# 3. laser search: while we have no laser, roam the safe circle scanning for one
LASER_ROAM = False
LASER_ROAM_UNTIL_S = 240
LASER_ROAM_S = 12          # pick a new waypoint this often
LASER_ROAM_STEP_M = 70     # waypoint distance

# Play styles (brain.py style_fight / HOLD). "default" = cover peek and strafe at whatever range.
STYLE = "default"          # "default", "kite", "rush", "roof", "assassin". kite: sim +0.35 but server 3.10 (sim had no trees)
KITE_MIN_M = 120           # kite: back off (with boost) when a target is closer than this...
KITE_MAX_M = 170           # ...and close in when farther than this
KITE_BOOST_ENERGY = 20
RUSH_RANGE_M = 25          # rush: close to this range
RUSH_BOOST_ENERGY = 30
ROOF_STYLE_UNTIL_S = 330   # roof: climb onto a roof and hold it until this match time
ROOF_STYLE_MIN_H = 8       # roofs at least this tall
ROOF_STYLE_SEARCH_M = 160
ROOF_STYLE_FIGHT_M = 45    # stop climbing to fight anyone closer than this
ROOF_STYLE_CACHE_S = 10
ASSASSIN_HP = 0.8          # assassin: go looking for fights while HP is above this fraction
ASSASSIN_UNTIL_S = 360
ASSASSIN_SOUND_S = 4.0

# Shot selection vs dodgers (combat.engage): skip gun shots whose flight is longer than this at grounded targets
# (vertical speed under FIRE_AIRBORNE_VZ). In the air a mech can barely change course (air_accel 12 vs 58.5).
FIRE_MAX_FLIGHT_S = None   # e.g. 0.3 (~75 m); None = always fire
FIRE_AIRBORNE_VZ = 1.0
