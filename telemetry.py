import math
import time

def _attitude(snapshot):
    msg = snapshot.get("ATTITUDE")

    if msg is None:
        return None
    
    return {
        "roll_deg": math.degrees(msg.roll),
        "pitch_deg": math.degrees(msg.pitch),
        "yaw_deg": math.degrees(msg.yaw),
        "roll_rate": msg.rollspeed,
        "pitch_rate": msg.pitchspeed,
        "yaw_rate": msg.yawspeed
    }

def _position(snapshot):
    msg = snapshot.get("GLOBAL_POSITION_INT")

    if msg is None:
        return None

    return {
        "lat": msg.lat / 1e7,
        "lon": msg.lon/1e7,
        "alt_msl_m": msg.alt/1000.0,
        "alt_rel_m": msg.relative_alt/1000.0,
        "heading_deg": msg.hdg/100.0 if msg.hdg != 65535 else None,
        "vx": msg.vx/100.0,
        "vy": msg.vy/100.0,
        "vz": msg.vz/100.0
    }

def _battery(snapshot):
    msg = snapshot.get("SYS_STATUS")

    if msg is None:
        return None

    return {
        "voltage_v": msg.voltage_battery/1000.0 if msg.voltage_battery != -1 else None,
        "current_a": msg.current_battery/100.0 if msg.current_battery != -1 else None,
        "remaining_pct": msg.battery_remaining if msg.battery_remaining != -1 else None
    }

def _status(snapshot):
    msg = snapshot.get("HEARTBEAT")

    if msg is None:
        return None
    
    armed = bool(msg.base_mode & 0x80)

    return {
        "armed": armed,
        "system_status": msg.system_status,
        "custom_mode": msg.custom_mode
    }

def build_telemetry(snapshot):
    return {
        "timestamp": time.time(),
        "attitude": _attitude(snapshot),
        "position": _position(snapshot),
        "battery": _battery(snapshot),
        "status": _status(snapshot)
    }