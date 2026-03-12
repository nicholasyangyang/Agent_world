import json
import logging
from types import SimpleNamespace
from typing import Any
import websockets

import protocol as P
from server import db as DB

logger = logging.getLogger(__name__)


async def send_msg(ws, msg: dict) -> None:
    await ws.send(json.dumps(msg))


async def send_error(ws, reason: str) -> None:
    await send_msg(ws, {"type": P.ERROR, "reason": reason})


async def broadcast_to_room(
    state: SimpleNamespace, room_owner_id: str, msg: dict, exclude: str = None
) -> None:
    for aid, loc in list(state.locations.items()):
        actual_room = loc if loc else aid
        if actual_room == room_owner_id and aid != exclude:
            if aid in state.connections:
                try:
                    await state.connections[aid].send(json.dumps(msg))
                except Exception:
                    pass


def current_room(state: SimpleNamespace, agent_id: str) -> str:
    loc = state.locations.get(agent_id)
    return loc if loc else agent_id


def is_in_own_room(state: SimpleNamespace, agent_id: str) -> bool:
    return state.locations.get(agent_id) is None


async def handle_auth(ws, msg: dict, state: SimpleNamespace) -> str | None:
    name = msg.get("name", "").strip()
    password = msg.get("password", "")
    if not name or not password:
        await send_msg(ws, {"type": P.AUTH_FAIL, "reason": "name and password required"})
        return None
    if name in state.connections:
        await send_msg(ws, {"type": P.AUTH_FAIL, "reason": "already online"})
        return None
    agent = await DB.get_agent(state.db, name)
    pw_hash = DB.hash_password(password)
    if agent is None:
        agent = await DB.create_agent(state.db, name, pw_hash)
        logger.info("Registered new agent: %s", name)
    elif agent["password_hash"] != pw_hash:
        await send_msg(ws, {"type": P.AUTH_FAIL, "reason": "wrong password"})
        return None
    state.connections[name] = ws
    state.locations[name] = None
    room_data = await DB.get_room(state.db, name)
    room_data["visitors"] = [
        aid for aid, loc in state.locations.items() if loc == name
    ]
    await send_msg(ws, {"type": P.AUTH_OK, "agent_id": name, "room": room_data})
    logger.info("Agent authenticated: %s", name)
    return name


