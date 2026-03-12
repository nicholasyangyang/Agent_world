"""
Gateway daemon: connects to Nostr relays, handles NIP-17 DMs,
exposes IPC via Unix Domain Socket for CLI.
"""
import asyncio
import atexit
import json
import logging
import signal
import sys
from pathlib import Path

from nostr_client import NostrDMClient, load_or_create_keys, npub_short
import local_db as DB

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "Default_config" / "gateway_config.json"

GATEWAY_DEFAULTS = {
    "relays": ["wss://relay.damus.io", "wss://nos.lol", "wss://relay.nostr.band"],
    "sock_path": "~/.agent/sock",
    "key_path": "~/.agent/key.json",
    "db_path": "~/.agent/contacts.db",
    "proxy": "",
    "debug": False,
}


def load_config(config_path: str | None) -> dict:
    cfg = dict(GATEWAY_DEFAULTS)
    path = Path(config_path or DEFAULT_CONFIG).expanduser()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


class GatewayState:
    def __init__(self, nostr: NostrDMClient, db, own_npub: str):
        self.nostr = nostr
        self.db = db
        self.own_npub = own_npub
        self.message_queue: list[dict] = []
        self.group_subscribers: dict[str, list[asyncio.StreamWriter]] = {}
        self._shutdown = asyncio.Event()
        self._connected_relays: list[str] = []
        self._msg_count = 0


async def handle_incoming_dm(state: GatewayState, sender_npub: str, content: str):
    """Process an incoming NIP-17 DM."""
    state._msg_count += 1

    # Try to parse as group protocol message
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "type" in data:
            await handle_group_message(state, sender_npub, data)
            return
    except (json.JSONDecodeError, KeyError):
        pass

    # Plain text DM — save to DB only (inbox reads from DB)
    display = await DB.get_display_name(state.db, sender_npub)
    await DB.save_message(state.db, sender_npub, content)
    logger.info("📩 DM from %s: %s", display, content[:80])


async def handle_group_message(state: GatewayState, sender_npub: str, data: dict):
    """Handle group protocol messages."""
    msg_type = data.get("type")
    group = data.get("group", "")
    from_npub = sender_npub  # Always use verified NIP-17 sender, ignore payload
    display = await DB.get_display_name(state.db, from_npub)

    if msg_type == "group_invite":
        state.message_queue.append({
            "type": "group_invite", "group": group, "from": from_npub
        })
        logger.info("📨 Group invite to '%s' from %s", group, display)

    elif msg_type == "group_accept":
        # Add member and broadcast updated member list
        if await DB.group_exists(state.db, group):
            await DB.add_member(state.db, group, from_npub)
            members = await DB.get_members(state.db, group)
            await broadcast_members_sync(state, group, members, exclude=from_npub)
            state.message_queue.append({
                "type": "group_accept", "group": group, "from": from_npub
            })
            logger.info("✓ %s joined group '%s'", display, group)

    elif msg_type == "group_members_sync":
        members = data.get("members", [])
        await DB.sync_members(state.db, group, members)
        state.message_queue.append({
            "type": "group_members_sync", "group": group, "members": members
        })
        logger.info("🔄 Group '%s' synced: %d members", group, len(members))

    elif msg_type == "group_position":
        x, y = data.get("x", 0), data.get("y", 0)
        # Forward to TUI subscribers
        event = {"type": "position", "group": group, "npub": from_npub, "x": x, "y": y}
        await push_to_group_subscribers(state, group, event)
        logger.debug("📍 %s moved to (%d,%d) in '%s'", display, x, y, group)

    elif msg_type == "group_leave":
        if await DB.group_exists(state.db, group):
            await DB.remove_member(state.db, group, from_npub)
        state.message_queue.append({
            "type": "group_leave", "group": group, "from": from_npub
        })
        event = {"type": "leave", "group": group, "npub": from_npub}
        await push_to_group_subscribers(state, group, event)
        logger.info("👋 %s left group '%s'", display, group)


async def broadcast_members_sync(
    state: GatewayState, group: str, members: list[str], exclude: str = None
):
    """Send group_members_sync to all members via NIP-17."""
    payload = json.dumps({
        "type": "group_members_sync", "group": group, "members": members
    })
    for npub in members:
        if npub != exclude and npub != state.own_npub:
            asyncio.create_task(state.nostr.send_dm(npub, payload))


async def push_to_group_subscribers(state: GatewayState, group: str, event: dict):
    """Push event to TUI subscribers for a group."""
    writers = state.group_subscribers.get(group, [])
    dead = []
    for w in writers:
        try:
            w.write((json.dumps(event) + "\n").encode())
            await w.drain()
        except Exception:
            dead.append(w)
    for w in dead:
        writers.remove(w)


# --- IPC ---

