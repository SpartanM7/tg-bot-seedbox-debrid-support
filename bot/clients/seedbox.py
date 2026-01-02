"""Seedbox (rTorrent / ruTorrent) client wrapper (minimal stub implementation).

Provides the interface needed by the bot and can be extended with real RPC calls.
"""

import os
from typing import List, Dict, Any

RUTORRENT_URL = os.getenv("RUTORRENT_URL")
RUTORRENT_USER = os.getenv("RUTORRENT_USER")
RUTORRENT_PASS = os.getenv("RUTORRENT_PASS")


class SeedboxNotConfigured(RuntimeError):
    pass


class SeedboxClient:
    def __init__(self, url: str = None, user: str = None, password: str = None):
        self.url = url or RUTORRENT_URL
        self.user = user or RUTORRENT_USER
        self.password = password or RUTORRENT_PASS
        if not (self.url and self.user and self.password):
            raise SeedboxNotConfigured("Seedbox (rTorrent) is not fully configured")

    def add_torrent(self, torrent: str) -> Dict[str, Any]:
        # TODO: implement RPC call to add torrent
        return {"id": "stub-sb-torrent", "status": "added", "torrent": torrent}

    def list_torrents(self) -> List[Dict[str, Any]]:
        # TODO: implement RPC call to list torrents
        return []

    def stop_torrent(self, torrent_hash: str) -> bool:
        # TODO: implement stop via RPC
        return True

    def delete_torrent(self, torrent_hash: str) -> bool:
        # TODO: implement delete via RPC
        return True

    def list_files(self, torrent_hash: str) -> List[str]:
        # TODO: return file list
        return []
