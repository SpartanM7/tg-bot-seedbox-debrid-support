"""
Telethon-based uploader for large Telegram files (up to 2GB+ via splitting).

Uses Telegram MTProto (user API) via Telethon.
Designed to be safe for long-running uploads on Heroku.
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
    BOT_TOKEN,            # <-- IMPORTANT: this already exists in your project
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# GLOBAL SINGLETON TELETHON CLIENT (PROCESS-WIDE)
# ─────────────────────────────────────────────

_client: Optional[TelegramClient] = None
_client_lock = asyncio.Lock()   # ASYNC lock (never threading.Lock)


async def _get_client() -> TelegramClient:
    """
    Create exactly ONE Telethon client per worker process.
    This client is reused for ALL uploads.
    """
    global _client

    async with _client_lock:
        if _client is not None:
            return _client

        if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
            raise RuntimeError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set")

        if not TELEGRAM_SESSION:
            raise RuntimeError(
                "TELEGRAM_SESSION must be set (string session required for Heroku)"
            )

        logger.info("Initializing singleton Telethon client")

        session = StringSession(TELEGRAM_SESSION)

        _client = TelegramClient(
            session=session,
            api_id=int(TELEGRAM_API_ID),
            api_hash=TELEGRAM_API_HASH,
            receive_updates=False,  # CRITICAL: disables update polling
        )

        # Start client as BOT (correct + explicit)
        await _client.start(bot_token=BOT_TOKEN)

        logger.info("Telethon client started successfully (singleton)")
        return _client


# ─────────────────────────────────────────────
# UPLOADER CLASS
# ─────────────────────────────────────────────

class TelethonUploader:
    """
    Stateless uploader that uses the shared Telethon client.
    Safe for split uploads and long-running tasks.
    """

    async def upload_file(
        self,
        file_path: str,
        chat_id: int,
        caption: Optional[str] = None,
        thumb_path: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ):
        """
        Upload a single file using Telethon.

        This function can be called sequentially for split parts.
        """

        client = await _get_client()

        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        # Override chat_id if TG_UPLOAD_TARGET is set
        target = TG_UPLOAD_TARGET or chat_id
        try:
            target = int(target)
        except Exception:
            pass

        logger.info(
            "Uploading %s (%d bytes) to Telegram target %s",
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

        # Give event loop breathing room between large uploads
        await asyncio.sleep(1)


# ─────────────────────────────────────────────
# GLOBAL ACCESSOR
# ─────────────────────────────────────────────

_uploader: Optional[TelethonUploader] = None


def get_telethon_uploader() -> Optional[TelethonUploader]:
    """
    Returns a singleton TelethonUploader instance.
    """
    global _uploader
    if _uploader is None:
        _uploader = TelethonUploader()
    return _uploader
