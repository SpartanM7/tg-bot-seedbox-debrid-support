"""
Real-Debrid API client with automatic token sanitization
"""

import os
import logging
import requests
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


class RealDebridNotConfigured(Exception):
    """Raised when Real-Debrid is not properly configured"""
    pass


class RDClient:
    """Real-Debrid API client"""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Real-Debrid client with token sanitization"""
        self.api_key = api_key or os.getenv("RD_ACCESS_TOKEN")

        # ✅ SANITIZE TOKEN - Remove ALL hidden characters
        if self.api_key:
            # Remove whitespace, newlines, carriage returns, quotes
            self.api_key = self.api_key.strip()
            self.api_key = self.api_key.replace('\r', '')
            self.api_key = self.api_key.replace('\n', '')
            self.api_key = self.api_key.replace('\t', '')
            self.api_key = self.api_key.strip('"').strip("'")
            logger.info(f"✅ Token sanitized: {self.api_key[:10]}...{self.api_key[-4:]}")

        if not self.api_key:
            raise RealDebridNotConfigured("RD_ACCESS_TOKEN not set")

        self.base_url = "https://api.real-debrid.com/rest/1.0"
        logger.info(f"Initialized RDClient with base {self.base_url}")

    def _headers(self) -> Dict[str, str]:
        """Get request headers with clean token"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make API request with error handling"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self._headers(),
                timeout=30,
                **kwargs
            )
            response.raise_for_status()

            # Handle empty responses
            if response.status_code == 204 or not response.text:
                return {}

            return response.json()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                logger.error("❌ Real-Debrid authentication failed - check your token")
                raise RealDebridNotConfigured(f"Invalid API key: {e}")
            logger.error(f"Real-Debrid HTTP error: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Real-Debrid network error: {e}")
            raise
        except ValueError as e:
            logger.error(f"Real-Debrid JSON decode error: {e}")
            raise

    def add_magnet(self, magnet: str) -> Dict:
        """Add magnet link"""
        logger.info(f"Adding magnet to Real-Debrid: {magnet[:50]}...")
        return self._request("POST", "/torrents/addMagnet", data={"magnet": magnet})

    def add_torrent(self, torrent_data: bytes) -> Dict:
        """Add torrent file"""
        logger.info("Adding torrent file to Real-Debrid")
        files = {"file": ("file.torrent", torrent_data)}

        # Special handling for file uploads
        url = f"{self.base_url}/torrents/addTorrent"
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            files=files,
            timeout=30
        )
        response.raise_for_status()
        return response.json()

    def get_torrent_info(self, torrent_id: str) -> Dict:
        """Get torrent information"""
        return self._request("GET", f"/torrents/info/{torrent_id}")

    def select_files(self, torrent_id: str, file_ids: str = "all") -> None:
        """Select files to download"""
        logger.info(f"Selecting files for torrent {torrent_id}: {file_ids}")
        self._request("POST", f"/torrents/selectFiles/{torrent_id}", data={"files": file_ids})

    def list_torrents(self, limit: int = 50) -> List[Dict]:
        """List all torrents"""
        try:
            result = self._request("GET", "/torrents", params={"limit": limit})
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.error(f"Failed to list torrents: {e}")
            return []

    def delete_torrent(self, torrent_id: str) -> None:
        """Delete a torrent"""
        logger.info(f"Deleting torrent {torrent_id}")
        self._request("DELETE", f"/torrents/delete/{torrent_id}")

    def unrestrict_link(self, link: str, remote: bool = True) -> Dict:
        """Unrestrict a download link"""
        logger.info(f"Unrestricting link: {link[:50]}...")
        data = {"link": link}
        if remote:
            data["remote"] = "1"
        return self._request("POST", "/unrestrict/link", data=data)

    def check_instant_availability(self, hashes: List[str]) -> Dict:
        """Check if torrents are cached"""
        if not hashes:
            return {}

        hash_str = "/".join(hashes)
        logger.debug(f"Checking instant availability for {len(hashes)} hash(es)")

        try:
            return self._request("GET", f"/torrents/instantAvailability/{hash_str}")
        except Exception as e:
            logger.error(f"Failed to check instant availability: {e}")
            return {}
