import asyncio
import json
import logging
import signal
import sys
from types import SimpleNamespace

import websockets

import protocol as P
from server import db as DB
from server.handlers import handle_auth, dispatch, broadcast_to_room

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HOST = "0.0.0.0"
PORT = 8765


def make_state(database) -> SimpleNamespace:
    return SimpleNamespace(
        db=database,
        connections={},
        locations={},
        pending_knocks={},
        accepted_knocks={},
    )


async def on_connect(ws, state: SimpleNamespace) -> None:
    agent_id = None
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
        msg = json.loads(raw)
        if msg.get("type") != P.AUTH:
            await ws.close()
            return
        agent_id = await handle_auth(ws, msg, state)
        if agent_id is None:
            return
        async for raw in ws:
            msg = json.loads(raw)
            await dispatch(ws, msg, agent_id, state)
    except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError):
        pass
    except json.JSONDecodeError:
        pass
    finally:
        if agent_id and agent_id in state.connections:
            del state.connections[agent_id]
            old_room = state.locations.pop(agent_id, None)
            if old_room:
                await broadcast_to_room(
                    state, old_room,
                    {"type": P.VISITOR_LEFT, "agent": agent_id, "room": old_room}
                )
            logger.info("Agent disconnected: %s", agent_id)


async def create_server(database, host: str = HOST, port: int = PORT):
    state = make_state(database)

    async def handler(ws):
        await on_connect(ws, state)

    server = await websockets.serve(handler, host, port)
    return state, server


async def main() -> None:
    database = await DB.init_db()
    state, server = await create_server(database)
    logger.info("Server started on %s:%d", HOST, PORT)

    loop = asyncio.get_running_loop()
    stop = loop.create_future()

    def _handle_signal():
        stop.set_result(None)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    await stop
    server.close()
    await server.wait_closed()
    await database.close()
    logger.info("Server stopped.")


if __name__ == "__main__":
    asyncio.run(main())
