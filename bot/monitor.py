"""Monitor module for polling services and triggering downloads.

- Polls Real-Debrid for "downloaded" torrents.
- Polls Seedbox for "finished" torrents.
- Triggers Downloader.process_item().
- Uses persistent state to avoid re-processing.
"""

import time
import logging
import threading
from typing import Optional, List, Dict, Any

from bot.clients.realdebrid import RDClient, RealDebridNotConfigured
from bot.clients.seedbox import SeedboxClient, SeedboxNotConfigured
from bot.state import get_state
from bot.downloader import Downloader

logger = logging.getLogger(__name__)

POLL_INTERVAL = 20  # seconds

class Monitor:
    def __init__(self, downloader: Downloader, rd_client: Optional[RDClient] = None, sb_client: Optional[SeedboxClient] = None):
        self.downloader = downloader
        self.rd = rd_client
        self.sb = sb_client
        self.state = get_state()
        self.running = False

    def start(self):
        """Start the polling loop in a background thread."""
        self.running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()
        logger.info("Monitor started polling.")

    def _loop(self):
        while self.running:
            try:
                self.check_realdebrid()
                self.check_seedbox()
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
            time.sleep(POLL_INTERVAL)

    def check_realdebrid(self):
        if not self.rd: return
        try:
            torrents = self.rd.list_torrents(limit=20)
            for t in torrents:
                if t['status'] == 'waiting_files_selection':
                    logger.info(f"Monitor: Auto-selecting files for RD torrent {t['filename']}")
                    self.rd.select_files(t['id'])
                    continue

                if t['status'] == 'downloaded':
                    tid = t['id']
                    if self.state.is_processed(f"rd_{tid}"):
                        continue
                    
                    # Unrestrict and download
                    logger.info(f"Monitor: Found RD completion {t['filename']}")
                    
                    # Notify waiting stage
                    self._notify_completion(f"rd_{tid}", t['filename'])
                    
                    # Get info to find links
                    info = self.rd.get_torrent_info(tid)
                    links = info.get('links', [])
                    
                    # For simplicity, handle first link or all? 
                    # Let's handle all unrestricted links
                    for link in links:
                        try:
                            unrestricted = self.rd.unrestrict_link(link, remote=True)
                            dl_url = unrestricted['download']
                            name = unrestricted['filename']
                            
                            # Determine intent
                            dest = self.state.get_intent(f"rd_{tid}") or "telegram"
                            
                            # Get file size from unrestricted info
                            file_size = unrestricted.get('filesize', 0)
                            
                            # Trigger download
                            self.downloader.process_item(dl_url, name, dest=dest, chat_id=None, size=file_size) 
                            # Note: chat_id is None here because we don't know who added it.
                            # Improvement: Store chat_id in state when adding torrent.
                            
                        except Exception as e:
                            logger.error(f"Failed to unrestrict/process RD link {link}: {e}")

                    self.state.add_processed(f"rd_{tid}")
        except Exception as e:
            logger.error(f"RD Monitor Error: {e}")

    def check_seedbox(self):
        if not self.sb: return
        try:
            torrents = self.sb.list_torrents()
            for t in torrents:
                # Check completion using new state field or manual fallback
                # State is 'seeding' if done >= size
                if t.get('state') == 'seeding' or (t['size'] > 0 and t['bytes_done'] == t['size']):
                    shash = t['hash']
                    if self.state.is_processed(f"sb_{shash}"):
                        continue
                    
                    logger.info(f"Monitor: Found Seedbox completion {t['name']}")
                    
                    # Notify waiting stage
                    self._notify_completion(f"sb_{shash}", t['name'])
                    
                    # Use SFTP
                    # List torrents now returns 'base_path' (full path on server)
                    base_path = t.get('base_path')
                    if not base_path:
                         logger.warning(f"Seedbox torrent {t['name']} has no base_path")
                         continue

                    # Construct SFTP URL (internal scheme handled by downloader)
                    dl_url = f"sftp://{base_path}"
                    
                    # Determine intent
                    dest = self.state.get_intent(f"sb_{shash}") or "telegram"
                    
                    # Get file size from torrent info
                    file_size = t.get('size', 0)
                    
                    self.downloader.process_item(dl_url, t['name'], dest=dest, chat_id=None, size=file_size)
                    
                    self.state.add_processed(f"sb_{shash}")
                    
        except Exception as e:
            logger.error(f"Seedbox Monitor Error: {e}")
    
    def _notify_completion(self, item_id: str, name: str):
        """Send notification that item is ready for download."""
        # Try to get chat_id from state if stored
        # For now, just log. Future: store chat_id when adding torrents.
        logger.info(f"⏳ Ready for download: {name}")