async def handle_ipc(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, state: GatewayState):
    try:
        raw = await asyncio.wait_for(reader.readline(), timeout=5.0)
        if not raw:
            writer.close()
            return
        req = json.loads(raw.decode())
    except Exception:
        writer.close()
        return

    cmd = req.get("cmd", "")
    args = req.get("args", {})
    logger.debug("IPC cmd: %s %s", cmd, args)

    # Streaming command for TUI
    if cmd == "group_subscribe":
        group = args.get("group", "")
        if group not in state.group_subscribers:
            state.group_subscribers[group] = []
        state.group_subscribers[group].append(writer)
        # Send initial ack
        writer.write((json.dumps({"ok": True, "type": "subscribed"}) + "\n").encode())
        await writer.drain()
        # Keep connection open — TUI will close when done
        return

    response = await handle_ipc_cmd(cmd, args, state)
    writer.write((json.dumps(response) + "\n").encode())
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def handle_ipc_cmd(cmd: str, args: dict, state: GatewayState) -> dict:
    if cmd == "status":
        return {
            "ok": True,
            "output": (
                f"npub: {state.own_npub}\n"
                f"Relays: {len(state._connected_relays)} connected\n"
                f"Messages received: {state._msg_count}"
            )
        }

    if cmd == "stop":
        state._shutdown.set()
        return {"ok": True, "output": "✓ gateway 正在停止"}

    if cmd == "whoami":
        return {"ok": True, "output": state.own_npub}

    if cmd == "inbox":
        unread = await DB.get_unread(state.db)
        await DB.mark_all_read(state.db)
        # Also drain push queue
        queued = list(state.message_queue)
        state.message_queue.clear()
        return {"ok": True, "messages": unread, "notifications": queued}

    if cmd == "msg":
        target_name = args.get("target", "")
        text = args.get("text", "")
        npub = await DB.resolve_name(state.db, target_name)
        if not npub:
            return {"ok": False, "output": f"✗ 未找到联系人: {target_name}"}
        display = await DB.get_display_name(state.db, npub)

        async def _bg_send():
            try:
                await state.nostr.send_dm(npub, text)
                logger.info("✓ DM to %s delivered", display)
            except Exception as e:
                logger.warning("✗ DM to %s failed: %s", display, e)

        asyncio.create_task(_bg_send())
        return {"ok": True, "output": f"✓ 已发送给 {display}"}

    if cmd == "contacts":
        contacts = await DB.get_contacts(state.db)
        if not contacts:
            return {"ok": True, "output": "暂无联系人"}
        lines = [f"  @{c['nickname']}  {c['npub'][:20]}.." for c in contacts]
        return {"ok": True, "output": "联系人:\n" + "\n".join(lines)}

    if cmd == "add_contact":
        npub = args.get("npub", "")
        nickname = args.get("nickname", "")
        if not npub.startswith("npub1") or not nickname:
            return {"ok": False, "output": "✗ 需要有效的 npub 和昵称"}
        await DB.add_contact(state.db, npub, nickname)
        return {"ok": True, "output": f"✓ 已添加 @{nickname}"}

    if cmd == "rm_contact":
        nickname = args.get("nickname", "")
        removed = await DB.remove_contact(state.db, nickname)
        if removed:
            return {"ok": True, "output": f"✓ 已删除 @{nickname}"}
        return {"ok": False, "output": f"✗ 未找到 @{nickname}"}

    # --- Group commands ---

    if cmd == "group_create":
        name = args.get("name", "")
        if await DB.group_exists(state.db, name):
            return {"ok": False, "output": f"✗ 群组 '{name}' 已存在"}
        await DB.create_group(state.db, name, state.own_npub)
        return {"ok": True, "output": f"✓ 已创建群组 '{name}'"}

    if cmd == "group_invite":
        group = args.get("group", "")
        nickname = args.get("nickname", "")
        npub = await DB.resolve_name(state.db, nickname)
        if not npub:
            return {"ok": False, "output": f"✗ 未找到联系人: {nickname}"}
        if not await DB.group_exists(state.db, group):
            return {"ok": False, "output": f"✗ 群组 '{group}' 不存在"}
        payload = json.dumps({
            "type": "group_invite", "group": group, "from_npub": state.own_npub
        })
        asyncio.create_task(state.nostr.send_dm(npub, payload))
        return {"ok": True, "output": f"✓ 已邀请 @{nickname} 加入 '{group}'"}

    if cmd == "group_join":
        inviter_npub = args.get("npub", "")
        group = args.get("group", "")
        if not inviter_npub or not group:
            return {"ok": False, "output": "✗ 需要 npub 和群组名"}
        payload = json.dumps({
            "type": "group_accept", "group": group, "from_npub": state.own_npub
        })
        asyncio.create_task(state.nostr.send_dm(inviter_npub, payload))
        # Add self to local group
        if not await DB.group_exists(state.db, group):
            await DB.create_group(state.db, group, state.own_npub)
        return {"ok": True, "output": f"✓ 已接受加入 '{group}'"}

    if cmd == "group_members":
        group = args.get("group", "")
        if not await DB.group_exists(state.db, group):
            return {"ok": False, "output": f"✗ 群组 '{group}' 不存在"}
        members = await DB.get_members(state.db, group)
        lines = []
        for m in members:
            display = await DB.get_display_name(state.db, m)
            marker = " (你)" if m == state.own_npub else ""
            lines.append(f"  {display}{marker}")
        return {"ok": True, "output": f"群组 '{group}' 成员:\n" + "\n".join(lines)}

    if cmd == "group_leave":
        group = args.get("group", "")
        if not await DB.group_exists(state.db, group):
            return {"ok": False, "output": f"✗ 群组 '{group}' 不存在"}
        members = await DB.get_members(state.db, group)
        payload = json.dumps({
            "type": "group_leave", "group": group, "from_npub": state.own_npub
        })
        for m in members:
            if m != state.own_npub:
                asyncio.create_task(state.nostr.send_dm(m, payload))
        await DB.remove_member(state.db, group, state.own_npub)
        await DB.delete_group(state.db, group)
        return {"ok": True, "output": f"✓ 已离开 '{group}'"}

    if cmd == "group_position":
        group = args.get("group", "")
        x, y = args.get("x", 0), args.get("y", 0)
        if not await DB.group_exists(state.db, group):
            return {"ok": False, "output": f"✗ 群组 '{group}' 不存在"}
        members = await DB.get_members(state.db, group)
        payload = json.dumps({
            "type": "group_position", "group": group,
            "x": x, "y": y, "from_npub": state.own_npub
        })
        for m in members:
            if m != state.own_npub:
                asyncio.create_task(state.nostr.send_dm(m, payload))
        return {"ok": True}

    if cmd == "groups":
        groups = await DB.get_groups(state.db)
        if not groups:
            return {"ok": True, "output": "暂无群组"}
        lines = [f"  {g}" for g in groups]
        return {"ok": True, "output": "群组列表:\n" + "\n".join(lines)}

    return {"ok": False, "output": f"✗ 未知命令: {cmd}"}


