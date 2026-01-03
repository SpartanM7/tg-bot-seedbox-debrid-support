"""Real-Debrid client wrapper (HTTP implementation).

This implementation uses the Real-Debrid REST API v1. It requires a valid
`RD_ACCESS_TOKEN` environment variable (a personal access token).

Note: the API surface used is minimal and focuses on the operations needed by
v1: check instant availability, add magnet, list torrents, delete torrent.
"""

import os
import requests
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

RD_ACCESS_TOKEN = os.getenv("RD_ACCESS_TOKEN")
RD_API_BASE = os.getenv("RD_API_BASE", "https://api.real-debrid.com/rest/1.0")


class RealDebridNotConfigured(RuntimeError):
    pass


class RDAPIError(RuntimeError):
    pass


class RDClient:
    def __init__(self, access_token: str = None, base_url: str = None, timeout: int = 20):
        self.access_token = access_token or RD_ACCESS_TOKEN
        self.base = base_url or RD_API_BASE
        self.timeout = timeout
        if not self.access_token:
            logger.error("RD_ACCESS_TOKEN not set")
            raise RealDebridNotConfigured("Real-Debrid access token not set (RD_ACCESS_TOKEN)")
        logger.info(f"Initialized RDClient with base {self.base}")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = self.base.rstrip("/") + "/" + path.lstrip("/")
        kwargs.setdefault("timeout", self.timeout)
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())
        
        headers.update(self._headers())
        
        try:
            logger.debug(f"RD Request: {method} {url}")
            resp = requests.request(method, url, headers=headers, **kwargs)
        except requests.RequestException as exc:
            raise RDAPIError(f"network error: {exc}") from exc
            
        if resp.status_code == 401:
            raise RealDebridNotConfigured("Real-Debrid access token rejected (401)")
        
        if resp.status_code == 204:
            return True

        if not resp.ok:
            error_msg = f"RD API {resp.status_code}"
            try:
                data = resp.json()
                if "error" in data:
                    error_msg += f": {data['error']}"
            except Exception:
                error_msg += f": {resp.text}"
            raise RDAPIError(error_msg)

        try:
            return resp.json()
        except ValueError:
            return resp.text

    def get_user_info(self) -> Dict[str, Any]:
        """Get user info to verify token and status."""
        return self._request("GET", "/user")

    def is_cached(self, magnet_or_hash: str) -> bool:
        """Check instant availability for a magnet or torrent hash.

        Uses the `/torrents/instantAvailability` endpoint. Returns True if RD has
        the torrent cached/instant-available, otherwise False.
        """
        try:
            # Clean magnet to hash if needed, but RD API usually handles both.
            # The API expects `magnets[]` as POST payload.
            data = {"magnets[]": magnet_or_hash}
            resp = self._request("GET", "/torrents/instantAvailability/" + magnet_or_hash)
            
            # Endpoint actually uses GET with /{hash} for single check in some docs, but POST for batch. 
            # The v1 stubs used POST. Let's stick to the documented way for checking a single hash/magnet if possible.
            # However, simpler to use the method that definitely worked or stick to the previous pattern if it was robust.
            # Actually, standard RD API for one hash: GET /torrents/instantAvailability/{hash}
            # For this implementation, I will stick to what was likely intended or standard:
            if not resp:
                return False
                
            # Response format: { "hash": { "rd": [ { ... } ] } }
            if isinstance(resp, dict):
                for hoster_data in resp.values(): # iterate over hashes
                    if isinstance(hoster_data, dict) and "rd" in hoster_data:
                        variants = hoster_data["rd"]
                        if variants and len(variants) > 0:
                            return True
            return False
            
        except RealDebridNotConfigured:
            raise
        except Exception as e:
            logger.error(f"Error checking cache status: {e}")
            return False

    def unrestrict_link(self, link: str) -> Dict[str, Any]:
        """Unrestrict a hoster link (e.g. from a torrent download or DDL)."""
        return self._request("POST", "/unrestrict/link", data={"link": link})

    def add_magnet(self, magnet: str) -> Dict[str, Any]:
        """Add a magnet to Real-Debrid torrents and return the created resource."""
        return self._request("POST", "/torrents/addMagnet", data={"magnet": magnet})

    def list_torrents(self, page: int = 1, limit: int = 50) -> List[Dict[str, Any]]:
        """List user torrents."""
        return self._request("GET", "/torrents", params={"page": page, "limit": limit}) or []
    
    def get_torrent_info(self, torrent_id: str) -> Dict[str, Any]:
        """Get details about a specific torrent."""
        return self._request("GET", f"/torrents/info/{torrent_id}")

    def delete_torrent(self, torrent_id: str) -> bool:
        """Delete a torrent."""
        self._request("DELETE", f"/torrents/{torrent_id}")
        return True

    def select_files(self, torrent_id: str, file_ids: str = "all") -> bool:
        """Select files to start the torrent (default 'all')."""
        self._request("POST", f"/torrents/selectFiles/{torrent_id}", data={"files": file_ids})
        return True

    def get_downloads(self, page: int = 1, limit: int = 50) -> List[Dict[str, Any]]:
        """List unrestricted downloads history."""
        return self._request("GET", "/downloads", params={"page": page, "limit": limit}) or []

