"""
Gateway daemon: maintains WebSocket connection to server,
exposes IPC via Unix Domain Socket.
"""
import asyncio
import atexit
import json
import logging
import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

import websockets

import protocol as P

logger = logging.getLogger(__name__)

SOCK_PATH = Path.home() / ".agent" / "sock"
SERVER_URL_DEFAULT = "ws://127.0.0.1:8765"
IPC_TIMEOUT = 10.0


class GatewayState:
    def __init__(self, agent_id: str, ws):
        self.agent_id = agent_id
        self.ws = ws
        self.message_queue: list[dict] = []
        self.pending_response: asyncio.Queue = asyncio.Queue()
        self.current_room: str | None = None
        self._shutdown_event: asyncio.Event = asyncio.Event()


async def ws_recv_loop(state: GatewayState) -> None:
    try:
        async for raw in state.ws:
            msg = json.loads(raw)
            msg_type = msg.get("type", "")
            if msg_type in P.PUSH_TYPES:
                state.message_queue.append(msg)
            else:
                await state.pending_response.put(msg)
            if msg_type == "ENTER_OK":
                state.current_room = msg.get("room", {}).get("owner")
            elif msg_type == "HOME_OK":
                state.current_room = None
    except Exception as e:
        logger.error("WebSocket recv error: %s", e)


async def handle_ipc_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: GatewayState,
) -> None:
    try:
        raw = await asyncio.wait_for(reader.readline(), timeout=5.0)
        req = json.loads(raw.decode())
    except Exception:
        writer.close()
        return

    cmd = req.get("cmd")
    args = req.get("args", {})
    response = await handle_ipc_cmd(cmd, args, state)

    writer.write((json.dumps(response) + "\n").encode())
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def handle_ipc_cmd(cmd: str, args: dict, state: GatewayState) -> dict:
    if cmd == "inbox":
        msgs = list(state.message_queue)
        state.message_queue.clear()
        return {"ok": True, "messages": msgs}

    if cmd == "status":
        room = state.current_room or state.agent_id
        return {"ok": True, "output": f"✓ {state.agent_id} @ {room}"}

    if cmd == "stop":
        state._shutdown_event.set()
        return {"ok": True, "output": "✓ gateway 正在停止"}

    ws_msg = _build_ws_msg(cmd, args)
    if ws_msg is None:
        return {"ok": False, "output": f"✗ 未知命令: {cmd}"}

    try:
        await state.ws.send(json.dumps(ws_msg))
    except Exception as e:
        return {"ok": False, "output": f"✗ 发送失败: {e}"}

    if cmd in ("say", "whisper", "accept", "reject"):
        return {"ok": True, "output": "✓ 已发送"}

    if cmd == "knock":
        return {"ok": True, "output": f"⏳ 已向 {args.get('target')} 发送拜访请求"}

    try:
        resp = await asyncio.wait_for(state.pending_response.get(), timeout=IPC_TIMEOUT)
    except asyncio.TimeoutError:
        return {"ok": False, "output": "✗ 服务器响应超时"}

    return _format_response(cmd, resp, state)


def _build_ws_msg(cmd: str, args: dict) -> dict | None:
    mapping = {
        "desc": lambda a: {"type": P.SET_DESC, "description": a.get("description", "")},
        "place": lambda a: {"type": P.PLACE_ITEM, **a},
        "remove": lambda a: {"type": P.REMOVE_ITEM, "name": a.get("name", "")},
        "look": lambda a: {"type": P.LOOK, **({} if not a.get("item_name") else {"item_name": a["item_name"]})},
        "who": lambda a: {"type": P.WHO},
        "list": lambda a: {"type": P.LIST},
        "knock": lambda a: {"type": P.KNOCK, "target": a.get("target", "")},
        "accept": lambda a: {"type": P.KNOCK_REPLY, "to": a.get("to", ""), "accept": True},
        "reject": lambda a: {"type": P.KNOCK_REPLY, "to": a.get("to", ""), "accept": False},
        "enter": lambda a: {"type": P.ENTER, "target": a.get("target", "")},
        "say": lambda a: {"type": P.SAY, "text": a.get("text", "")},
        "whisper": lambda a: {"type": P.WHISPER, **a},
        "home": lambda a: {"type": P.HOME},
    }
    factory = mapping.get(cmd)
    return factory(args) if factory else None


