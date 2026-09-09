import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from mavsdk.action import ActionError
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

def get_vehicle(request: Request) -> VehicleConnection:
    vehicle: VehicleConnection = request.app.state.vehicle
    if not vehicle.state.connected:
        raise HTTPException(status_code=503, detail="vehicle not connected")
    return vehicle

@router.post("/command/arm", status_code=202)
async def arm(vehicle: VehicleConnection = Depends(get_vehicle)):
    try:
        await vehicle.arm()
        return {"status": "accepted", "command": "arm"}
    except ActionError as e:
        raise HTTPException(status_code=409, detail=str(e))

@router.post("/command/takeoff", status_code=202)
async def takeoff(vehicle: VehicleConnection = Depends(get_vehicle)):
    try:
        await vehicle.takeoff()
        return {"status": "accepted", "command": "takeoff"}
    except ActionError as e:
        raise HTTPException(status_code=409, detail=str(e))

@router.post("/command/land", status_code=202)
async def land(vehicle: VehicleConnection = Depends(get_vehicle)):
    try:
        await vehicle.land()
        return {"status": "accepted", "command": "land"}
    except ActionError as e:
        raise HTTPException(status_code=409, detail=str(e))

@router.post("/command/rtl", status_code=202)
async def return_to_launch(vehicle: VehicleConnection = Depends(get_vehicle)):
    try:
        await vehicle.return_to_launch()
        return {"status": "accepted", "command": "return to launch"}
    except ActionError as e:
        raise HTTPException(status_code=409, detail=str(e))