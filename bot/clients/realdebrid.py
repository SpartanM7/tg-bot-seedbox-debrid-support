"""Real-Debrid client wrapper (HTTP implementation).

This implementation uses the Real-Debrid REST API v1. It requires a valid
`RD_ACCESS_TOKEN` environment variable (a personal access token).

Note: the API surface used is minimal and focuses on the operations needed by
v1: check instant availability, add magnet, list torrents, delete torrent.
"""

import os
import requests
from typing import List, Dict, Any

RD_ACCESS_TOKEN = os.getenv("RD_ACCESS_TOKEN")
RD_API_BASE = os.getenv("RD_API_BASE", "https://api.real-debrid.com/rest/1.0")


class RealDebridNotConfigured(RuntimeError):
    pass


class RDAPIError(RuntimeError):
    pass


class RDClient:
    def __init__(self, access_token: str = None, base_url: str = None, timeout: int = 10):
        self.access_token = access_token or RD_ACCESS_TOKEN
        self.base = base_url or RD_API_BASE
        self.timeout = timeout
        if not self.access_token:
            raise RealDebridNotConfigured("Real-Debrid access token not set (RD_ACCESS_TOKEN)")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = self.base.rstrip("/") + "/" + path.lstrip("/")
        kwargs.setdefault("timeout", self.timeout)
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())
        try:
            resp = requests.request(method, url, headers=headers, **kwargs)
        except requests.RequestException as exc:
            raise RDAPIError(f"network error: {exc}") from exc
        if resp.status_code == 401:
            raise RealDebridNotConfigured("Real-Debrid access token rejected (401)")
        if not resp.ok:
            raise RDAPIError(f"RD API {resp.status_code}: {resp.text}")
        if resp.text:
            try:
                return resp.json()
            except ValueError:
                return resp.text
        return None

    def is_cached(self, magnet_or_hash: str) -> bool:
        """Check instant availability for a magnet or torrent hash.

        Uses the `/torrents/instantAvailability` endpoint. Returns True if RD has
        the torrent cached/instant-available, otherwise False.
        """
        # The API expects `magnets[]` as POST payload. Use defensive code to
        # interpret different response shapes.
        try:
            data = {"magnets[]": magnet_or_hash}
            resp = self._request("POST", "/torrents/instantAvailability", data=data)
            # resp can be dict mapping hash->info or list; check for any positive flag
            if isinstance(resp, dict):
                # look through values for instant availability
                for v in resp.values():
                    if isinstance(v, dict) and v.get("instant"):
                        return True
            elif isinstance(resp, list):
                for item in resp:
                    if isinstance(item, dict) and item.get("instant"):
                        return True
            return False
        except RealDebridNotConfigured:
            raise
        except RDAPIError:
            # On any API error, be conservative and return False
            return False

    def add_magnet(self, magnet: str) -> Dict[str, Any]:
        """Add a magnet to Real-Debrid torrents and return the created resource."""
        resp = self._request("POST", "/torrents/addMagnet", data={"magnet": magnet})
        return resp

    def list_torrents(self) -> List[Dict[str, Any]]:
        resp = self._request("GET", "/torrents")
        return resp or []

    def delete_torrent(self, torrent_id: str) -> bool:
        _ = self._request("DELETE", f"/torrents/{torrent_id}")
        return True
