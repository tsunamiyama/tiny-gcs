"""Phase 2 glider dynamics — a point-mass paper-plane model.

Unpowered point-mass (3-DOF) glider: gravity, lift, and drag act on a mass and
we integrate to get the trajectory. No thrust — the plane trades altitude for
distance, so the headline emergent quantity is the glide ratio (L/D).

KEY MODELLING CHOICE: a straight glide lives entirely in the VERTICAL PLANE that
contains the launch heading. So we integrate the dynamics in 2D (downrange s,
altitude h) where the lift/drag geometry is simple and robust, then project the
downrange distance onto the compass bearing toward the target to get lat/lon.
This deliberately avoids a fragile 3D lift-vector construction. Turning flight
would need the full 3D treatment; straight-line feasibility does not.

MODULE LAYOUT: this file holds the dynamics (_derivatives, step), geography,
telemetry, and the flight/playback drivers (fly, summarize, prepare_playback).
Supporting pieces live alongside it: constants.py (shared physical constants),
atmosphere.py (ISA density + gravity), params.py (GliderParams), state.py
(GliderState). They are imported below.

ATMOSPHERE: air density comes from a layered International Standard Atmosphere
model (atmosphere.density), so a launch from Everest glides differently than one
from a rooftop — thinner air, less lift and drag. Gravity varies with altitude
too (weakly). Both are looked up from the current altitude each timestep.

ALTITUDE ASSUMPTION (deliberate): altitude is modelled as height above a flat
ground plane, and gravity always points "down" in the integration plane. Earth
curvature is applied to ground DISTANCE (great-circle) but not to the vertical
dynamics. This is valid because a glider's vertical extent is negligible against
its ground track. It would break for near-space launches (100 km), where the
vertical scale becomes comparable to earth curvature — those need a spherical/
polar reformulation and are out of scope for this base model.

REAL (computed): position, velocity, altitude, sink rate, glide ratio, ranges.
DERIVED (kinematics, not rigid-body sim): pitch = flight-path angle, yaw = bearing.
NOT modelled: rigid-body rotation, control surfaces, sensors, banked turns.

Units: SI (m, m/s, kg, N). Local frame: x=east, y=north, z=up.
"""

import math

from constants import R_EARTH
from atmosphere import density, gravity
from glider_params import GliderParams
from glider_state import GliderState


def _derivatives(s, h, vs, vh, params, headwind):
    """The equations of motion as a pure function.

    Given a state (downrange s, altitude h, downrange velocity vs, vertical
    velocity vh), return the time-derivatives of each: [ds/dt, dh/dt, dvs/dt,
    dvh/dt]. Position derivatives are just the velocities; velocity derivatives
    are the accelerations (force / mass).

    This is pure — it reads no external state and mutates nothing — which is
    exactly what RK4 needs, since RK4 evaluates it at several trial states per
    step without committing to any of them.
    """
    # airspeed along-path includes headwind; vertical air motion ignored (calm)
    air_vs = vs + headwind
    speed = math.hypot(air_vs, vh)
    if speed < 1e-3:
        speed = 1e-3

    # density and gravity depend on the altitude at THIS trial state
    rho = density(h)
    g = gravity(h)

    qS = 0.5 * rho * speed * speed * params.wing_area
    lift = qS * params.cl
    drag = qS * params.cd

    gamma = math.atan2(vh, air_vs)   # flight-path angle of the airflow
    # drag opposes velocity: (-cos g, -sin g); lift perpendicular: (-sin g, cos g)
    f_s = -drag * math.cos(gamma) - lift * math.sin(gamma)
    f_h = -drag * math.sin(gamma) + lift * math.cos(gamma) - params.mass * g

    return (vs, vh, f_s / params.mass, f_h / params.mass)


