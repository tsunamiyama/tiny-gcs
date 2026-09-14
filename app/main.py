import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.replay_source import ReplaySource
from app.source_manager import SourceManager
from app.telemetry_source import TelemetrySource
from app.vehicle import VehicleConnection
from app.controller import router

async def _bring_up(manager: SourceManager) -> None:
    """Connect to PX4 and start the readers, off the startup path so
    the server boots immediately and stays Ctrl+C-responsive even if
    PX4 isn't up yet."""
    await manager.start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    vehicle = VehicleConnection()
    replay = ReplaySource("flights/demo.ulog")
    manager = SourceManager(live= vehicle, replay = replay)
    app.state.sources = manager

    # Kick off connection in the background; don't block startup on it.
    bringup = asyncio.create_task(_bring_up(manager))

    try:
        yield
    finally:
        bringup.cancel()                       # in case connect() is still waiting
        await asyncio.gather(bringup, return_exceptions=True)
        await vehicle.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)