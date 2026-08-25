"""GliderState — the evolving physical state of a flight.

The dynamical state is just four numbers (s, h, vs, vh) — a direct consequence
of the point-mass-in-a-vertical-plane model. `bearing` is carried alongside so
the 2D flight can be projected onto lat/lon; `t` and `landed` track progress.
"""

import math

from glider_params import GliderParams


class GliderState:
    """State in the vertical plane, plus bearing for lat/lon projection."""
    def __init__(self, params: GliderParams, bearing_rad: float):
        ang = math.radians(params.launch_angle_deg)
        self.s = 0.0                                   # downrange distance (m)
        self.h = params.launch_alt                     # altitude (m)
        self.vs = params.launch_speed * math.cos(ang)  # downrange velocity
        self.vh = params.launch_speed * math.sin(ang)  # vertical velocity
        self.t = 0.0                                    # elapsed sim time (s)
        self.bearing = bearing_rad                      # compass dir of travel
        self.landed = False