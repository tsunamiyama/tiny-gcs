"""Shared physical constants for the glider simulation.

These are depended on by the atmosphere/gravity model and the geography helpers.
This module imports nothing, so anything can import it without circular-dependency
risk.
"""

GRAV_ACCEL = 9.80665          # m/s^2, standard gravity at sea level
R_EARTH = 6_371_000.0         # m, mean earth radius (gravity vs altitude, great-circle)
AIR_CONSTANT = 287.05         # J/(kg·K), specific gas constant for air