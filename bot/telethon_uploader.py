"""Telethon-based uploader for large Telegram files (up to 2GB).

This module uses Telegram's user API (MTProto) via Telethon to bypass
the 50MB bot API limit. Requires API_ID and API_HASH from my.telegram.org.
"""

import os
import logging
from typing import Optional

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.tl.types import DocumentAttributeFilename
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False
    TelegramClient = None
    StringSession = None

from bot.config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, TELEGRAM_SESSION

logger = logging.getLogger(__name__)


class TelethonUploader:
    """Uploader using Telethon (user API) for large files."""
    
    def __init__(self):
        if not TELETHON_AVAILABLE:
            raise RuntimeError("Telethon not installed. Install with: pip install telethon")
        
        if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
            raise RuntimeError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env")
        
        # Use string session if available (for Heroku), otherwise create new session
        if TELEGRAM_SESSION:
            logger.info("Using string session from TELEGRAM_SESSION env var")
            session = StringSession(TELEGRAM_SESSION)
        else:
            logger.warning("No TELEGRAM_SESSION found. Will create file session (not recommended for Heroku)")
            os.makedirs(".sessions", exist_ok=True)
            session = os.path.join(".sessions", "bot_session")
        
        self.client = TelegramClient(
            session,
            int(TELEGRAM_API_ID),
            TELEGRAM_API_HASH
        )
        self._connected = False
    
    async def connect(self):
        """Connect and authenticate if needed."""
        if not self._connected:
            await self.client.start(phone=TELEGRAM_PHONE)
            self._connected = True
            logger.info("Telethon client connected")
    
    async def upload_file(self, file_path: str, chat_id: int, caption: str = None, progress_callback=None):
        """Upload a file to Telegram using user API.
        
        Args:
            file_path: Path to file to upload
            chat_id: Telegram chat ID
            caption: Optional caption
            progress_callback: Callable(current, total) for progress updates
        """
        await self.connect()
        
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        
        logger.info(f"Uploading {file_name} ({file_size} bytes) to chat {chat_id}")
        
        # Upload as document with custom attributes
        await self.client.send_file(
            chat_id,
            file_path,
            caption=caption,
            attributes=[DocumentAttributeFilename(file_name)],
            progress_callback=progress_callback
        )
        
        logger.info(f"Successfully uploaded {file_name}")
    
    async def disconnect(self):
        """Disconnect client."""
        if self._connected:
            await self.client.disconnect()
            self._connected = False


# Global instance (lazy initialized)
_telethon_uploader = None

def get_telethon_uploader() -> Optional[TelethonUploader]:
    """Get or create global Telethon uploader instance."""
    global _telethon_uploader
    
    if not TELETHON_AVAILABLE:
        logger.warning("Telethon not available, large file uploads disabled")
        return None
    
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH):
        logger.warning("Telethon credentials not configured")
        return None
    
    if _telethon_uploader is None:
        try:
            _telethon_uploader = TelethonUploader()
        except Exception as e:
            logger.error(f"Failed to create Telethon uploader: {e}")
            return None
    
    return _telethon_uploader
