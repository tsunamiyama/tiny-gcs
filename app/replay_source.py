import asyncio
import logging
import math

from pyulog import ULog

from app.schema import (
    TelemetryState,
    Position,
    Attitude,
    Battery,
)

logger = logging.getLogger("uvicorn.error")


# PX4 nav_state (commander_state) -> readable label. Only the modes seen
# in typical arm->takeoff->hold->land flights are named; anything else
# falls back to "MODE_<n>" so replay never crashes on an unmapped value.
_NAV_STATE = {
    0: "MANUAL",
    2: "POSCTL",
    3: "AUTO_MISSION",
    4: "AUTO_LOITER",
    5: "AUTO_RTL",
    14: "OFFBOARD",
    17: "AUTO_TAKEOFF",
    18: "AUTO_LAND",
}


class ReplaySource:
    """Replays a recorded PX4 .ulog over the same TelemetryState surface
    the live source uses, so the WebSocket endpoint can't tell them apart.

    Parses the log once into time-ordered frames, then loops a single
    task that writes into self.state on a wall-clock schedule.

    Field mappings are locked to a PX4 SITL log (verified against
    demo.ulog): battery.remaining is already 0-1, arming_state==2 means
    armed, and relative altitude comes from vehicle_local_position.z
    (NED, so rel_alt = -z) since vehicle_global_position carries no
    relative-altitude field."""

    _TOPICS = (
        "vehicle_global_position",
        "vehicle_local_position",
        "vehicle_attitude",
        "battery_status",
        "vehicle_status",
    )

    def __init__(self, ulog_path: str, speed: float = 1.0):
        self._path = ulog_path
        self._speed = speed          # 1.0 = real time; 2.0 = twice as fast
        self.state = TelemetryState()
        self._task: asyncio.Task | None = None
        self._frames: list[tuple[float, str, object]] = []

    @property
    def name(self) -> str:
        return "log-replay"

    @property
    def healthy(self) -> bool:
        # log loaded and valid — independent of whether the loop is still
        # running, so a finished replay stays healthy
        return bool(self._frames)

    async def start(self) -> None:
        if self._task:
            return                    # idempotent
        self._frames = await asyncio.to_thread(self._load_frames)
        self.state.connected = True
        self._task = asyncio.create_task(self._replay())
        logger.info(f"Replaying {self._path} ({len(self._frames)} frames)")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    # --- parsing ----------------------------------------------------

    def _load_frames(self) -> list[tuple[float, str, object]]:
        """Flatten the ulog into (t_seconds, field, value), time-sorted.

        lat/lon/abs_alt come from vehicle_global_position; rel_alt comes
        from vehicle_local_position.z. Because those are separate topics
        at different rates, we don't build Position objects here — we emit
        the raw components and let _replay() assemble a complete Position
        by carrying the last-seen value of each. Runs in a thread; pyulog
        is synchronous and file-bound."""
        ulog = ULog(self._path, self._TOPICS)
        ds = {d.name: d.data for d in ulog.data_list}
        frames: list[tuple[float, str, object]] = []

        def secs(arr):
            return [t / 1e6 for t in arr]

        # global position -> lat / lon / abs_alt
        if "vehicle_global_position" in ds:
            g = ds["vehicle_global_position"]
            t = secs(g["timestamp"])
            for i in range(len(t)):
                frames.append((t[i], "_lat", float(g["lat"][i])))
                frames.append((t[i], "_lon", float(g["lon"][i])))
                frames.append((t[i], "_abs_alt", float(g["alt"][i])))

        # local position -> rel_alt (NED z is down-positive, so negate)
        if "vehicle_local_position" in ds:
            lp = ds["vehicle_local_position"]
            t = secs(lp["timestamp"])
            for i in range(len(t)):
                frames.append((t[i], "_rel_alt", -float(lp["z"][i])))

        # attitude quaternion [w,x,y,z] -> euler degrees
        if "vehicle_attitude" in ds:
            a = ds["vehicle_attitude"]
            t = secs(a["timestamp"])
            q0, q1 = a["q[0]"], a["q[1]"]
            q2, q3 = a["q[2]"], a["q[3]"]
            for i in range(len(t)):
                roll, pitch, yaw = _quat_to_euler(
                    float(q0[i]), float(q1[i]), float(q2[i]), float(q3[i])
                )
                frames.append((t[i], "attitude",
                               Attitude(roll=roll, pitch=pitch, yaw=yaw)))

        # battery -> voltage / remaining (remaining already 0-1)
        if "battery_status" in ds:
            b = ds["battery_status"]
            t = secs(b["timestamp"])
            for i in range(len(t)):
                frames.append((t[i], "battery",
                               Battery(voltage=float(b["voltage_v"][i]),
                                       remaining=float(b["remaining"][i]))))

        # status -> armed (arming_state==2) and flight_mode label
        if "vehicle_status" in ds:
            s = ds["vehicle_status"]
            t = secs(s["timestamp"])
            for i in range(len(t)):
                frames.append((t[i], "armed", int(s["arming_state"][i]) == 2))
                nav = int(s["nav_state"][i])
                frames.append((t[i], "flight_mode",
                               _NAV_STATE.get(nav, f"MODE_{nav}")))

        frames.sort(key=lambda f: f[0])
        return frames

    # --- replay loop ------------------------------------------------

    async def _replay(self) -> None:
        if not self._frames:
            return
        # carried position components, so a partial update never
        # overwrites the complete Position with a half-filled one
        lat: float | None = None
        lon: float | None = None
        abs_alt: float | None = None
        rel_alt: float | None = None
        t0 = self._frames[0][0]
        wall0 = asyncio.get_event_loop().time()

        for t, field, value in self._frames:
            target = wall0 + (t - t0) / self._speed
            now = asyncio.get_event_loop().time()
            await asyncio.sleep(max(0.0, target - now))

            if field in ("_lat", "_lon", "_abs_alt", "_rel_alt"):
                assert isinstance(value, float)   # narrows object -> float
                if field == "_lat":
                    lat = value
                elif field == "_lon":
                    lon = value
                elif field == "_abs_alt":
                    abs_alt = value
                else:
                    rel_alt = value
            else:
                setattr(self.state, field, value)
                continue

            # emit a Position only once all four components exist
            if (
                lat is not None
                and lon is not None
                and abs_alt is not None
                and rel_alt is not None
            ):
                self.state.position = Position(
                    lat=lat, lon=lon, abs_alt=abs_alt, rel_alt=rel_alt
                )

        # replay reached the end of the log — signal completion. Final
        # telemetry stays on self.state (landed, disarmed); connected
        # flips false so the frontend can show the stream has ended.
        self.state.connected = False


def _quat_to_euler(w: float, x: float, y: float, z: float) -> tuple[float, float, float]:
    """PX4 body quaternion [w,x,y,z] -> roll/pitch/yaw in degrees."""
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)