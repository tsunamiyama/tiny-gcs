from dataclasses import dataclass, asdict
from typing import Optional
import time


@dataclass
class Position:
    lat: float
    lon: float
    abs_alt: float
    rel_alt: float


@dataclass
class Attitude:
    roll: float   # degrees
    pitch: float  # degrees
    yaw: float    # degrees


@dataclass
class Battery:
    voltage: float
    remaining: float  # 0.0–1.0


@dataclass
class TelemetryState:
    """The full telemetry snapshot. Any subsystem is None until its
    first stream tick arrives from MAVSDK."""
    position: Optional[Position] = None
    attitude: Optional[Attitude] = None
    flight_mode: Optional[str] = None
    armed: Optional[bool] = None
    battery: Optional[Battery] = None
    connected: bool = False

    def to_json(self) -> dict:
        """Serialize to the JSON shape the client consumes."""
        return {
            "timestamp": time.time(),
            "connected": self.connected,
            "position": asdict(self.position) if self.position else None,
            "attitude": asdict(self.attitude) if self.attitude else None,
            "flight_mode": self.flight_mode,
            "armed": self.armed,
            "battery": asdict(self.battery) if self.battery else None,
        }