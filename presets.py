"""Launch altitude presets for the paper-plane simulator.

Each preset is a named real-world height. The user chooses WHERE to launch
(a position on the map) separately; the preset supplies only the starting
ALTITUDE. So there are no coordinates here — just a height and some flavor.

Ordered low to high. Every entry in this starting set sits in the regime where
the flat-vertical-plane glider physics is valid (vertical extent negligible
against earth curvature), so they all run on the base model. Higher presets
(airliner cruise, Karman line, etc.) come later and may need the extended
density / spherical treatment.

`altitude_m` is height above the launch ground, in meters.
"""

PRESETS = [
    {
        "id": "human",
        "name": "Human height",
        "altitude_m": 1.6,
        "blurb": "Just letting go at eye level.",
    },
    {
        "id": "hoop",
        "name": "Basketball hoop",
        "altitude_m": 3.05,
        "blurb": "Regulation rim height.",
    },
    {
        "id": "house",
        "name": "Two-story house",
        "altitude_m": 6.0,
        "blurb": "Out the upstairs window.",
    },
    {
        "id": "tree",
        "name": "Tall tree",
        "altitude_m": 15.0,
        "blurb": "About four stories of trunk.",
    },
    {
        "id": "pisa",
        "name": "Leaning Tower of Pisa",
        "altitude_m": 57.0,
        "blurb": "From the top of the lean.",
    },
    {
        "id": "liberty",
        "name": "Statue of Liberty (torch)",
        "altitude_m": 93.0,
        "blurb": "Up at the torch.",
    },
    {
        "id": "giza",
        "name": "Great Pyramid of Giza",
        "altitude_m": 139.0,
        "blurb": "The ancient-world skyscraper.",
    },
    {
        "id": "golden_gate",
        "name": "Golden Gate Bridge tower",
        "altitude_m": 227.0,
        "blurb": "Top of the north tower.",
    },
    {
        "id": "empire_state",
        "name": "Empire State Building",
        "altitude_m": 380.0,
        "blurb": "Roof height, no antenna.",
    },
    {
        "id": "burj_khalifa",
        "name": "Burj Khalifa",
        "altitude_m": 828.0,
        "blurb": "Tallest building in the world.",
    },
    {
        "id": "everest",
        "name": "Mount Everest summit",
        "altitude_m": 8849.0,
        "blurb": "Top of the world.",
    },
]

# Lookup by id, for when a request references a preset.
PRESETS_BY_ID = {p["id"]: p for p in PRESETS}


def get_altitude(preset_id):
    """Return the altitude (m) for a preset id, or None if unknown."""
    preset = PRESETS_BY_ID.get(preset_id)
    return preset["altitude_m"] if preset else None