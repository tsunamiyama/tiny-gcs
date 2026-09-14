from typing import Protocol, runtime_checkable

from app.schema import TelemetryState

@runtime_checkable
class TelemetrySource(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def state(self) -> TelemetryState: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...
