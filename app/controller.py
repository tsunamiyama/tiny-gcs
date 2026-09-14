import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from mavsdk.action import ActionError
from app.source_manager import SourceManager
from app.vehicle import VehicleConnection

_PUSH_INTERVAL_S = 0.1  # 10 Hz

router = APIRouter()


def get_manager(request: Request) -> SourceManager:
    return request.app.state.sources


@router.websocket("/ws/telemetry")
async def telemetry_ws(websocket: WebSocket) -> None:
    """Stream the latest cached telemetry to one client at a fixed rate.

    Polls the active source's telemetry cache every _PUSH_INTERVAL_S and
    sends it as JSON. No per-client state — the cache is the single
    source, so every connection samples the same fresh snapshot."""
    manager: SourceManager = websocket.app.state.sources
    await websocket.accept()
    try:
        while True:
            payload = manager.state.to_json()
            payload["source"] = manager.active_name
            await websocket.send_json(payload)
            await asyncio.sleep(_PUSH_INTERVAL_S)
    except WebSocketDisconnect:
        pass


# --- source switching -----------------------------------------------

@router.post("/source/{mode}")
async def set_source(mode: str, manager: SourceManager = Depends(get_manager)):
    if mode == "live":
        await manager.use_vehicle()
    elif mode == "replay":
        await manager.use_replay()
    else:
        raise HTTPException(status_code=400, detail=f"unknown mode: {mode}")
    return {"active": manager.active_name}


# --- commands (live vehicle only) -----------------------------------

def get_vehicle(manager: SourceManager = Depends(get_manager)) -> VehicleConnection:
    """Commands target the real vehicle, never replay. Reject unless the
    live source is active and connected."""
    vehicle = manager.vehicle
    if manager.active_name != vehicle.name:
        raise HTTPException(status_code=409, detail="commands require live source; switch to live first")
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