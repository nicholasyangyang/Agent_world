import asyncio
import pytest
from tests.conftest import send, recv_type, fire


@pytest.mark.asyncio
async def test_knock_and_accept(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    await fire(bob, {"type": "KNOCK", "target": "alice"})
    knock = await recv_type(alice, "KNOCK_RECEIVED")
    assert knock["from"] == "bob"
    await fire(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    accepted = await recv_type(bob, "KNOCK_ACCEPTED")
    assert accepted["from"] == "alice"


@pytest.mark.asyncio
async def test_knock_and_reject(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    await fire(bob, {"type": "KNOCK", "target": "alice"})
    await recv_type(alice, "KNOCK_RECEIVED")
    await fire(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": False})
    rejected = await recv_type(bob, "KNOCK_REJECTED")
    assert rejected["from"] == "alice"


@pytest.mark.asyncio
async def test_knock_offline_target(client):
    bob = await client("bob", "bpass")
    resp = await send(bob, {"type": "KNOCK", "target": "nobody"})
    assert resp["type"] == "ERROR"


@pytest.mark.asyncio
async def test_knock_target_not_home(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    carol = await client("carol", "cpass")
    await fire(bob, {"type": "KNOCK", "target": "carol"})
    await recv_type(carol, "KNOCK_RECEIVED")
    await fire(carol, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")
    enter_ok = await send(bob, {"type": "ENTER", "target": "carol"})
    assert enter_ok["type"] == "ENTER_OK"
    resp = await send(alice, {"type": "KNOCK", "target": "bob"})
    assert resp["type"] == "ERROR"


@pytest.mark.asyncio
async def test_enter_without_acceptance(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    resp = await send(bob, {"type": "ENTER", "target": "alice"})
    assert resp["type"] == "ERROR"


@pytest.mark.asyncio
async def test_enter_accepted_room(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    await fire(bob, {"type": "KNOCK", "target": "alice"})
    await recv_type(alice, "KNOCK_RECEIVED")
    await fire(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")
    resp = await send(bob, {"type": "ENTER", "target": "alice"})
    assert resp["type"] == "ENTER_OK"
    assert resp["room"]["owner"] == "alice"


@pytest.mark.asyncio
async def test_visitor_joined_broadcast(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    await fire(bob, {"type": "KNOCK", "target": "alice"})
    await recv_type(alice, "KNOCK_RECEIVED")
    await fire(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")
    await send(bob, {"type": "ENTER", "target": "alice"})
    joined = await recv_type(alice, "VISITOR_JOINED")
    assert joined["agent"] == "bob"


@pytest.mark.asyncio
async def test_visitor_left_broadcast(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    await fire(bob, {"type": "KNOCK", "target": "alice"})
    await recv_type(alice, "KNOCK_RECEIVED")
    await fire(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")
    await send(bob, {"type": "ENTER", "target": "alice"})
    await recv_type(alice, "VISITOR_JOINED")
    home_ok = await send(bob, {"type": "HOME"})
    assert home_ok["type"] == "HOME_OK"
    left = await recv_type(alice, "VISITOR_LEFT")
    assert left["agent"] == "bob"


@pytest.mark.asyncio
async def test_home_returns_own_room(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    await fire(bob, {"type": "KNOCK", "target": "alice"})
    await recv_type(alice, "KNOCK_RECEIVED")
    await fire(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")
    await send(bob, {"type": "ENTER", "target": "alice"})
    await recv_type(alice, "VISITOR_JOINED")
    resp = await send(bob, {"type": "HOME"})
    assert resp["type"] == "HOME_OK"
    assert resp["room"]["owner"] == "bob"


@pytest.mark.asyncio
async def test_who_lists_visitors(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    await fire(bob, {"type": "KNOCK", "target": "alice"})
    await recv_type(alice, "KNOCK_RECEIVED")
    await fire(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")
    await send(bob, {"type": "ENTER", "target": "alice"})
    await recv_type(alice, "VISITOR_JOINED")
    resp = await send(alice, {"type": "WHO"})
    assert resp["type"] == "WHO_RESULT"
    assert "bob" in resp["visitors"]


@pytest.mark.asyncio
async def test_list_online_agents(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    resp = await send(alice, {"type": "LIST"})
    assert resp["type"] == "LIST_RESULT"
    assert "alice" in resp["agents"]
    assert "bob" in resp["agents"]
