"""Unit tests for the telemetry schema — the wire-format contract that
both the WebSocket client and the Angular frontend consume.

These tests pin down the shape of `TelemetryState.to_json()` so a change
to the serialized format is caught here rather than downstream.

All sample telemetry values live in the constants block below so each
value is defined exactly once — change it there and every test that uses
it follows.
"""

import json

from app.schema import (
    TelemetryState,
    Position,
    Attitude,
    Battery,
)


# --- sample telemetry values (single source of truth) ----------------

# Position
LAT = 47.397
LON = 8.545
ABS_ALT = 488.0
REL_ALT = 0.02

# Attitude (degrees)
ROLL = 1.5
PITCH = -2.0
YAW = 90.0

# Battery
VOLTAGE = 16.2
REMAINING = 0.98

# Flat fields
FLIGHT_MODE = "HOLD"
ARMED = True
CONNECTED = True


# --- reusable builders -----------------------------------------------


def _position() -> Position:
    return Position(lat=LAT, lon=LON, abs_alt=ABS_ALT, rel_alt=REL_ALT)


def _attitude() -> Attitude:
    return Attitude(roll=ROLL, pitch=PITCH, yaw=YAW)


def _battery() -> Battery:
    return Battery(voltage=VOLTAGE, remaining=REMAINING)


def _populated_state() -> TelemetryState:
    return TelemetryState(
        position=_position(),
        attitude=_attitude(),
        flight_mode=FLIGHT_MODE,
        armed=ARMED,
        battery=_battery(),
        connected=CONNECTED,
    )


# --- the subsystem dataclasses ---------------------------------------


def test_position_fields():
    p = _position()
    assert p.lat == LAT
    assert p.lon == LON
    assert p.abs_alt == ABS_ALT
    assert p.rel_alt == REL_ALT


def test_attitude_fields():
    a = _attitude()
    assert a.roll == ROLL
    assert a.pitch == PITCH
    assert a.yaw == YAW


def test_battery_fields():
    b = _battery()
    assert b.voltage == VOLTAGE
    assert b.remaining == REMAINING


# --- TelemetryState defaults -----------------------------------------


def test_fresh_state_defaults():
    """A freshly constructed state has every subsystem empty and is
    not connected — the pre-telemetry starting condition."""
    s = TelemetryState()
    assert s.position is None
    assert s.attitude is None
    assert s.flight_mode is None
    assert s.armed is None
    assert s.battery is None
    assert s.connected is False


def test_armed_none_distinct_from_false():
    """`armed` defaults to None (unknown), which must stay distinct
    from False (known-disarmed) — the reason it's Optional[bool]."""
    s = TelemetryState()
    assert s.armed is None
    assert s.armed is not False


# --- to_json() on an empty state -------------------------------------


def test_to_json_empty_keys():
    """The wire format always carries the full key set, even before any
    telemetry has arrived."""
    frame = TelemetryState().to_json()
    assert set(frame.keys()) == {
        "timestamp",
        "connected",
        "position",
        "attitude",
        "flight_mode",
        "armed",
        "battery",
    }


def test_to_json_empty_values():
    frame = TelemetryState().to_json()
    assert frame["connected"] is False
    assert frame["position"] is None
    assert frame["attitude"] is None
    assert frame["flight_mode"] is None
    assert frame["armed"] is None
    assert frame["battery"] is None


def test_to_json_timestamp_is_float():
    frame = TelemetryState().to_json()
    assert isinstance(frame["timestamp"], float)


# --- to_json() on a populated state ----------------------------------


def test_to_json_nested_position():
    """Present subsystems serialize as nested dicts, not dataclasses."""
    frame = _populated_state().to_json()
    assert frame["position"] == {
        "lat": LAT,
        "lon": LON,
        "abs_alt": ABS_ALT,
        "rel_alt": REL_ALT,
    }


def test_to_json_nested_attitude():
    frame = _populated_state().to_json()
    assert frame["attitude"] == {"roll": ROLL, "pitch": PITCH, "yaw": YAW}


def test_to_json_nested_battery():
    frame = _populated_state().to_json()
    assert frame["battery"] == {"voltage": VOLTAGE, "remaining": REMAINING}


def test_to_json_flat_fields():
    """flight_mode and armed are top-level siblings, not nested under a
    'mode' object — the flattening decision from the schema."""
    frame = _populated_state().to_json()
    assert frame["flight_mode"] == FLIGHT_MODE
    assert frame["armed"] is ARMED
    assert frame["connected"] is CONNECTED


def test_to_json_partial_state():
    """A mix of present and absent subsystems: present ones serialize,
    absent ones stay None. Models the startup window where some streams
    have ticked and others haven't."""
    s = TelemetryState(position=_position(), connected=CONNECTED)
    frame = s.to_json()
    assert frame["position"] == {
        "lat": LAT,
        "lon": LON,
        "abs_alt": ABS_ALT,
        "rel_alt": REL_ALT,
    }
    assert frame["attitude"] is None
    assert frame["battery"] is None
    assert frame["armed"] is None
    assert frame["connected"] is CONNECTED


# --- the whole frame must survive real JSON serialization ------------


def test_to_json_is_json_serializable_empty():
    """to_json() returns a dict; it must round-trip through the actual
    json module, since that's what send_json does on the wire."""
    frame = TelemetryState().to_json()
    assert json.loads(json.dumps(frame)) == frame


def test_to_json_is_json_serializable_populated():
    frame = _populated_state().to_json()
    assert json.loads(json.dumps(frame)) == frame