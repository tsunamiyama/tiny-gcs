"""FastAPI controller for the paper-plane glider simulation.

Primary path: a live telemetry WebSocket. The client sends one JSON message
describing the plane and the route, then receives a `meta` frame followed by
telemetry frames streamed as the simulation steps, paced in wall-clock time.

  WS   /flights/stream      -> live-stream telemetry frames as the sim runs

The REST helpers (summarize, playback) are kept as thin optional endpoints but
are secondary; the streaming endpoint is the one the front-end is built around.
"""

from typing import Optional, Tuple

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import anyio
from anyio.from_thread import BlockingPortal
from anyio.to_thread import run_sync

from glider_params import GliderParams
from glider import fly, summarize, prepare_playback

app = FastAPI(title="Glider Control", version="1.0.0")

# Open CORS so a browser front-end can call these directly. Tighten in prod.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ParamsIn(BaseModel):
    """User-tunable design knobs. All optional; omitted fields keep defaults."""
    mass: Optional[float] = Field(default=None, gt=0, description="kg")
    wing_area: Optional[float] = Field(default=None, gt=0, description="m^2")
    cl: Optional[float] = Field(default=None, description="lift coefficient")
    cd0: Optional[float] = Field(default=None, ge=0, description="parasitic drag coeff")
    induced_k: Optional[float] = Field(default=None, ge=0, description="induced drag factor")
    launch_speed: Optional[float] = Field(default=None, gt=0, description="m/s")
    launch_angle_deg: Optional[float] = Field(default=None, description="deg above horizontal")
    launch_alt: Optional[float] = Field(default=None, ge=0, description="m above ground")

    def to_params(self) -> GliderParams:
        p = GliderParams()
        for name, value in self.model_dump().items():
            if value is not None:
                setattr(p, name, value)
        return p


class LatLon(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)

    def as_tuple(self) -> Tuple[float, float]:
        return (self.lat, self.lon)


class StreamRequest(BaseModel):
    """One message opens a live stream: the plane, the route, the pacing."""
    params: ParamsIn = Field(default_factory=ParamsIn)
    start: LatLon
    end: LatLon
    headwind: float = Field(default=0.0, description="m/s; positive opposes travel")

    # Pacing. speed_factor multiplies simulated time -> wall-clock: 1.0 is real
    # time, 100 plays 100x faster. max_wall_s caps the whole stream so a long
    # flight can't stream forever. frame_stride thins dense fine-step frames.
    speed_factor: float = Field(default=1.0, gt=0, description="sim seconds per wall second")
    max_wall_s: Optional[float] = Field(default=None, gt=0, description="hard cap on stream length")
    frame_stride: int = Field(default=1, ge=1, description="emit every Nth sim frame")


# Wall-clock gap between emitted frames is clamped to this band so we neither
# spin the socket at kHz on fine steps nor stall for minutes on coarse ones.
_MIN_GAP_S = 1.0 / 60.0    # don't exceed ~60 fps
_MAX_GAP_S = 0.25          # don't let a single gap stall the animation


# ---------------------------------------------------------------------------
# WebSocket streaming (primary)
# ---------------------------------------------------------------------------
#
# We stream straight from `fly`, which yields a telemetry frame per sim step.
# Each frame carries `timestamp` (simulated seconds). We pace by the DELTA in
# simulated time between consecutive emitted frames, divided by speed_factor,
# to get how long to sleep in wall-clock -- so the animation advances in true
# proportion to the flight while staying bounded. The sim itself is synchronous
# and CPU-bound, so we drive it from a worker thread and hand frames to the
# async sender through a memory channel.

async def _run_stream(ws: WebSocket, req: StreamRequest) -> None:
    params = req.params.to_params()
    start = req.start.as_tuple()
    end = req.end.as_tuple()

    send_stream, receive_stream = anyio.create_memory_object_stream(max_buffer_size=256)

    def produce(portal: BlockingPortal):
        """Runs in a worker thread: step the sim, push frames into the channel.

        The sim is synchronous, so it runs off the event loop. It talks back to
        the async side through `portal`, anyio's supported sync->async bridge:
        portal.call(fn, *args) runs the async `fn` on the event loop and blocks
        until it completes, so the bounded channel's backpressure still applies.
        """
        gen = fly(params, start, end, req.headwind)
        try:
            for i, frame in enumerate(gen):
                if i % req.frame_stride != 0:
                    continue
                portal.call(send_stream.send, frame)
        finally:
            gen.close()
            portal.call(send_stream.aclose)

    await ws.send_json({
        "type": "meta",
        "data": {
            "speed_factor": req.speed_factor,
            "headwind": req.headwind,
            "design_glide_ratio": round(params.glide_ratio, 2),
        },
    })

    wall_start = anyio.current_time()
    prev_sim_t: Optional[float] = None

    async with anyio.create_task_group() as tg:
        async with BlockingPortal() as portal:
            # start_soon receives a plain zero-arg coroutine function; run_sync
            # is called normally inside it, where its variadic signature (and the
            # portal argument) resolve without confusing the type checker.
            async def run_producer() -> None:
                await run_sync(produce, portal)

            tg.start_soon(run_producer)

            async for frame in receive_stream:
                sim_t = frame["timestamp"]

                if prev_sim_t is not None:
                    gap = (sim_t - prev_sim_t) / req.speed_factor
                    gap = max(_MIN_GAP_S, min(_MAX_GAP_S, gap))
                    await anyio.sleep(gap)
                prev_sim_t = sim_t

                await ws.send_json({"type": "frame", "data": frame})

                if req.max_wall_s is not None and \
                        anyio.current_time() - wall_start >= req.max_wall_s:
                    tg.cancel_scope.cancel()
                    break

    await ws.send_json({"type": "end"})


@app.websocket("/flights/stream")
async def flight_stream(ws: WebSocket):
    await ws.accept()
    try:
        raw = await ws.receive_json()
        req = StreamRequest.model_validate(raw)
        await _run_stream(ws, req)
    except WebSocketDisconnect:
        return
    except Exception as exc:  # surface errors to the client before closing
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# REST helpers (optional / secondary)
# ---------------------------------------------------------------------------

class FlightRequest(BaseModel):
    params: ParamsIn = Field(default_factory=ParamsIn)
    start: LatLon
    end: LatLon
    headwind: float = 0.0


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/flights/summarize")
def flight_summarize(req: FlightRequest):
    """Optional: run to completion, return the feasibility outcome."""
    return summarize(
        req.params.to_params(), req.start.as_tuple(), req.end.as_tuple(),
        headwind=req.headwind,
    )


@app.post("/flights/playback")
def flight_playback(req: FlightRequest):
    """Optional: bounded, evenly-sampled frames + metadata for local playback."""
    return prepare_playback(
        req.params.to_params(), req.start.as_tuple(), req.end.as_tuple(),
        headwind=req.headwind,
    )