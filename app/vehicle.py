import asyncio
import logging
from mavsdk import System

from app.schema import (
    TelemetryState,
    Position,
    Attitude,
    Battery,
)

logger = logging.getLogger("uvicorn.error")

class VehicleConnection:
    """Owns the single MAVSDK connection to PX4 — the one link through
    which both telemetry and commands flow.

    Telemetry: background tasks read each MAVSDK stream and write into
    `self.state`, which the WebSocket endpoint reads.
    Commands (Phase 3): action calls (arm/takeoff/land) issued over the
    same connection."""

    def __init__(self, system_address: str = "udpin://0.0.0.0:14540"):
        self._system_address = system_address
        self._drone = System()
        self.state = TelemetryState()
        self._tasks: list[asyncio.Task] = []

    async def connect(self) -> None:
        """Connect to PX4 and block until the link is up."""
        await self._drone.connect(system_address=self._system_address)

        # Block until PX4 is actually heard from (first heartbeat).
        async for state in self._drone.core.connection_state():
            if state.is_connected:
                self.state.connected = True
                break

        logger.info(f"Vehicle Connected on {self._system_address}")

    def start(self) -> None:
        """Launch one background task per telemetry stream."""
        self._tasks = [
            asyncio.create_task(self._watch_position()),
            asyncio.create_task(self._watch_attitude()),
            asyncio.create_task(self._watch_armed()),
            asyncio.create_task(self._watch_flight_mode()),
            asyncio.create_task(self._watch_battery()),
            asyncio.create_task(self._watch_connection()),
        ]

    async def stop(self) -> None:
        """Cancel all background tasks cleanly."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # --- telemetry stream readers -----------------------------------

    async def _watch_position(self) -> None:
        async for p in self._drone.telemetry.position():
            self.state.position = Position(
                lat=p.latitude_deg,
                lon=p.longitude_deg,
                abs_alt=p.absolute_altitude_m,
                rel_alt=p.relative_altitude_m,
            )

    async def _watch_attitude(self) -> None:
        async for a in self._drone.telemetry.attitude_euler():
            self.state.attitude = Attitude(
                roll=a.roll_deg,
                pitch=a.pitch_deg,
                yaw=a.yaw_deg,
            )

    async def _watch_armed(self) -> None:
        async for is_armed in self._drone.telemetry.armed():
            self.state.armed = is_armed

    async def _watch_flight_mode(self) -> None:
        async for fm in self._drone.telemetry.flight_mode():
            self.state.flight_mode = str(fm)

    async def _watch_battery(self) -> None:
        async for b in self._drone.telemetry.battery():
            self.state.battery = Battery(
                voltage=b.voltage_v,
                remaining=b.remaining_percent,
            )

    async def _watch_connection(self) -> None:
        async for state in self._drone.core.connection_state():
            self.state.connected = state.is_connected

    # --- commands (Phase 3) -----------------------------------------
    # arm / takeoff / land / RTL will live here, issued over the same
    # self._drone connection via self._drone.action.*