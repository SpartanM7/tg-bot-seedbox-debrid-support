"""Real-Debrid client wrapper (minimal stub implementation).

This module provides a small class with the interface needed by the bot. Methods
raise a clear error if the client isn't configured via env vars. Network-based
implementations can be added later without changing the rest of the code.
"""

import os
from typing import List, Dict, Any

RD_ACCESS_TOKEN = os.getenv("RD_ACCESS_TOKEN")


class RealDebridNotConfigured(RuntimeError):
    pass


class RDClient:
    def __init__(self, access_token: str = None):
        self.access_token = access_token or RD_ACCESS_TOKEN
        if not self.access_token:
            raise RealDebridNotConfigured("Real-Debrid access token not set (RD_ACCESS_TOKEN)")

    def is_cached(self, link: str) -> bool:
        """Stub: Return whether Real-Debrid has cached the resource.

        A real implementation would call RD endpoints to check cache/instant availability.
        """
        # TODO: implement actual API call
        return False

    def add_magnet(self, magnet: str) -> Dict[str, Any]:
        """Stub: Add a magnet to RD and return a representation.

        Returns a dict with minimal fields to satisfy handlers.
        """
        # TODO: implement actual API call
        return {"id": "stub-magnet", "status": "queued", "magnet": magnet}

    def list_torrents(self) -> List[Dict[str, Any]]:
        """Stub: List torrents in RD."""
        # TODO: implement actual API call
        return []

    def delete_torrent(self, torrent_id: str) -> bool:
        """Stub: Delete a torrent on RD and return success bool."""
        # TODO: implement actual API call
        return True