def step(state, params, headwind=0.0, dt=0.02):
    """Advance one timestep with fourth-order Runge-Kutta (RK4).

    RK4 samples the dynamics at four points across the step — the start (k1),
    two midpoint estimates (k2, k3), and an endpoint estimate (k4) — then takes
    a weighted average. This tracks how the forces change across the step, so it
    stays accurate and stable at far larger dt than Euler, which assumes constant
    force. That is what lets one dt serve both a 20-second toss and a multi-hour
    high-altitude glide without blowing up.
    """
    if state.landed:
        return

    s, h, vs, vh = state.s, state.h, state.vs, state.vh

    # k1: derivatives at the current state
    k1 = _derivatives(s, h, vs, vh, params, headwind)
    # k2: derivatives at the midpoint, stepped half-dt along k1
    k2 = _derivatives(s + 0.5*dt*k1[0], h + 0.5*dt*k1[1],
                      vs + 0.5*dt*k1[2], vh + 0.5*dt*k1[3], params, headwind)
    # k3: derivatives at the midpoint, stepped half-dt along k2
    k3 = _derivatives(s + 0.5*dt*k2[0], h + 0.5*dt*k2[1],
                      vs + 0.5*dt*k2[2], vh + 0.5*dt*k2[3], params, headwind)
    # k4: derivatives at the endpoint, stepped full-dt along k3
    k4 = _derivatives(s + dt*k3[0], h + dt*k3[1],
                      vs + dt*k3[2], vh + dt*k3[3], params, headwind)

    # weighted average: (k1 + 2*k2 + 2*k3 + k4) / 6, applied over dt
    state.s  += dt/6.0 * (k1[0] + 2*k2[0] + 2*k3[0] + k4[0])
    state.h  += dt/6.0 * (k1[1] + 2*k2[1] + 2*k3[1] + k4[1])
    state.vs += dt/6.0 * (k1[2] + 2*k2[2] + 2*k3[2] + k4[2])
    state.vh += dt/6.0 * (k1[3] + 2*k2[3] + 2*k3[3] + k4[3])
    state.t += dt

    if state.h <= 0.0:
        state.h = 0.0
        state.landed = True


# ---- geography: great-circle distance and along-track projection ----
#
# We use proper spherical geometry for the GROUND path so distances are correct
# at any scale (paper-plane meters up to continental spans) and the map track
# curves realistically. The flight DYNAMICS stay flat (vertical plane); only the
# ground mapping is spherical. See the ALTITUDE ASSUMPTION note in the docstring.

