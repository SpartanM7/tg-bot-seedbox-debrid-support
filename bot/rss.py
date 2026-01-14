"""RSS processing and auto-routing per v1 spec.

Features:
- Per-feed configuration (no global defaults)
- Polling/parsing using `feedparser`
- Router that decides backend in AUTO mode with rules:
  1. If backend is forced → use it
  2. If torrent is marked private (per-feed flag) → seedbox
  3. If public & cached on Real-Debrid → Real-Debrid
  4. Else → seedbox

Uses `bot.state` for persistent 'seen' item tracking to survive restarts.
"""

import time
import logging
from typing import Dict, Set, Optional, Callable

try:
    import feedparser
except Exception:
    feedparser = None

from bot.clients.realdebrid import RDClient, RealDebridNotConfigured
from bot.clients.seedbox import SeedboxClient, SeedboxNotConfigured
from bot.state import get_state

logger = logging.getLogger(__name__)

# Polling interval defaults
DEFAULT_POLL_INTERVAL = 600  # 10 mins

class FeedConfig:
    def __init__(self, url: str, forced_backend: Optional[str] = None, private_torrents: bool = False):
        """Create a per-feed config.

        forced_backend: 'rd'|'sb' or None
        private_torrents: if True, treat torrent/magnet items as private and route to seedbox
        """
        self.url = url
        self.forced_backend = forced_backend
        self.private_torrents = private_torrents


class Router:
    def __init__(self, rd_client: Optional[RDClient] = None, sb_client: Optional[SeedboxClient] = None):
        self.rd = rd_client
        self.sb = sb_client

    def decide(self, feed_cfg: FeedConfig, entry: Dict) -> str:
        """Return 'rd' or 'sb' depending on rules."""
        if feed_cfg.forced_backend:
            return feed_cfg.forced_backend

        # Detect torrent-like entries (simple heuristic: magnet or .torrent links)
        link = entry.get('link') or entry.get('guid') or ''
        is_torrent = link.startswith('magnet:') or link.lower().endswith('.torrent')
        if is_torrent and feed_cfg.private_torrents:
            return 'sb'

        if is_torrent:
            # ask RD if it's cached
            if self.rd:
                try:
                    if self.rd.is_cached(link):
                        return 'rd'
                except RealDebridNotConfigured:
                    # If RD not configured, fall back to seedbox
                    return 'sb'
                except Exception as e:
                    logger.warning(f"RD cache check failed: {e}. Falling back to Seedbox.")
                    return 'sb'
            return 'sb'

        # For non-torrent entries default to seedbox (some feeds are generic)
        return 'sb'


class FeedManager:
    def __init__(self, router: Router):
        self.router = router
        self.feeds: Dict[str, FeedConfig] = {}
        self.state_manager = get_state()

    def add_feed(self, url: str, forced_backend: Optional[str] = None, private_torrents: bool = False):
        self.feeds[url] = FeedConfig(url, forced_backend, private_torrents)

    def remove_feed(self, url: str):
        self.feeds.pop(url, None)

    def list_feeds(self):
        return list(self.feeds.values())

    def poll_once(self, on_decision: Optional[Callable[[str, Dict], None]] = None):
        """Poll all feeds once and call `on_decision(backend, entry)` for new items."""
        if feedparser is None:
            raise RuntimeError("feedparser is not installed")
        
        for url, cfg in self.feeds.items():
            logger.info(f"Polling feed: {url}")
            try:
                d = feedparser.parse(url)
            except Exception as e:
                logger.error(f"Failed to parse feed {url}: {e}")
                continue

            for e in d.entries:
                # Unique ID: GUID > link > title
                uid = e.get('id') or e.get('link') or e.get('guid') or e.get('title')
                if not uid:
                    continue
                
                if self.state_manager.is_seen(url, uid):
                    continue

                # Mark as seen immediately to avoid processing loop if decision fails
                self.state_manager.add_seen(url, uid)
                
                try:
                    backend = self.router.decide(cfg, e)
                    logger.info(f"Feed {url}: route {uid} -> {backend}")
                    if on_decision:
                        on_decision(backend, e)
                except Exception as exc:
                    logger.error(f"Error routing item {uid} from {url}: {exc}")

    def run_polling(self, interval_sec: int = DEFAULT_POLL_INTERVAL, on_decision: Optional[Callable[[str, Dict], None]] = None):
        logger.info(f"Starting RSS poll loop (interval={interval_sec}s)")
        while True:
            try:
                self.poll_once(on_decision=on_decision)
            except Exception as exc:
                logger.exception('Uncaught error during RSS polling: %s', exc)
            time.sleep(interval_sec)