async def handle_look(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    item_name = msg.get("item_name")
    room_owner = current_room(state, agent_id)
    if item_name:
        item = await DB.get_item(state.db, room_owner, item_name)
        if item is None:
            await send_error(ws, f"物品 '{item_name}' 不存在")
            return
        await send_msg(ws, {"type": P.LOOK_RESULT, "item": item})
    else:
        room_data = await DB.get_room(state.db, room_owner)
        room_data["owner"] = room_owner
        room_data["visitors"] = [
            aid for aid, loc in state.locations.items() if loc == room_owner
        ]
        await send_msg(ws, {"type": P.LOOK_RESULT, "room": room_data})


async def handle_set_desc(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    if not is_in_own_room(state, agent_id):
        await send_error(ws, "只能在自己房间修改描述")
        return
    desc = msg.get("description", "")
    await DB.update_room_desc(state.db, agent_id, desc)
    await send_msg(ws, {"type": P.DESC_UPDATED})


async def handle_place_item(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    if not is_in_own_room(state, agent_id):
        await send_error(ws, "只能在自己房间放置物品")
        return
    icon = msg.get("icon", "")
    name = msg.get("name", "").strip()
    desc = msg.get("description", "")
    if not icon or not name:
        await send_error(ws, "icon 和 name 不能为空")
        return
    try:
        item = await DB.add_item(state.db, agent_id, icon, name, desc)
    except Exception:
        await send_error(ws, f"物品 '{name}' 已存在")
        return
    await send_msg(ws, {"type": P.ITEM_PLACED, "item": item})


async def handle_remove_item(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    if not is_in_own_room(state, agent_id):
        await send_error(ws, "只能在自己房间移除物品")
        return
    name = msg.get("name", "").strip()
    if not name:
        await send_error(ws, "name 不能为空")
        return
    removed = await DB.remove_item(state.db, agent_id, name)
    if not removed:
        await send_error(ws, f"物品 '{name}' 不存在")
        return
    await send_msg(ws, {"type": P.ITEM_REMOVED, "name": name})


async def handle_who(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    room_owner = current_room(state, agent_id)
    visitors = [aid for aid, loc in state.locations.items() if loc == room_owner]
    await send_msg(ws, {"type": P.WHO_RESULT, "room": room_owner, "visitors": visitors})


async def handle_list(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    online = list(state.connections.keys())
    await send_msg(ws, {"type": P.LIST_RESULT, "agents": online})


async def handle_knock(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    target = msg.get("target", "").strip()
    if not target:
        await send_error(ws, "target 不能为空")
        return
    if target not in state.connections:
        await send_error(ws, "目标玩家不在线")
        return
    if state.locations.get(target) is not None:
        await send_error(ws, "目标玩家不在自己房间")
        return
    if target not in state.pending_knocks:
        state.pending_knocks[target] = set()
    state.pending_knocks[target].add(agent_id)
    target_ws = state.connections[target]
    await send_msg(target_ws, {"type": P.KNOCK_RECEIVED, "from": agent_id})


async def handle_knock_reply(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    if not is_in_own_room(state, agent_id):
        await send_error(ws, "只能在自己房间回应来访")
        return
    requester = msg.get("to", "").strip()
    accept = msg.get("accept", False)
    knocks = state.pending_knocks.get(agent_id, set())
    if requester not in knocks:
        await send_error(ws, "没有该用户的来访请求")
        return
    knocks.discard(requester)
    if requester not in state.connections:
        return
    req_ws = state.connections[requester]
    if accept:
        if agent_id not in state.accepted_knocks:
            state.accepted_knocks[agent_id] = set()
        state.accepted_knocks[agent_id].add(requester)
        await send_msg(req_ws, {"type": P.KNOCK_ACCEPTED, "from": agent_id})
    else:
        await send_msg(req_ws, {"type": P.KNOCK_REJECTED, "from": agent_id})


async def handle_enter(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    target = msg.get("target", "").strip()
    if not target:
        await send_error(ws, "target 不能为空")
        return
    accepted = state.accepted_knocks.get(target, set())
    if agent_id not in accepted:
        await send_error(ws, "未被接受，无法进入")
        return
    accepted.discard(agent_id)
    old_room = current_room(state, agent_id)
    if old_room != agent_id:
        state.locations[agent_id] = None
        await broadcast_to_room(
            state, old_room,
            {"type": P.VISITOR_LEFT, "agent": agent_id, "room": old_room},
            exclude=agent_id
        )
    state.locations[agent_id] = target
    room_data = await DB.get_room(state.db, target)
    room_data["owner"] = target
    room_data["visitors"] = [
        aid for aid, loc in state.locations.items() if loc == target
    ]
    await send_msg(ws, {"type": P.ENTER_OK, "room": room_data})
    await broadcast_to_room(
        state, target,
        {"type": P.VISITOR_JOINED, "agent": agent_id, "room": target},
        exclude=agent_id
    )


async def handle_say(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    text = msg.get("text", "").strip()
    if not text:
        await send_error(ws, "text 不能为空")
        return
    room_owner = current_room(state, agent_id)
    await broadcast_to_room(
        state, room_owner,
        {"type": P.SAID, "from": agent_id, "text": text, "room": room_owner}
    )


async def handle_whisper(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    target = msg.get("target", "").strip()
    text = msg.get("text", "").strip()
    if not target or not text:
        await send_error(ws, "target 和 text 不能为空")
        return
    if target not in state.connections:
        await send_error(ws, "目标玩家不在线")
        return
    target_ws = state.connections[target]
    await send_msg(target_ws, {"type": P.WHISPERED, "from": agent_id, "text": text})


async def handle_home(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    old_room = current_room(state, agent_id)
    if old_room != agent_id:
        state.locations[agent_id] = None
        await broadcast_to_room(
            state, old_room,
            {"type": P.VISITOR_LEFT, "agent": agent_id, "room": old_room},
            exclude=agent_id
        )
    room_data = await DB.get_room(state.db, agent_id)
    room_data["owner"] = agent_id
    room_data["visitors"] = [
        aid for aid, loc in state.locations.items() if loc == agent_id
    ]
    await send_msg(ws, {"type": P.HOME_OK, "room": room_data})


async def dispatch(ws, msg: dict, agent_id: str, state: SimpleNamespace) -> None:
    msg_type = msg.get("type")
    handlers = {
        P.SET_DESC: handle_set_desc,
        P.PLACE_ITEM: handle_place_item,
        P.REMOVE_ITEM: handle_remove_item,
        P.LOOK: handle_look,
        P.WHO: handle_who,
        P.LIST: handle_list,
        P.KNOCK: handle_knock,
        P.KNOCK_REPLY: handle_knock_reply,
        P.ENTER: handle_enter,
        P.SAY: handle_say,
        P.WHISPER: handle_whisper,
        P.HOME: handle_home,
    }
    handler = handlers.get(msg_type)
    if handler:
        await handler(ws, msg, agent_id, state)
    else:
        await send_error(ws, f"未知消息类型: {msg_type}")
