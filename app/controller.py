import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.vehicle import VehicleConnection

# How often we push a telemetry frame to the client, independent of
# the rates at which MAVSDK's streams update the cache.
_PUSH_INTERVAL_S = 0.1  # 10 Hz

router = APIRouter()


@router.websocket("/ws/telemetry")
async def telemetry_ws(websocket: WebSocket) -> None:
    """Stream the latest cached telemetry to one client at a fixed rate.

    Polls the vehicle's telemetry cache every _PUSH_INTERVAL_S and sends
    it as JSON. No per-client state and no shared queue — the cache is
    the single source, so every connection just samples the same fresh
    snapshot independently."""
    await websocket.accept()
    vehicle: VehicleConnection = websocket.app.state.vehicle

    try:
        while True:
            await websocket.send_json(vehicle.state.to_json())
            await asyncio.sleep(_PUSH_INTERVAL_S)
    except WebSocketDisconnect:
        # Client went away; nothing to unwind (no registration to undo).
        pass