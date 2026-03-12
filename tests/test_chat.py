import asyncio
import pytest
from tests.conftest import send, recv_type, fire


async def enter_room(guest, host_ws, host_name, guest_name):
    await fire(guest, {"type": "KNOCK", "target": host_name})
    await recv_type(host_ws, "KNOCK_RECEIVED")
    await fire(host_ws, {"type": "KNOCK_REPLY", "to": guest_name, "accept": True})
    await recv_type(guest, "KNOCK_ACCEPTED")
    enter_ok = await send(guest, {"type": "ENTER", "target": host_name})
    assert enter_ok["type"] == "ENTER_OK"
    await recv_type(host_ws, "VISITOR_JOINED")


@pytest.mark.asyncio
async def test_say_broadcast(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    await enter_room(bob, alice, "alice", "bob")
    bob_msg = await send(bob, {"type": "SAY", "text": "你好"})
    alice_msg = await recv_type(alice, "SAID")
    assert alice_msg["from"] == "bob"
    assert alice_msg["text"] == "你好"
    assert bob_msg["type"] == "SAID"
    assert bob_msg["from"] == "bob"


@pytest.mark.asyncio
async def test_say_not_to_other_rooms(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    carol = await client("carol", "cpass")
    await enter_room(bob, alice, "alice", "bob")
    bob_said = await send(bob, {"type": "SAY", "text": "秘密"})
    assert bob_said["type"] == "SAID"
    await recv_type(alice, "SAID")
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await recv_type(carol, "SAID", timeout=0.3)


@pytest.mark.asyncio
async def test_whisper_delivery(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    await fire(alice, {"type": "WHISPER", "target": "bob", "text": "悄悄话"})
    msg = await recv_type(bob, "WHISPERED")
    assert msg["from"] == "alice"
    assert msg["text"] == "悄悄话"


@pytest.mark.asyncio
async def test_whisper_not_to_others(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    carol = await client("carol", "cpass")
    await fire(alice, {"type": "WHISPER", "target": "bob", "text": "只给bob"})
    await recv_type(bob, "WHISPERED")
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await recv_type(carol, "WHISPERED", timeout=0.3)


@pytest.mark.asyncio
async def test_whisper_offline_target(client):
    alice = await client("alice", "apass")
    resp = await send(alice, {"type": "WHISPER", "target": "nobody", "text": "hi"})
    assert resp["type"] == "ERROR"
