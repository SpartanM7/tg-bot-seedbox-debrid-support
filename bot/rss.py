"""
RSS Feed Manager with smart polling and Real-Debrid cache checking
"""

import logging
import feedparser
import asyncio
import time
from typing import List, Dict, Optional
from datetime import datetime, timezone
import hashlib

logger = logging.getLogger(__name__)


class RSSManager:
    """Manages RSS feeds with intelligent polling and caching"""

    def __init__(
        self,
        rd_client,
        sb_client,
        state_manager,
        upload_dest="gdrive",
        api_delay=2.0,
        default_chat_id=None,
        delete_after_upload=False
    ):
        self.rd_client = rd_client
        self.sb_client = sb_client
        self.state_manager = state_manager
        self.upload_dest = upload_dest
        self.api_delay = api_delay  # Delay between API calls
        self.default_chat_id = default_chat_id
        self.delete_after_upload = delete_after_upload

        # Load feeds from state
        self.feeds = self.state_manager.get_rss_feeds()
        logger.info(f"Loaded {len(self.feeds)} RSS feeds")

    def add_feed(
        self,
        url: str,
        service: Optional[str] = None,
        private_torrent: bool = False,
        delete_after_upload: Optional[bool] = None
    ):
        """
        Add RSS feed

        Args:
            url: RSS feed URL
            service: 'rd' or 'sb' or None (auto-detect based on cache)
            private_torrent: Whether feed contains private torrents
            delete_after_upload: Delete from seedbox after upload (overrides global setting)
        """
        # Check if feed already exists
        for feed in self.feeds:
            if feed["url"] == url:
                raise ValueError("Feed already exists")

        # Use global setting if not specified
        if delete_after_upload is None:
            delete_after_upload = self.delete_after_upload

        feed_data = {
            "url": url,
            "service": service,
            "private": private_torrent,
            "last_check": None,  # Track last poll time
            "seen_guids": [],  # Track seen items to avoid re-processing
            "delete_after_upload": delete_after_upload
        }

        self.feeds.append(feed_data)
        self.state_manager.save_rss_feeds(self.feeds)

        logger.info(f"Added RSS feed: {url} (service={service}, delete={delete_after_upload})")

    def remove_feed(self, url: str):
        """Remove RSS feed by URL"""
        self.feeds = [f for f in self.feeds if f["url"] != url]
        self.state_manager.save_rss_feeds(self.feeds)
        logger.info(f"Removed RSS feed: {url}")

    def list_feeds(self) -> List[Dict]:
        """List all RSS feeds"""
        return self.feeds.copy()

    async def poll_feeds(self) -> int:
        """
        Poll all RSS feeds and add new torrents

        Returns:
            Number of new items found
        """
        total_new = 0

        for feed in self.feeds:
            try:
                new_items = await self._poll_feed(feed)
                total_new += new_items

                # Save updated feed state
                self.state_manager.save_rss_feeds(self.feeds)

                # Delay between feeds to avoid rate limits
                if new_items > 0 and self.api_delay > 0:
                    await asyncio.sleep(self.api_delay)

            except Exception as e:
                logger.error(f"Error polling feed {feed['url']}: {e}", exc_info=True)

        return total_new

    async def _poll_feed(self, feed: Dict) -> int:
        """
        Poll single RSS feed

        Returns:
            Number of new items added
        """
        url = feed["url"]
        logger.info(f"Polling RSS feed: {url}")

        try:
            # Parse feed
            parsed = feedparser.parse(url)

            if not parsed.entries:
                logger.warning(f"No entries found in feed: {url}")
                return 0

            # Get current timestamp for tracking
            current_time = datetime.now(timezone.utc)
            last_check = feed.get("last_check")

            # Initialize seen_guids if not exists
            if "seen_guids" not in feed:
                feed["seen_guids"] = []

            new_items = 0

            for entry in parsed.entries:
                try:
                    # Extract torrent link
                    torrent_url = self._extract_torrent_url(entry)
                    if not torrent_url:
                        continue

                    # Generate unique ID for this entry
                    entry_guid = entry.get("id") or entry.get("link") or torrent_url
                    entry_hash = hashlib.md5(entry_guid.encode()).hexdigest()

                    # Skip if we've seen this item before
                    if entry_hash in feed["seen_guids"]:
                        continue

                    # Check if item is newer than last check (first-time setup)
                    if last_check is None:
                        # First poll - mark all as seen but don't add
                        feed["seen_guids"].append(entry_hash)
                        continue

                    # Parse entry publish date
                    entry_time = None
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        entry_time = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                        entry_time = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

                    # Only process if newer than last check
                    if entry_time and entry_time <= datetime.fromisoformat(last_check):
                        feed["seen_guids"].append(entry_hash)
                        continue

                    # Extract title
                    title = entry.get("title", "Unknown")

                    logger.info(f"📰 RSS: New item - {title}")

                    # Add torrent with intelligent service selection
                    success = await self._add_rss_torrent(
                        torrent_url=torrent_url,
                        title=title,
                        feed=feed
                    )

                    if success:
                        new_items += 1
                        feed["seen_guids"].append(entry_hash)

                        # Delay between items to avoid rate limits
                        if self.api_delay > 0:
                            await asyncio.sleep(self.api_delay)

                except Exception as e:
                    logger.error(f"Error processing entry: {e}", exc_info=True)
                    continue

            # Update last check time
            feed["last_check"] = current_time.isoformat()

            # Keep only last 1000 seen GUIDs to prevent memory bloat
            if len(feed["seen_guids"]) > 1000:
                feed["seen_guids"] = feed["seen_guids"][-1000:]

            logger.info(f"RSS feed {url}: {new_items} new items")
            return new_items

        except Exception as e:
            logger.error(f"Error parsing feed {url}: {e}", exc_info=True)
            return 0

    def _extract_torrent_url(self, entry) -> Optional[str]:
        """Extract torrent URL from RSS entry"""
        # Try direct link
        if hasattr(entry, "link") and entry.link:
            if entry.link.startswith("magnet:") or entry.link.endswith(".torrent"):
                return entry.link

        # Try enclosures
        if hasattr(entry, "enclosures"):
            for enclosure in entry.enclosures:
                if enclosure.get("type") == "application/x-bittorrent":
                    return enclosure.get("href")

        # Try links
        if hasattr(entry, "links"):
            for link in entry.links:
                href = link.get("href", "")
                if href.startswith("magnet:") or href.endswith(".torrent"):
                    return href

        return None

    async def _add_rss_torrent(self, torrent_url: str, title: str, feed: Dict) -> bool:
        """
        Add torrent from RSS with intelligent service selection

        Strategy:
        1. If service is forced (rd/sb), use that
        2. If public torrent: Check RD cache first
        3. If cached in RD -> use RD
        4. If not cached -> use Seedbox
        5. If private torrent -> always use Seedbox

        Returns:
            True if successfully added
        """
        service = feed.get("service")
        private = feed.get("private", False)
        delete_after_upload = feed.get("delete_after_upload", self.delete_after_upload)

        try:
            # If service is forced, use it
            if service in ["rd", "sb"]:
                selected_service = service
                logger.info(f"Using forced service: {selected_service}")

            # If private torrent, always use seedbox
            elif private:
                selected_service = "sb"
                logger.info(f"Private torrent -> using Seedbox")

            # Public torrent: Check RD cache
            else:
                selected_service = await self._select_service_by_cache(torrent_url)

            # Add to selected service
            if selected_service == "rd":
                if not self.rd_client:
                    logger.error("Real-Debrid not configured")
                    return False

                # Add to Real-Debrid
                if torrent_url.startswith("magnet:"):
                    result = self.rd_client.add_magnet(torrent_url)
                else:
                    # Download torrent file
                    import requests
                    resp = requests.get(torrent_url, timeout=30)
                    resp.raise_for_status()
                    result = self.rd_client.add_torrent(resp.content)

                torrent_id = result.get("id")

                logger.info(f"✅ Added to RD ({self.upload_dest}): {title}")

                # Store for monitoring
                self.state_manager.add_torrent(
                    torrent_id=str(torrent_id),
                    service="rd",
                    user_id=0,  # RSS user
                    upload_intent=self.upload_dest,
                    chat_id=self.default_chat_id,
                    delete_after_upload=False  # RD doesn't need deletion
                )

            elif selected_service == "sb":
                if not self.sb_client:
                    logger.error("Seedbox not configured")
                    return False

                # Add to Seedbox
                if torrent_url.startswith("magnet:"):
                    result = self.sb_client.add_magnet(torrent_url)
                else:
                    import requests
                    resp = requests.get(torrent_url, timeout=30)
                    resp.raise_for_status()
                    result = self.sb_client.add_torrent(resp.content)

                torrent_hash = result.get("hash")

                logger.info(f"✅ Added to Seedbox ({self.upload_dest}, delete={delete_after_upload}): {title}")

                # Store for monitoring
                self.state_manager.add_torrent(
                    torrent_id=torrent_hash,
                    service="sb",
                    user_id=0,  # RSS user
                    upload_intent=self.upload_dest,
                    chat_id=self.default_chat_id,
                    delete_after_upload=delete_after_upload  # Per-feed config
                )

            return True

        except Exception as e:
            logger.error(f"Error adding RSS torrent {title}: {e}", exc_info=True)
            return False

    async def _select_service_by_cache(self, torrent_url: str) -> str:
        """
        Select service based on Real-Debrid cache availability

        Returns:
            'rd' if cached in Real-Debrid, 'sb' otherwise
        """
        try:
            # Check if RD client is available
            if not self.rd_client:
                logger.info("RD not configured -> using Seedbox")
                return "sb"

            # Extract hash from magnet or get torrent info
            if torrent_url.startswith("magnet:"):
                # Extract hash from magnet
                import re
                match = re.search(r"btih:([a-fA-F0-9]{40})", torrent_url)
                if not match:
                    logger.warning("Cannot extract hash from magnet -> using Seedbox")
                    return "sb"
                torrent_hash = match.group(1).lower()
            else:
                # Download torrent and calculate hash
                import requests
                import bencodepy
                resp = requests.get(torrent_url, timeout=30)
                resp.raise_for_status()
                torrent_data = bencodepy.decode(resp.content)
                info_hash = hashlib.sha1(bencodepy.encode(torrent_data[b'info'])).hexdigest()
                torrent_hash = info_hash.lower()

            # Check RD instant availability
            logger.info(f"Checking RD cache for hash: {torrent_hash}")
            availability = self.rd_client.check_instant_availability([torrent_hash])

            if availability and torrent_hash in availability and availability[torrent_hash]:
                logger.info(f"✅ Cached in RD -> using Real-Debrid")
                return "rd"
            else:
                logger.info(f"❌ Not cached in RD -> using Seedbox")
                return "sb"

        except Exception as e:
            logger.error(f"Error checking RD cache: {e}", exc_info=True)
            logger.info("Cache check failed -> using Seedbox")
            return "sb"
