import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from vehicle import VehicleConnection
from controller import router

async def _bring_up(vehicle: VehicleConnection) -> None:
    """Connect to PX4 and start the readers, off the startup path so
    the server boots immediately and stays Ctrl+C-responsive even if
    PX4 isn't up yet."""
    await vehicle.connect()
    vehicle.start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    vehicle = VehicleConnection()
    app.state.vehicle = vehicle

    # Kick off connection in the background; don't block startup on it.
    bringup = asyncio.create_task(_bring_up(vehicle))

    try:
        yield
    finally:
        bringup.cancel()                       # in case connect() is still waiting
        await asyncio.gather(bringup, return_exceptions=True)
        await vehicle.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(router)