# --- Main ---

def make_cleanup(sock_path: Path):
    def cleanup():
        try:
            sock_path.unlink(missing_ok=True)
        except Exception:
            pass
    return cleanup


async def run_gateway(cfg: dict) -> None:
    sock_path = Path(cfg["sock_path"]).expanduser()
    key_path = cfg["key_path"]
    db_path = Path(cfg["db_path"]).expanduser()

    # Ensure directories
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Check existing gateway
    if sock_path.exists():
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(sock_path)), timeout=1.0
            )
            writer.close()
            print("✗ gateway 已在运行")
            return
        except Exception:
            sock_path.unlink(missing_ok=True)

    # Load keys
    keys = load_or_create_keys(key_path)
    own_npub = keys.public_key().to_bech32()

    # Init DB
    db = await DB.init_db(str(db_path))

    # Connect to Nostr
    nostr = NostrDMClient(keys, cfg["relays"], cfg.get("proxy", ""))
    connected_relays = await nostr.connect()

    state = GatewayState(nostr, db, own_npub)
    state._connected_relays = connected_relays

    # Print status
    proxy_str = cfg.get("proxy", "") or "none"
    print(f"✓ Agent World Gateway")
    print(f"  npub: {own_npub}")
    print(f"  Relays: {len(connected_relays)} connected ({', '.join(r.split('//')[1] if '//' in r else r for r in connected_relays)})")
    print(f"  Proxy: {proxy_str}")
    print(f"  Socket: {sock_path}")
    print(f"  Waiting for messages...")
    print()

    cleanup = make_cleanup(sock_path)
    atexit.register(cleanup)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, state._shutdown.set)

    # Start IPC server
    async def ipc_handler(reader, writer):
        await handle_ipc(reader, writer, state)

    ipc_server = await asyncio.start_unix_server(ipc_handler, path=str(sock_path))

    # Start Nostr listener
    async def dm_callback(sender_npub, content):
        await handle_incoming_dm(state, sender_npub, content)

    nostr_task = asyncio.create_task(nostr.subscribe_and_handle(dm_callback))

    try:
        async with ipc_server:
            await state._shutdown.wait()
    except Exception:
        pass
    finally:
        nostr_task.cancel()
        await nostr.disconnect()
        await db.close()
        cleanup()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Agent World Gateway (Nostr)")
    parser.add_argument("--config", default=None, help="Path to config JSON file")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    cfg = load_config(args.config)
    debug = args.debug or cfg.get("debug", False)
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s" if debug else "%(message)s"
    )

    asyncio.run(run_gateway(cfg))


if __name__ == "__main__":
    main()
