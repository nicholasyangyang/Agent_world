import json
import pytest
import websockets
from tests.conftest import send, recv_type, fire


@pytest.mark.asyncio
async def test_set_description(client):
    ws = await client("alice", "pass")
    resp = await send(ws, {"type": "SET_DESC", "description": "星空咖啡馆"})
    assert resp["type"] == "DESC_UPDATED"
    resp = await send(ws, {"type": "LOOK"})
    assert resp["type"] == "LOOK_RESULT"
    assert resp["room"]["description"] == "星空咖啡馆"


@pytest.mark.asyncio
async def test_place_item(client):
    ws = await client("alice", "pass")
    resp = await send(ws, {
        "type": "PLACE_ITEM", "icon": "☕", "name": "咖啡机", "description": "自动续杯"
    })
    assert resp["type"] == "ITEM_PLACED"
    assert resp["item"]["name"] == "咖啡机"
    resp = await send(ws, {"type": "LOOK"})
    names = [i["name"] for i in resp["room"]["items"]]
    assert "咖啡机" in names


@pytest.mark.asyncio
async def test_place_duplicate_name(client):
    ws = await client("alice", "pass")
    await send(ws, {"type": "PLACE_ITEM", "icon": "☕", "name": "咖啡机", "description": ""})
    resp = await send(ws, {"type": "PLACE_ITEM", "icon": "🍵", "name": "咖啡机", "description": ""})
    assert resp["type"] == "ERROR"


@pytest.mark.asyncio
async def test_remove_item(client):
    ws = await client("alice", "pass")
    await send(ws, {"type": "PLACE_ITEM", "icon": "☕", "name": "咖啡机", "description": ""})
    resp = await send(ws, {"type": "REMOVE_ITEM", "name": "咖啡机"})
    assert resp["type"] == "ITEM_REMOVED"
    resp = await send(ws, {"type": "LOOK"})
    names = [i["name"] for i in resp["room"]["items"]]
    assert "咖啡机" not in names


@pytest.mark.asyncio
async def test_remove_nonexistent(client):
    ws = await client("alice", "pass")
    resp = await send(ws, {"type": "REMOVE_ITEM", "name": "不存在的物品"})
    assert resp["type"] == "ERROR"


@pytest.mark.asyncio
async def test_look_room(client):
    ws = await client("alice", "pass")
    await send(ws, {"type": "SET_DESC", "description": "我的房间"})
    await send(ws, {"type": "PLACE_ITEM", "icon": "📚", "name": "书架", "description": "满是书"})
    resp = await send(ws, {"type": "LOOK"})
    assert resp["type"] == "LOOK_RESULT"
    assert "room" in resp
    assert resp["room"]["description"] == "我的房间"
    assert any(i["name"] == "书架" for i in resp["room"]["items"])
    assert "owner" in resp["room"]


@pytest.mark.asyncio
async def test_look_specific_item(client):
    ws = await client("alice", "pass")
    await send(ws, {"type": "PLACE_ITEM", "icon": "☕", "name": "吧台", "description": "三杯拿铁"})
    resp = await send(ws, {"type": "LOOK", "item_name": "吧台"})
    assert resp["type"] == "LOOK_RESULT"
    assert resp["item"]["name"] == "吧台"
    assert resp["item"]["description"] == "三杯拿铁"


@pytest.mark.asyncio
async def test_look_nonexistent_item(client):
    ws = await client("alice", "pass")
    resp = await send(ws, {"type": "LOOK", "item_name": "不存在"})
    assert resp["type"] == "ERROR"


@pytest.mark.asyncio
async def test_cannot_modify_others_room(server, client):
    alice = await client("alice", "apass")
    bob = await client("bob", "bpass")
    await fire(bob, {"type": "KNOCK", "target": "alice"})
    await recv_type(alice, "KNOCK_RECEIVED")
    await fire(alice, {"type": "KNOCK_REPLY", "to": "bob", "accept": True})
    await recv_type(bob, "KNOCK_ACCEPTED")
    resp = await send(bob, {"type": "ENTER", "target": "alice"})
    assert resp["type"] == "ENTER_OK"
    assert resp["type"] == "ENTER_OK"
    resp = await send(bob, {"type": "PLACE_ITEM", "icon": "🎸", "name": "吉他", "description": ""})
    assert resp["type"] == "ERROR"
    resp = await send(bob, {"type": "REMOVE_ITEM", "name": "something"})
    assert resp["type"] == "ERROR"
    resp = await send(bob, {"type": "SET_DESC", "description": "hacked"})
    assert resp["type"] == "ERROR"
