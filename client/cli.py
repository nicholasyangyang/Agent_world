"""CLI commands for Agent World (Nostr-based)."""
import asyncio
import json
import logging
import sys
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "Default_config" / "cli_config.json"

CLI_DEFAULTS = {
    "sock_path": "~/.agent/sock",
    "key_path": "~/.agent/key.json",
    "db_path": "~/.agent/contacts.db",
    "debug": False,
}

_sock_path: Path = Path.home() / ".agent" / "sock"
_debug: bool = False


def _load_config(config_path: str | None) -> dict:
    cfg = dict(CLI_DEFAULTS)
    path = Path(config_path or DEFAULT_CONFIG).expanduser()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


async def _send_ipc(cmd: str, args: dict) -> dict:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(_sock_path)), timeout=3.0
        )
    except Exception:
        click.echo("✗ gateway 未运行，请先启动: python -m client.gateway")
        sys.exit(1)

    req = json.dumps({"cmd": cmd, "args": args}) + "\n"
    if _debug:
        click.echo(f"[DEBUG] → {req.strip()}")
    writer.write(req.encode())
    await writer.drain()

    raw = await asyncio.wait_for(reader.readline(), timeout=10.0)
    writer.close()
    await writer.wait_closed()
    resp = json.loads(raw.decode())
    if _debug:
        click.echo(f"[DEBUG] ← {json.dumps(resp, ensure_ascii=False)[:200]}")
    return resp


def send(cmd: str, args: dict = None) -> dict:
    return asyncio.run(_send_ipc(cmd, args or {}))


# --- Click Group ---

@click.group()
@click.option("--config", default=None, help="Path to config JSON")
@click.option("--debug", is_flag=True, help="Enable debug output")
def cli(config, debug):
    """Agent World CLI (Nostr)"""
    global _sock_path, _debug
    cfg = _load_config(config)
    _sock_path = Path(cfg["sock_path"]).expanduser()
    _debug = debug or cfg.get("debug", False)
    if _debug:
        logging.basicConfig(level=logging.DEBUG)


# --- Messaging ---

@cli.command()
@click.argument("target")
@click.argument("text", nargs=-1, required=True)
def msg(target, text):
    """发送 NIP-17 加密私信。"""
    res = send("msg", {"target": target, "text": " ".join(text)})
    click.echo(res["output"])


@cli.command()
def inbox():
    """查看未读消息。"""
    res = send("inbox")
    messages = res.get("messages", [])
    notifications = res.get("notifications", [])

    if not messages and not notifications:
        click.echo("📬 暂无新消息")
        return

    if notifications:
        click.echo(f"📬 {len(notifications)} 条通知:")
        for n in notifications:
            t = n.get("type", "")
            if t == "dm":
                click.echo(f"  [{n.get('from', '?')[:12]}..] {n.get('text', '')}")
            elif t == "group_invite":
                click.echo(f"  📨 收到群组 '{n.get('group')}' 邀请 (来自 {n.get('from', '?')[:12]}..)")
            elif t == "group_accept":
                click.echo(f"  ✓ {n.get('from', '?')[:12]}.. 加入了 '{n.get('group')}'")
            elif t == "group_leave":
                click.echo(f"  👋 {n.get('from', '?')[:12]}.. 离开了 '{n.get('group')}'")
            else:
                click.echo(f"  {t}: {n}")

    if messages:
        click.echo(f"📬 {len(messages)} 条消息:")
        for m in messages:
            from_npub = m.get("from_npub", "?")
            text_val = m.get("text", "")
            group = m.get("group_name")
            if group:
                click.echo(f"  [{group}] {from_npub[:12]}.. : {text_val}")
            else:
                click.echo(f"  [{from_npub[:12]}..] {text_val}")


# --- Contacts ---

@cli.command()
def contacts():
    """查看联系人列表。"""
    res = send("contacts")
    click.echo(res["output"])


@cli.command()
@click.argument("npub")
@click.argument("nickname")
def add(npub, nickname):
    """添加联系人备注。"""
    res = send("add_contact", {"npub": npub, "nickname": nickname})
    click.echo(res["output"])


@cli.command()
@click.argument("nickname")
def rm(nickname):
    """删除联系人。"""
    res = send("rm_contact", {"nickname": nickname})
    click.echo(res["output"])


@cli.command()
def whoami():
    """显示自己的 npub。"""
    res = send("whoami")
    click.echo(res["output"])


# --- Groups ---

@cli.group(name="group")
def group_cmd():
    """群组管理。"""


@group_cmd.command(name="create")
@click.argument("name")
def group_create(name):
    """创建群组。"""
    res = send("group_create", {"name": name})
    click.echo(res["output"])


@group_cmd.command(name="invite")
@click.argument("group_name")
@click.argument("nickname")
def group_invite(group_name, nickname):
    """邀请联系人加入群组。"""
    res = send("group_invite", {"group": group_name, "nickname": nickname})
    click.echo(res["output"])


@group_cmd.command(name="join")
@click.argument("inviter_npub")
@click.argument("group_name")
def group_join(inviter_npub, group_name):
    """接受群组邀请。"""
    res = send("group_join", {"npub": inviter_npub, "group": group_name})
    click.echo(res["output"])


@group_cmd.command(name="members")
@click.argument("group_name")
def group_members(group_name):
    """查看群组成员。"""
    res = send("group_members", {"group": group_name})
    click.echo(res["output"])


@group_cmd.command(name="leave")
@click.argument("group_name")
def group_leave(group_name):
    """离开群组。"""
    res = send("group_leave", {"group": group_name})
    click.echo(res["output"])


@group_cmd.command(name="list")
def group_list():
    """列出所有群组。"""
    res = send("groups")
    click.echo(res["output"])


# --- Home TUI ---

@cli.command()
@click.argument("group_name")
def home(group_name):
    """进入群组 Home TUI (坐标系统)。"""
    from client.tui import run_tui
    cfg = _load_config(None)
    sock = Path(cfg["sock_path"]).expanduser()
    run_tui(group_name, str(sock), _debug)


# --- System ---

@cli.command()
def status():
    """查看 gateway 状态。"""
    res = send("status")
    click.echo(res["output"])


@cli.command()
def stop():
    """停止 gateway。"""
    res = send("stop")
    click.echo(res["output"])


if __name__ == "__main__":
    cli()
