import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from pymavlink import mavutil
from mavLinker import MavLinker
from telemetry import build_telemetry


TELEMETRY_HZ = 10

linker: MavLinker | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global linker
    linker = await asyncio.to_thread(MavLinker, "udpin:localhost:14540")

    linker.start()

    try:
        yield
    finally:
        linker.stop()
        linker = None

app = FastAPI(title="GCS Backend", lifespan = lifespan)

class CommandResult(BaseModel):
    command: str
    accepted: bool
    result_code: int | None = None
    detail: str

_RESULT_NAMES = {
    mavutil.mavlink.MAV_RESULT_ACCEPTED: "accepted",
    mavutil.mavlink.MAV_RESULT_TEMPORARILY_REJECTED: "temporarily rejected",
    mavutil.mavlink.MAV_RESULT_DENIED: "denied",
    mavutil.mavlink.MAV_RESULT_UNSUPPORTED: "unsupported",
    mavutil.mavlink.MAV_RESULT_FAILED: "failed"
}

def _require_linker() -> MavLinker:
    if linker is None:
        raise HTTPException(status_code=503, detail="MAVLINK link is not ready")
    if not linker.link_alive():
        raise HTTPException(status_code=503, detail="MAVLINK link is lost (no recent heartbeat)")
    return linker

def _ack_to_response(command: str, ack) -> CommandResult:
    if ack is None:
        raise HTTPException(status_code=504, detail=f"{command}: no acknowledgement from vehicle (timed out)")
    elif ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
        return CommandResult(command=command, accepted=True, result_code=ack.result, detail=f"{command} accepted")
    else:
        name = _RESULT_NAMES.get(ack.result, f"result {ack.result}")
        raise HTTPException(status_code=409, detail=f"{command} rejected by vehicle: {name}")

@app.post("/command/arm", response_model=CommandResult)
async def arm():
    mav = _require_linker()
    ack = await asyncio.to_thread(mav.arm)
    return _ack_to_response("arm", ack)

@app.post("/command/disarm", response_model=CommandResult)
async def disarm():
    mav = _require_linker()
    ack = await asyncio.to_thread(mav.disarm)
    return _ack_to_response("disarm", ack)

class TakeoffRequest(BaseModel):
    altitude: float = 10.0

@app.post("/command/takeoff", response_model=CommandResult)
async def takeoff(req: TakeoffRequest):
    mav = _require_linker()
    ack = await asyncio.to_thread(mav.takeoff, req.altitude)
    return _ack_to_response("takeoff", ack)

@app.post("/command/land", response_model=CommandResult)
async def land():
    mav = _require_linker()
    ack = await asyncio.to_thread(mav.land)
    return _ack_to_response("land", ack)

@app.get("/health")
async def health():
    alive = linker is not None and linker.link_alive()
    return {"link_alive": alive}

@app.websocket("/ws/telemetry")
async def telemetry_ws(ws: WebSocket):
    await ws.accept()
    interval = 1.0/TELEMETRY_HZ
    try:
        while True:
            if linker is not None:
                payload = build_telemetry(linker.snapshot())
                payload["link_alive"] = linker.link_alive()
                await ws.send_json(payload)
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        pass