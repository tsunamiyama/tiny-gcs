import asyncio
import json

import websockets

_WS_URL = "ws://localhost:8000/ws/telemetry"


async def main() -> None:
    """Connect to the telemetry WebSocket and print each frame."""
    async with websockets.connect(_WS_URL) as ws:
        print(f"connected to {_WS_URL}")
        async for message in ws:
            frame = json.loads(message)
            print(json.dumps(frame, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nclient stopped")