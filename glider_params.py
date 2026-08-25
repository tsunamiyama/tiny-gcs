"""GliderParams — the user-tunable design parameters for the paper plane."""


class GliderParams:
    """The knobs a user tweaks when designing their paper plane.
    Defaults are a plausible ~5 g paper airplane; illustrative, not measured.
    """
    def __init__(self):
        self.mass = 0.005            # kg
        self.wing_area = 0.03        # m^2
        self.cl = 0.9                # lift coefficient (approx constant here)
        self.cd0 = 0.06              # parasitic drag coefficient
        self.induced_k = 0.10        # induced drag: cd = cd0 + k*cl^2
        self.launch_speed = 8.0      # m/s
        self.launch_angle_deg = 5.0  # release pitch above horizontal
        self.launch_alt = 30.0       # m above ground

    @property
    def cd(self):
        """Total drag coefficient from the drag polar: parasitic + induced."""
        return self.cd0 + self.induced_k * self.cl ** 2

    @property
    def glide_ratio(self):
        """Lift-to-drag ratio (L/D) — meters forward per meter of height lost."""
        return self.cl / self.cd