def _haversine(start_latlon, end_latlon):
    """Great-circle distance (m) and initial bearing (rad) start->end."""
    lat1, lon1 = math.radians(start_latlon[0]), math.radians(start_latlon[1])
    lat2, lon2 = math.radians(end_latlon[0]), math.radians(end_latlon[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    dist = 2 * R_EARTH * math.asin(math.sqrt(a))
    # initial bearing along the great circle
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1)*math.sin(lat2) - math.sin(lat1)*math.cos(lat2)*math.cos(dlon)
    bearing = math.atan2(y, x)
    return dist, bearing


def _local_target(start_latlon, end_latlon):
    """Return (great-circle distance m, initial bearing rad)."""
    return _haversine(start_latlon, end_latlon)


def _project_latlon(start_latlon, bearing, downrange):
    """Point at `downrange` meters from start along the great circle at `bearing`.
    Standard 'destination given distance and bearing' spherical formula."""
    lat1, lon1 = math.radians(start_latlon[0]), math.radians(start_latlon[1])
    ad = downrange / R_EARTH   # angular distance
    lat2 = math.asin(math.sin(lat1)*math.cos(ad) +
                     math.cos(lat1)*math.sin(ad)*math.cos(bearing))
    lon2 = lon1 + math.atan2(math.sin(bearing)*math.sin(ad)*math.cos(lat1),
                             math.cos(ad) - math.sin(lat1)*math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)


def emit_telemetry(state, params, start_latlon, target_dist):
    """Telemetry in the existing contract shape."""
    ground_speed = state.vs
    sink_rate = -state.vh                 # positive = descending
    inst_glide = (ground_speed / sink_rate) if sink_rate > 1e-3 else None
    pitch = math.degrees(math.atan2(state.vh, state.vs)) if abs(state.vs) > 1e-3 else 0.0
    lat, lon = _project_latlon(start_latlon, state.bearing, state.s)

    return {
        "timestamp": state.t,
        "position": {
            "lat": lat, "lon": lon,
            "alt_rel_m": state.h,
            "downrange_m": state.s,
            "groundspeed_m_s": ground_speed,
            "vspeed_m_s": state.vh,
            "heading_deg": math.degrees(state.bearing) % 360,
        },
        "attitude": {          # DERIVED, not simulated rigid-body attitude
            "roll_deg": 0.0,
            "pitch_deg": pitch,
            "yaw_deg": math.degrees(state.bearing) % 360,
        },
        "glide": {
            "sink_rate_m_s": sink_rate,
            "instant_glide_ratio": inst_glide,
            "design_glide_ratio": params.glide_ratio,
            "air_density": density(state.h),
        },
        "mission": {
            "dist_to_target_m": max(0.0, target_dist - state.s),
            "downrange_m": state.s,
            "elapsed_s": state.t,
        },
        "status": {
            "phase": "landed" if state.landed else "gliding",
        },
    }


def fly(params, start_latlon, end_latlon, headwind=0.0, dt=None, max_time=None):
    """Run a full flight, yielding telemetry each timestep until landing.

    TIMESTEP: if dt is None (the default), an ADAPTIVE step is used — small
    during the launch transient (where forces are large and a coarse step would
    go unstable) and large once the flight settles into steady glide (where big
    steps are safe and keep long high-altitude flights fast). Pass an explicit
    dt to force a fixed step (mainly for testing/convergence checks).

    RK4 makes the large steady-glide steps stable; on a cruder integrator the
    coarse phase would blow up. The two together are what let one call handle
    both a 20-second toss and a multi-hour Everest glide efficiently.

    max_time caps the simulated flight (seconds) as a runaway guard, scaled to
    launch altitude if None. It is not the expected length.
    """
    target_dist, bearing = _local_target(start_latlon, end_latlon)
    state = GliderState(params, bearing)

    if max_time is None:
        max_time = (params.launch_alt / 0.5) * 3.0 + 60.0

    adaptive = dt is None
    DT_FINE = 0.02      # transient / near-ground: stable under large forces
    DT_COARSE = 0.2     # steady glide: fast, still stable with RK4
    # Acceleration magnitude below which we consider the flight "settled".
    SETTLE_ACCEL = 0.5  # m/s^2

    elapsed = 0.0
    while not state.landed and elapsed < max_time:
        if adaptive:
            # Use the current acceleration magnitude to decide the step size:
            # large accel (launch transient, or dense low-altitude air) -> fine
            # step; small accel (steady glide) -> coarse step. Also stay fine
            # when close to the ground so we don't overshoot the landing.
            _, _, a_s, a_h = _derivatives(state.s, state.h, state.vs, state.vh,
                                          params, headwind)
            accel = math.hypot(a_s, a_h)
            near_ground = state.h < 50.0
            dt_use = DT_FINE if (accel > SETTLE_ACCEL or near_ground) else DT_COARSE
        else:
            dt_use = dt

        step(state, params, headwind, dt_use)
        elapsed = state.t
        yield emit_telemetry(state, params, start_latlon, target_dist)


def summarize(params, start_latlon, end_latlon, headwind=0.0):
    """Run to completion; return the feasibility outcome."""
    target_dist, _ = _local_target(start_latlon, end_latlon)
    last = None
    for tele in fly(params, start_latlon, end_latlon, headwind):
        last = tele
    if last is None:
        raise ValueError("flight produced no frames")

    reached = last["position"]["downrange_m"] >= target_dist - 5.0
    return {
        "reached": reached,
        "target_distance_m": round(target_dist, 1),
        "distance_flown_m": round(last["position"]["downrange_m"], 1),
        "shortfall_m": round(max(0.0, target_dist - last["position"]["downrange_m"]), 1),
        "flight_time_s": round(last["timestamp"], 1),
        "design_glide_ratio": round(params.glide_ratio, 2),
    }


# ---------------------------------------------------------------------------
# Playback preparation
# ---------------------------------------------------------------------------
#
# A flight can take anywhere from seconds (a rooftop toss) to hours of SIMULATED
# time (an Everest glide). We never play it back 1:1 — instead we compute the
# whole flight fast, then produce a bounded set of frames that plays over a fixed
# wall-clock window:
#
#   playback_s = min(true_flight_time, MAX_PLAYBACK_S)   # 10s cap, real-time floor
#   speed      = true_flight_time / playback_s           # 1x for short flights
#
# So short flights play at real time (speed ~1x) and long flights are compressed
# to fit the window (Everest ~2700x). We downsample the trajectory to
# playback_s * FPS frames, evenly in simulated time, so the payload is small and
# bounded regardless of how long the flight actually was. A caller (e.g. a
# WebSocket endpoint) streams these frames, sleeping 1/FPS between them.

MAX_PLAYBACK_S = 10.0     # hard cap on wall-clock playback length
PLAYBACK_FPS = 30         # frames per wall-clock second of playback


def prepare_playback(params, start_latlon, end_latlon, headwind=0.0,
                     max_playback_s=MAX_PLAYBACK_S, fps=PLAYBACK_FPS):
    """Run the full flight, then return frames + metadata for animated playback.

    Returns a dict:
      {
        "meta": {
           "true_flight_time_s":  actual simulated flight duration,
           "playback_time_s":     wall-clock length of the animation (<= cap),
           "speed_factor":        true_time / playback_time (1.0 = real time),
           "frame_interval_s":    seconds to sleep between frames (1/fps),
           "frame_count":         number of frames,
           "reached":             did it reach the target,
           "target_distance_m", "distance_flown_m", "shortfall_m",
           "design_glide_ratio",
        },
        "frames": [ telemetry_dict, ... ]   # evenly sampled across the flight
      }

    The caller streams `frames` pacing at `frame_interval_s`; the whole animation
    lasts `playback_time_s` regardless of the true flight duration.
    """
    # 1. Compute the flight, sampling as we go. We must NOT accumulate every
    #    timestep — a high launch is millions of steps (Everest ~13M at dt=0.002)
    #    and would exhaust memory. Instead we do a lightweight first pass to get
    #    the true duration, then a second pass that keeps only sampled frames.
    #
    #    First pass: find the flight's true duration and step count cheaply by
    #    running the sim and counting, keeping only the last frame.
    target_dist, _ = _local_target(start_latlon, end_latlon)

    last = None
    total_steps = 0
    for tele in fly(params, start_latlon, end_latlon, headwind):
        last = tele
        total_steps += 1
    if last is None:
        raise ValueError("flight produced no frames")

    true_time = last["timestamp"]

    # 2. Playback timing: real-time below the cap, compressed above it.
    playback_s = min(true_time, max_playback_s) if true_time > 0 else max_playback_s
    playback_s = max(playback_s, 1.0 / fps)   # guard degenerate near-zero flight
    speed_factor = true_time / playback_s if playback_s > 0 else 1.0

    # 3. Second pass: re-run and keep every Nth frame so we end up with about
    #    frame_count frames, without ever holding the whole trajectory.
    frame_count = max(2, int(round(playback_s * fps)))
    stride = max(1, total_steps // frame_count)
    frames = []
    for i, tele in enumerate(fly(params, start_latlon, end_latlon, headwind)):
        if i % stride == 0:
            frames.append(tele)
    if frames[-1] is not last:
        frames.append(last)   # always include the landing frame

    reached = last["position"]["downrange_m"] >= target_dist - 5.0
    meta = {
        "true_flight_time_s": round(true_time, 1),
        "playback_time_s": round(playback_s, 3),
        "speed_factor": round(speed_factor, 1),
        "frame_interval_s": round(1.0 / fps, 4),
        "frame_count": len(frames),
        "reached": reached,
        "target_distance_m": round(target_dist, 1),
        "distance_flown_m": round(last["position"]["downrange_m"], 1),
        "shortfall_m": round(max(0.0, target_dist - last["position"]["downrange_m"]), 1),
        "design_glide_ratio": round(params.glide_ratio, 2),
    }
    return {"meta": meta, "frames": frames}