"""
Telethon-based uploader for large Telegram files (up to 2GB).

Uses Telegram MTProto via Telethon.
Designed for long-running large uploads (Heroku-safe).
"""

import os
import logging
import asyncio
from typing import Optional, Callable

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeFilename

from bot.config import (
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    TELEGRAM_SESSION,
    TG_UPLOAD_TARGET,
    TELEGRAM_BOT_TOKEN,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# GLOBAL SINGLETON CLIENT (PROCESS-WIDE)
# ─────────────────────────────────────────────

_client: Optional[TelegramClient] = None
_client_lock = asyncio.Lock()   # ASYNC lock, NOT threading.Lock


async def _get_client() -> TelegramClient:
    """
    Create exactly ONE Telethon client per process.
    Reused for all uploads.
    """
    global _client

    async with _client_lock:
        if _client is not None:
            return _client

        if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
            raise RuntimeError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set")

        if TELEGRAM_SESSION:
            logger.info("Using string session from TELEGRAM_SESSION env var")
            session = StringSession(TELEGRAM_SESSION)
        else:
            raise RuntimeError(
                "TELEGRAM_SESSION must be set for production (Heroku-safe)"
            )

        _client = TelegramClient(
            session=session,
            api_id=int(TELEGRAM_API_ID),
            api_hash=TELEGRAM_API_HASH,
            receive_updates=False,  # CRITICAL: disable update polling
        )

        await _client.start(bot_token=TELEGRAM_BOT_TOKEN)
        logger.info("Telethon client started (singleton)")

        return _client


# ─────────────────────────────────────────────
# UPLOADER CLASS
# ─────────────────────────────────────────────

class TelethonUploader:
    """Uploader using a shared Telethon client."""

    async def upload_file(
        self,
        file_path: str,
        chat_id: int,
        caption: str = None,
        thumb_path: str = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ):
        """
        Upload a single file safely.
        Can be called repeatedly for split parts.
        """

        client = await _get_client()

        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        target = TG_UPLOAD_TARGET or chat_id
        try:
            target = int(target)
        except Exception:
            pass

        logger.info(
            "Uploading %s (%d bytes) to target %s",
            file_name,
            file_size,
            target,
        )

        await client.send_file(
            entity=target,
            file=file_path,
            caption=caption or file_name,
            thumb=thumb_path,
            attributes=[DocumentAttributeFilename(file_name)],
            progress_callback=progress_callback,
            force_document=True,
            supports_streaming=False,
        )

        logger.info("Successfully uploaded %s", file_name)

        # Let event loop breathe between large uploads
        await asyncio.sleep(1)


# ─────────────────────────────────────────────
# GLOBAL ACCESSOR
# ─────────────────────────────────────────────

_uploader: Optional[TelethonUploader] = None


def get_telethon_uploader() -> Optional[TelethonUploader]:
    global _uploader
    if _uploader is None:
        _uploader = TelethonUploader()
    return _uploader
