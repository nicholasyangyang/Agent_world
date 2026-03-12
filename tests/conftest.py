import asyncio
import json
import pytest
import websockets
from server.db import init_db
from server.main import create_server


@pytest.fixture
async def server():
    db = await init_db(":memory:")
    state, ws_server = await create_server(db, host="127.0.0.1", port=0)
    port = ws_server.sockets[0].getsockname()[1]
    yield {"port": port, "state": state, "db": db}
    ws_server.close()
    await ws_server.wait_closed()
    await db.close()


@pytest.fixture
async def client(server):
    clients = []

    async def make_client(name="testuser", password="testpass"):
        ws = await websockets.connect(f"ws://127.0.0.1:{server['port']}")
        await ws.send(json.dumps({"type": "AUTH", "name": name, "password": password}))
        resp = json.loads(await ws.recv())
        assert resp["type"] == "AUTH_OK"
        clients.append(ws)
        return ws

    yield make_client

    for ws in clients:
        try:
            await ws.close()
        except Exception:
            pass


async def send(ws, msg: dict) -> dict:
    await ws.send(json.dumps(msg))
    return json.loads(await ws.recv())


async def fire(ws, msg: dict) -> None:
    """Send a message without waiting for a response."""
    await ws.send(json.dumps(msg))


async def recv_type(ws, expected_type: str, timeout: float = 2.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise TimeoutError(f"未收到 {expected_type}")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        msg = json.loads(raw)
        if msg["type"] == expected_type:
            return msg
