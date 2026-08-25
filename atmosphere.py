"""International Standard Atmosphere (ISA) density model and gravity.

Self-contained: given an altitude, returns air density (kg/m^3) and gravitational
acceleration (m/s^2). Extracted from the glider dynamics so the atmosphere can be
developed and extended (e.g. for near-space launches) independently.

The atmosphere is divided into layers, each defined by a base altitude, the
temperature at that base, and a lapse rate (how fast temperature changes with
height in that layer). Temperature varies LINEARLY within a layer; pressure and
density are then computed from the physics, NOT interpolated directly (density
falls roughly exponentially, so linear interpolation of density would overestimate
air up high — exactly the regime that matters for tall launches).

The table covers 0–86 km (standard ISA). Above that an exponential tail is used,
since a paper plane there is effectively ballistic and only needs "almost no air"
to behave correctly. Values are the standard ISA constants.
"""

import math

from constants import GRAV_ACCEL, AIR_CONSTANT, R_EARTH

# Each layer: (base_altitude_m, base_temperature_K, lapse_rate_K_per_m)
_ISA_LAYERS = [
    (0.0,      288.15,  -0.0065),   # troposphere
    (11000.0,  216.65,   0.0),      # tropopause (isothermal)
    (20000.0,  216.65,   0.001),    # lower stratosphere
    (32000.0,  228.65,   0.0028),   # upper stratosphere
    (47000.0,  270.65,   0.0),      # stratopause (isothermal)
    (51000.0,  270.65,  -0.0028),   # lower mesosphere
    (71000.0,  214.65,  -0.002),    # upper mesosphere
    (84852.0,  186.87,   0.0),      # ~mesopause; top of standard table
]

_P0 = 101325.0         # Pa, sea-level standard pressure


def _build_layer_base_pressures():
    """Precompute pressure at each layer's base by integrating up the layers.

    Derived from the layer table (not hardcoded) so the pressures stay consistent
    with the layers automatically if the table is ever edited.
    """
    pressures = [_P0]
    for i in range(1, len(_ISA_LAYERS)):
        base_alt, base_T, _ = _ISA_LAYERS[i - 1]
        top_alt = _ISA_LAYERS[i][0]
        lapse = _ISA_LAYERS[i - 1][2]
        p_base = pressures[i - 1]
        dh = top_alt - base_alt
        if abs(lapse) < 1e-12:
            # isothermal layer: exponential pressure drop
            p_top = p_base * math.exp(-GRAV_ACCEL * dh / (AIR_CONSTANT * base_T))
        else:
            # gradient layer: power-law pressure
            T_top = base_T + lapse * dh
            p_top = p_base * (T_top / base_T) ** (-GRAV_ACCEL / (AIR_CONSTANT * lapse))
        pressures.append(p_top)
    return pressures


_ISA_BASE_PRESSURES = _build_layer_base_pressures()


def density(altitude_m):
    """Air density (kg/m^3) at a given altitude using the ISA layered model.

    Below 0 m clamps to sea level; above the ~85 km table top uses an
    exponential tail (air is negligible there anyway).
    """
    if altitude_m <= 0.0:
        altitude_m = 0.0

    top_alt, _top_T, _ = _ISA_LAYERS[-1]
    if altitude_m > top_alt:
        # Exponential tail above the standard table. Use the density at the
        # table top and a representative scale height (~7 km) to fade out.
        rho_top = _density_in_table(top_alt)
        scale_height = 7000.0
        return rho_top * math.exp(-(altitude_m - top_alt) / scale_height)

    return _density_in_table(altitude_m)


def _density_in_table(altitude_m):
    """Density within the standard ISA table (0–85 km)."""
    # Find the layer this altitude sits in.
    layer_idx = 0
    for i in range(len(_ISA_LAYERS)):
        if altitude_m >= _ISA_LAYERS[i][0]:
            layer_idx = i
        else:
            break

    base_alt, base_T, lapse = _ISA_LAYERS[layer_idx]
    p_base = _ISA_BASE_PRESSURES[layer_idx]
    dh = altitude_m - base_alt
    T = base_T + lapse * dh   # temperature varies linearly (the ISA definition)

    if abs(lapse) < 1e-12:
        p = p_base * math.exp(-GRAV_ACCEL * dh / (AIR_CONSTANT * base_T))
    else:
        p = p_base * (T / base_T) ** (-GRAV_ACCEL / (AIR_CONSTANT * lapse))

    return p / (AIR_CONSTANT * T)   # ideal gas law: density from pressure & temp


def gravity(altitude_m):
    """Gravitational acceleration (m/s^2) at altitude, inverse-square with
    distance from earth's center. Barely changes over glider altitudes but
    matters for very high launches."""
    return GRAV_ACCEL * (R_EARTH / (R_EARTH + altitude_m)) ** 2