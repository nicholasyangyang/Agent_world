import asyncio
import json
import pytest
import websockets
from tests.conftest import send, recv_type


async def raw_connect(server):
    return await websockets.connect(f"ws://127.0.0.1:{server['port']}")


async def auth(ws, name, password):
    return await send(ws, {"type": "AUTH", "name": name, "password": password})


@pytest.mark.asyncio
async def test_register_new_agent(server):
    ws = await raw_connect(server)
    resp = await auth(ws, "alice", "pass123")
    assert resp["type"] == "AUTH_OK"
    assert resp["agent_id"] == "alice"
    assert "room" in resp
    assert resp["room"]["items"] == []
    await ws.close()


@pytest.mark.asyncio
async def test_login_existing_agent(server):
    ws1 = await raw_connect(server)
    await auth(ws1, "alice", "pass123")
    await ws1.close()
    await asyncio.sleep(0.05)
    ws2 = await raw_connect(server)
    resp = await auth(ws2, "alice", "pass123")
    assert resp["type"] == "AUTH_OK"
    await ws2.close()


@pytest.mark.asyncio
async def test_login_wrong_password(server):
    ws1 = await raw_connect(server)
    await auth(ws1, "alice", "pass123")
    await ws1.close()
    await asyncio.sleep(0.05)
    ws2 = await raw_connect(server)
    resp = await auth(ws2, "alice", "wrongpass")
    assert resp["type"] == "AUTH_FAIL"
    await ws2.close()


@pytest.mark.asyncio
async def test_duplicate_login(server):
    ws1 = await raw_connect(server)
    await auth(ws1, "alice", "pass123")
    ws2 = await raw_connect(server)
    resp = await auth(ws2, "alice", "pass123")
    assert resp["type"] == "AUTH_FAIL"
    await ws1.close()
    await ws2.close()


@pytest.mark.asyncio
async def test_reconnect_after_disconnect(server):
    ws1 = await raw_connect(server)
    await auth(ws1, "alice", "pass123")
    await ws1.close()
    await asyncio.sleep(0.1)
    ws2 = await raw_connect(server)
    resp = await auth(ws2, "alice", "pass123")
    assert resp["type"] == "AUTH_OK"
    await ws2.close()
