from app.telemetry_source import TelemetrySource
from app.schema import TelemetryState


class SourceManager:
    def __init__(self, live: TelemetrySource, replay: TelemetrySource):
        self._vehicle = live
        self._replay = replay
        self._active: TelemetrySource = replay

    @property
    def state(self) -> TelemetryState:
        return self._active.state

    @property
    def active_name(self) -> str:
        return self._active.name

    async def start(self) -> None:
        await self._active.start()

    async def use_vehicle(self) -> None:
        await self._vehicle.start()
        self._active = self._vehicle

    async def use_replay(self) -> None:
        self._active = self._replay

    async def stop(self) -> None:
        await self._vehicle.stop()
        await self._replay.stop()