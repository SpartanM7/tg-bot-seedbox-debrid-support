
import os
from pathlib import Path
from typing import Optional


def load_dotenv(dotenv_path: Optional[str] = None) -> None:
    """Load a `.env` file into environment variables (does not overwrite existing vars).

    - dotenv_path: path to .env file. Defaults to the repository root `.env`.
    """
    p = Path(dotenv_path) if dotenv_path else Path(__file__).resolve().parents[1] / ".env"
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


# Auto-load .env if present (useful for local dev; CI / Heroku use real env vars)
load_dotenv()

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
SEEDBOX_HTTP_URL = os.getenv("SEEDBOX_HTTP_URL")
RD_ACCESS_TOKEN = os.getenv("RD_ACCESS_TOKEN")
RD_CLIENT_ID = os.getenv("RD_CLIENT_ID")
RD_CLIENT_SECRET = os.getenv("RD_CLIENT_SECRET")
RUTORRENT_URL = os.getenv("RUTORRENT_URL")
RUTORRENT_USER = os.getenv("RUTORRENT_USER")
RUTORRENT_PASS = os.getenv("RUTORRENT_PASS")

SEEDBOX_HOST = os.getenv("SEEDBOX_HOST")
SEEDBOX_SFTP_PORT = int(os.getenv("SEEDBOX_SFTP_PORT", 22))
# SFTP Defaults to RUTORRENT credentials if not provided
SFTP_USER = os.getenv("SFTP_USER") or RUTORRENT_USER
SFTP_PASS = os.getenv("SFTP_PASS") or RUTORRENT_PASS

DRIVE_DEST = os.getenv("DRIVE_DEST", "gdrive:/")

# Telegram User API (Telethon) for large file uploads
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE")
TELEGRAM_SESSION = os.getenv("TELEGRAM_SESSION")  # String session for Heroku



# Auto-detect host from RUTORRENT_URL if not set
if not SEEDBOX_HOST and RUTORRENT_URL:
    try:
        # e.g. https://server.feralhosting.com/rutorrent/
        from urllib.parse import urlparse
        SEEDBOX_HOST = urlparse(RUTORRENT_URL).hostname
    except Exception:
        pass
