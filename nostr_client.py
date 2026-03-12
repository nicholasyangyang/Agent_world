"""Nostr SDK wrapper for NIP-17 encrypted direct messages."""
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional, Callable, Awaitable

from nostr_sdk import (
    Client, ClientBuilder, ClientOptions, Connection, ConnectionMode,
    Keys, PublicKey, SecretKey, Filter, Kind, NostrSigner, RelayUrl, Timestamp,
    HandleNotification, RelayMessage, Event, UnwrappedGift,
    Tag,
)

logger = logging.getLogger(__name__)


def load_or_create_keys(key_path: str | Path) -> Keys:
    """Load keys from key.json, or generate and save new ones."""
    path = Path(key_path).expanduser()
    if path.exists():
        data = json.loads(path.read_text())
        secret_key = SecretKey.parse(data["nsec"])
        keys = Keys(secret_key)
        logger.info("Loaded keys from %s", path)
        return keys

    keys = Keys.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps({
        "nsec": keys.secret_key().to_bech32(),
        "npub": keys.public_key().to_bech32(),
    }, indent=2)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    logger.info("Generated new keys, saved to %s", path)
    return keys


def npub_short(npub: str) -> str:
    """Return first 12 chars of npub + '..'"""
    return npub[:12] + ".."


class NostrDMClient:
    """High-level wrapper for Nostr NIP-17 encrypted DMs."""

    def __init__(
        self,
        keys: Keys,
        relays: list[str],
        proxy: str = "",
    ):
        self.keys = keys
        self.relays = relays
        self.proxy = proxy
        self.client: Optional[Client] = None
        self._connected = False

    @property
    def npub(self) -> str:
        return self.keys.public_key().to_bech32()

    @property
    def npub_short(self) -> str:
        return npub_short(self.npub)

    async def connect(self) -> list[str]:
        """Connect to relays. Returns list of connected relay URLs."""
        opts = ClientOptions()
        if self.proxy:
            # Parse proxy address "host:port"
            if ":" in self.proxy:
                host, port_str = self.proxy.rsplit(":", 1)
                port = int(port_str)
            else:
                host, port = self.proxy, 1080
            mode = ConnectionMode.PROXY(host, port)
            conn = Connection().mode(mode)
            opts = opts.connection(conn)

        signer = NostrSigner.keys(self.keys)
        builder = ClientBuilder().signer(signer).opts(opts)
        self.client = builder.build()

        for relay_url in self.relays:
            try:
                await self.client.add_relay(RelayUrl.parse(relay_url))
                logger.debug("Added relay: %s", relay_url)
            except Exception as e:
                logger.warning("Failed to add relay %s: %s", relay_url, e)

        await self.client.connect()
        self._connected = True

        connected = []
        for url, relay in (await self.client.relays()).items():
            connected.append(str(url))
        logger.info("Connected to %d relay(s)", len(connected))
        return connected

    async def disconnect(self) -> None:
        if self.client and self._connected:
            await self.client.disconnect()
            self._connected = False
            logger.info("Disconnected from relays")

    async def send_dm(self, recipient_npub: str, text: str, timeout: float = 30.0) -> None:
        """Send a NIP-17 encrypted DM."""
        if not self.client:
            raise RuntimeError("Not connected")
        recipient = PublicKey.parse(recipient_npub)
        await asyncio.wait_for(
            self.client.send_private_msg(recipient, text),
            timeout=timeout,
        )
        logger.debug("Sent DM to %s: %s", npub_short(recipient_npub), text[:50])

    async def subscribe_and_handle(
        self,
        on_dm: Callable[[str, str], Awaitable[None]],
    ) -> None:
        """Subscribe to NIP-17 gift wraps and call on_dm(sender_npub, plaintext).

        This blocks — run in a task.
        """
        if not self.client:
            raise RuntimeError("Not connected")

        # Subscribe to gift wrap events (kind 1059) addressed to us
        # since=7 days ago, limit=0 → only receive new online messages
        import time
        since = Timestamp.from_secs(int(time.time()) - 7 * 86400)
        f = Filter().pubkey(self.keys.public_key()).kind(Kind(1059)).since(since).limit(0)
        await self.client.subscribe(f)
        logger.info("Subscribed to NIP-17 DMs")

        signer = NostrSigner.keys(self.keys)

        class NotificationHandler(HandleNotification):
            async def handle(self, relay_url, subscription_id, event: Event):
                if event.kind().as_u16() == 1059:
                    try:
                        unwrapped = await UnwrappedGift.from_gift_wrap(signer, event)
                        sender_pubkey = unwrapped.sender()
                        rumor = unwrapped.rumor()
                        sender_npub = sender_pubkey.to_bech32()
                        content = rumor.content()
                        logger.debug(
                            "Received DM from %s: %s",
                            npub_short(sender_npub), content[:50]
                        )
                        await on_dm(sender_npub, content)
                    except Exception as e:
                        # Silently ignore events we can't decrypt
                        # (not addressed to us, or from incompatible clients)
                        logger.debug("Ignored gift wrap: %s", e)

            async def handle_msg(self, relay_url, msg):
                pass

        await self.client.handle_notifications(NotificationHandler())