def _format_response(cmd: str, resp: dict, state: GatewayState) -> dict:
    msg_type = resp.get("type", "")
    if msg_type == P.ERROR:
        return {"ok": False, "output": f"✗ {resp.get('reason', '未知错误')}"}

    if msg_type == P.DESC_UPDATED:
        return {"ok": True, "output": "✓ 描述已更新"}

    if msg_type == P.ITEM_PLACED:
        item = resp["item"]
        return {"ok": True, "output": f"✓ 已放置: {item['icon']} {item['name']}"}

    if msg_type == P.ITEM_REMOVED:
        return {"ok": True, "output": f"✓ 已移除: {resp.get('name', '')}"}

    if msg_type == P.LOOK_RESULT:
        if "item" in resp:
            i = resp["item"]
            return {"ok": True, "output": f"{i['icon']} {i['name']}\n  {i['description']}"}
        room = resp["room"]
        items_str = " | ".join(f"{i['icon']} {i['name']}" for i in room.get("items", []))
        visitors_str = ", ".join(room.get("visitors", []))
        lines = [
            f"🏠 {room['owner']} 的房间 — \"{room.get('description', '')}\"",
            f"物品: {items_str or '（空）'}",
            f"在线: {visitors_str or '（无）'}",
        ]
        return {"ok": True, "output": "\n".join(lines)}

    if msg_type == P.WHO_RESULT:
        visitors = ", ".join(resp.get("visitors", []))
        return {"ok": True, "output": f"房间成员: {visitors or '（无）'}"}

    if msg_type == P.LIST_RESULT:
        agents = ", ".join(resp.get("agents", []))
        return {"ok": True, "output": f"在线玩家: {agents}"}

    if msg_type in (P.ENTER_OK, P.HOME_OK):
        room = resp["room"]
        items_str = " | ".join(f"{i['icon']} {i['name']}" for i in room.get("items", []))
        visitors_str = ", ".join(room.get("visitors", []))
        lines = [
            f"🏠 {room['owner']} 的房间 — \"{room.get('description', '')}\"",
            f"物品: {items_str or '（空）'}",
            f"在线: {visitors_str or '（无）'}",
        ]
        return {"ok": True, "output": "\n".join(lines)}

    return {"ok": True, "output": f"✓ {msg_type}"}


async def connect_and_auth(server_url: str, name: str, password: str) -> GatewayState:
    ws = await websockets.connect(server_url)
    await ws.send(json.dumps({"type": P.AUTH, "name": name, "password": password}))
    resp = json.loads(await ws.recv())
    if resp["type"] != P.AUTH_OK:
        await ws.close()
        raise RuntimeError(f"AUTH failed: {resp.get('reason', '')}")
    return GatewayState(agent_id=name, ws=ws)


def cleanup_sock():
    try:
        SOCK_PATH.unlink(missing_ok=True)
    except Exception:
        pass


async def run_gateway(server_url: str, name: str, password: str) -> None:
    sock_dir = SOCK_PATH.parent
    sock_dir.mkdir(parents=True, exist_ok=True)

    if SOCK_PATH.exists():
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(SOCK_PATH)), timeout=1.0
            )
            writer.close()
            print("✗ gateway 已在运行")
            return
        except Exception:
            SOCK_PATH.unlink(missing_ok=True)

    state = await connect_and_auth(server_url, name, password)
    print(f"✓ 已连接为 {name}")

    atexit.register(cleanup_sock)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, state._shutdown_event.set)

    async def ipc_handler(reader, writer):
        await handle_ipc_connection(reader, writer, state)

    ipc_server = await asyncio.start_unix_server(ipc_handler, path=str(SOCK_PATH))

    recv_task = asyncio.create_task(ws_recv_loop(state))

    try:
        async with ipc_server:
            await state._shutdown_event.wait()
    except Exception:
        pass
    finally:
        recv_task.cancel()
        await state.ws.close()
        cleanup_sock()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Agent World Gateway")
    parser.add_argument("name", help="Agent name")
    parser.add_argument("password", help="Agent password")
    parser.add_argument("--server", default=SERVER_URL_DEFAULT, help="Server URL")
    args = parser.parse_args()
    asyncio.run(run_gateway(args.server, args.name, args.password))


if __name__ == "__main__":
    main()
