import asyncio
import pytest
from tests.conftest import send, recv_type, fire


@pytest.mark.asyncio
async def test_full_visit_scenario(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    await send(alice, {"type": "SET_DESC", "description": "爱丽丝的茶室"})
    await send(alice, {"type": "PLACE_ITEM", "icon": "🍵", "name": "茶具", "description": "精美茶具"})
    await send(alice, {"type": "PLACE_ITEM", "icon": "🌸", "name": "樱花", "description": "盛开的樱花"})
    # KNOCK has no direct response to sender; target gets KNOCK_RECEIVED
    await fire(bob, {"type": "KNOCK", "target": "alice"})
    knock = await recv_type(alice, "KNOCK_RECEIVED")
    assert knock["from"] == "bob"
    # KNOCK_REPLY has no direct response to alice; bob gets KNOCK_ACCEPTED
    await fire(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    accepted = await recv_type(bob, "KNOCK_ACCEPTED")
    assert accepted["from"] == "alice"
    # ENTER has ENTER_OK direct response to bob, VISITOR_JOINED broadcast to alice
    enter_ok = await send(bob, {"type": "ENTER", "target": "alice"})
    assert enter_ok["type"] == "ENTER_OK"
    assert enter_ok["room"]["owner"] == "alice"
    assert enter_ok["room"]["description"] == "爱丽丝的茶室"
    assert len(enter_ok["room"]["items"]) == 2
    joined = await recv_type(alice, "VISITOR_JOINED")
    assert joined["agent"] == "bob"
    # SAY broadcasts SAID to all in room including sender; use send() to capture bob's SAID
    bob_said = await send(bob, {"type": "SAY", "text": "你好"})
    assert bob_said["type"] == "SAID"
    said = await recv_type(alice, "SAID")
    assert said["from"] == "bob"
    assert said["text"] == "你好"
    # WHISPER has no direct response to sender; bob gets WHISPERED
    await fire(alice, {"type": "WHISPER", "target": "bob", "text": "欢迎光临"})
    whispered = await recv_type(bob, "WHISPERED")
    assert whispered["from"] == "alice"
    assert whispered["text"] == "欢迎光临"
    # HOME has HOME_OK direct response to bob, VISITOR_LEFT broadcast to alice
    home_ok = await send(bob, {"type": "HOME"})
    assert home_ok["type"] == "HOME_OK"
    assert home_ok["room"]["owner"] == "bob"
    left = await recv_type(alice, "VISITOR_LEFT")
    assert left["agent"] == "bob"


@pytest.mark.asyncio
async def test_three_players_in_room(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    carol = await client("carol", "cpass")

    async def enter(guest, guest_ws, host_name):
        await fire(guest_ws, {"type": "KNOCK", "target": host_name})
        await recv_type(alice, "KNOCK_RECEIVED")
        await fire(alice, {"type": "KNOCK_REPLY", "to": guest, "accept": True})
        await recv_type(guest_ws, "KNOCK_ACCEPTED")
        enter_ok = await send(guest_ws, {"type": "ENTER", "target": host_name})
        assert enter_ok["type"] == "ENTER_OK"
        await recv_type(alice, "VISITOR_JOINED")

    await enter("bob", bob, "alice")
    await enter("carol", carol, "alice")
    # SAY from alice; she gets SAID broadcast too
    alice_said = await send(alice, {"type": "SAY", "text": "欢迎大家"})
    assert alice_said["type"] == "SAID"
    bob_said = await recv_type(bob, "SAID")
    carol_said = await recv_type(carol, "SAID")
    assert all(m["text"] == "欢迎大家" for m in [alice_said, bob_said, carol_said])


@pytest.mark.asyncio
async def test_disconnect_cleanup(client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    await fire(bob, {"type": "KNOCK", "target": "alice"})
    await recv_type(alice, "KNOCK_RECEIVED")
    await fire(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")
    enter_ok = await send(bob, {"type": "ENTER", "target": "alice"})
    assert enter_ok["type"] == "ENTER_OK"
    await recv_type(alice, "VISITOR_JOINED")
    await bob.close()
    left = await recv_type(alice, "VISITOR_LEFT", timeout=3.0)
    assert left["agent"] == "bob"
