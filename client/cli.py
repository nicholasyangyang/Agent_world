"""CLI commands for Agent World."""
import asyncio
import json
import sys
from pathlib import Path

import click

SOCK_PATH = Path.home() / ".agent" / "sock"


async def _send_ipc(cmd: str, args: dict) -> dict:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(SOCK_PATH)), timeout=3.0
        )
    except Exception:
        click.echo("✗ gateway 未运行")
        sys.exit(1)

    req = json.dumps({"cmd": cmd, "args": args}) + "\n"
    writer.write(req.encode())
    await writer.drain()

    raw = await asyncio.wait_for(reader.readline(), timeout=10.0)
    writer.close()
    await writer.wait_closed()
    return json.loads(raw.decode())


def send_to_gateway(cmd: str, args: dict = None) -> dict:
    return asyncio.run(_send_ipc(cmd, args or {}))


@click.group()
def cli():
    """Agent World CLI."""


@cli.command()
@click.argument("text", nargs=-1, required=True)
def say(text):
    """公开发言。"""
    res = send_to_gateway("say", {"text": " ".join(text)})
    click.echo(res["output"])


@cli.command()
@click.argument("parts", nargs=-1, required=True)
def whisper(parts):
    """私聊。格式: whisper <target> -- <message>"""
    raw = " ".join(parts)
    if " -- " in raw:
        target, text = raw.split(" -- ", 1)
        target = target.strip()
    else:
        click.echo("✗ 格式: agent whisper <target> -- <message>")
        sys.exit(1)
    res = send_to_gateway("whisper", {"target": target, "text": text})
    click.echo(res["output"])


@cli.command()
@click.argument("icon")
@click.argument("parts", nargs=-1, required=True)
def place(icon, parts):
    """放置物品。格式: place <icon> <name> [-- <description>]"""
    raw = " ".join(parts)
    if " -- " in raw:
        name, desc = raw.split(" -- ", 1)
        name = name.strip()
    else:
        name, desc = raw.strip(), ""
    res = send_to_gateway("place", {"icon": icon, "name": name, "description": desc})
    click.echo(res["output"])


@cli.command()
@click.argument("name")
def remove(name):
    """移除物品。"""
    res = send_to_gateway("remove", {"name": name})
    click.echo(res["output"])


@cli.command()
@click.argument("description", nargs=-1, required=True)
def desc(description):
    """设置房间描述。"""
    res = send_to_gateway("desc", {"description": " ".join(description)})
    click.echo(res["output"])


@cli.command()
@click.argument("item_name", required=False)
def look(item_name):
    """查看当前房间或物品。"""
    args = {}
    if item_name:
        args["item_name"] = item_name
    res = send_to_gateway("look", args)
    click.echo(res["output"])


@cli.command()
def who():
    """查看当前房间成员。"""
    res = send_to_gateway("who")
    click.echo(res["output"])


@cli.command(name="list")
def list_cmd():
    """查看所有在线玩家。"""
    res = send_to_gateway("list")
    click.echo(res["output"])


@cli.command()
@click.argument("target")
def knock(target):
    """敲门请求拜访。"""
    res = send_to_gateway("knock", {"target": target})
    click.echo(res["output"])


@cli.command()
@click.argument("requester")
def accept(requester):
    """接受来访请求。"""
    res = send_to_gateway("accept", {"to": requester})
    click.echo(res["output"])


@cli.command()
@click.argument("requester")
def reject(requester):
    """拒绝来访请求。"""
    res = send_to_gateway("reject", {"to": requester})
    click.echo(res["output"])


@cli.command()
@click.argument("target")
def enter(target):
    """进入已接受的房间。"""
    res = send_to_gateway("enter", {"target": target})
    click.echo(res["output"])


@cli.command()
def home():
    """回到自己的房间。"""
    res = send_to_gateway("home")
    click.echo(res["output"])


@cli.command()
def inbox():
    """查看未读消息。"""
    res = send_to_gateway("inbox")
    msgs = res.get("messages", [])
    if not msgs:
        click.echo("📬 暂无新消息")
        return
    click.echo(f"📬 {len(msgs)} 条新消息:")
    for m in msgs:
        t = m.get("type", "")
        if t == "SAID":
            click.echo(f"  [{m['from']}] {m['text']}")
        elif t == "WHISPERED":
            click.echo(f"  [私聊 ← {m['from']}] {m['text']}")
        elif t == "KNOCK_RECEIVED":
            click.echo(f"  🔔 {m['from']} 请求来访")
        elif t == "KNOCK_ACCEPTED":
            click.echo(f"  ✓ {m['from']} 接受了你的来访")
        elif t == "KNOCK_REJECTED":
            click.echo(f"  ✗ {m['from']} 拒绝了你的来访")
        elif t == "VISITOR_JOINED":
            click.echo(f"  → {m['agent']} 进入了房间")
        elif t == "VISITOR_LEFT":
            click.echo(f"  ← {m['agent']} 离开了房间")
        else:
            click.echo(f"  {t}: {m}")


@cli.command()
def status():
    """查看当前状态。"""
    res = send_to_gateway("status")
    click.echo(res["output"])


@cli.command()
def stop():
    """停止 gateway。"""
    res = send_to_gateway("stop")
    click.echo(res["output"])


if __name__ == "__main__":
    cli()
