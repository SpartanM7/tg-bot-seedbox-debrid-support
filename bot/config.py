
import os
from pathlib import Path
from typing import Optional


def get_env_safe(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get environment variable and strip whitespace/carriage returns."""
    val = os.getenv(key, default)
    if val is not None:
        return val.strip().replace("\r", "")
    return val

# Auto-load .env if present (useful for local dev; CI / Heroku use real env vars)
load_dotenv()

# Configuration
BOT_TOKEN = get_env_safe("BOT_TOKEN")
SEEDBOX_HTTP_URL = get_env_safe("SEEDBOX_HTTP_URL")
RD_ACCESS_TOKEN = get_env_safe("RD_ACCESS_TOKEN")
RD_CLIENT_ID = get_env_safe("RD_CLIENT_ID")
RD_CLIENT_SECRET = get_env_safe("RD_CLIENT_SECRET")
RUTORRENT_URL = get_env_safe("RUTORRENT_URL")
RUTORRENT_USER = get_env_safe("RUTORRENT_USER")
RUTORRENT_PASS = get_env_safe("RUTORRENT_PASS")
SEEDBOX_RPC_URL = get_env_safe("SEEDBOX_RPC_URL") # New: Explicit override

SEEDBOX_HOST = get_env_safe("SEEDBOX_HOST")
SEEDBOX_SFTP_PORT = int(get_env_safe("SEEDBOX_SFTP_PORT", "22"))
# SFTP Defaults to RUTORRENT credentials if not provided
SFTP_USER = get_env_safe("SFTP_USER") or RUTORRENT_USER
SFTP_PASS = get_env_safe("SFTP_PASS") or RUTORRENT_PASS

DRIVE_DEST = get_env_safe("DRIVE_DEST", "gdrive:/")

# Telegram User API (Telethon) for large file uploads
TELEGRAM_API_ID = get_env_safe("TELEGRAM_API_ID")
TELEGRAM_API_HASH = get_env_safe("TELEGRAM_API_HASH")
TELEGRAM_PHONE = get_env_safe("TELEGRAM_PHONE")
TELEGRAM_SESSION = get_env_safe("TELEGRAM_SESSION")  # String session for Heroku



# Auto-detect host from RUTORRENT_URL if not set
if not SEEDBOX_HOST and RUTORRENT_URL:
    try:
        # e.g. https://server.feralhosting.com/rutorrent/
        from urllib.parse import urlparse
        SEEDBOX_HOST = urlparse(RUTORRENT_URL).hostname
    except Exception:
        pass
