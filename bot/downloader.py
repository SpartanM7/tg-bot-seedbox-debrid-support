"""Downloader module for retrieving files and uploading them.

Handles:
- Downloading from HTTP links (Real-Debrid / Seedbox)
- Zipping folders (via packager)
- Uploading to Telegram (split if large)
- Uploading to Google Drive (rclone stub)
"""

import os
import time
import threading
import requests
import shutil
import logging
import subprocess
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

try:
    import paramiko
except ImportError:
    paramiko = None

from bot.utils import packager
from bot.state import get_state
from bot.storage_queue import get_storage_queue
from bot.config import SEEDBOX_HOST, SEEDBOX_SFTP_PORT, RUTORRENT_USER, RUTORRENT_PASS, DRIVE_DEST, SFTP_USER, SFTP_PASS

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "downloads"
MAX_TG_SIZE = 2 * 1024 * 1024 * 1024 - 1024  # 2GB - padding

_executor = ThreadPoolExecutor(max_workers=2)
_state = get_state()

class Downloader:
    def __init__(self, telegram_updater=None):
        self.updater = telegram_updater
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        self.storage_queue = get_storage_queue(DOWNLOAD_DIR, min_free_gb=20.0)
        self._active_tasks = {}
        self._tasks_lock = threading.Lock()


    def process_item(self, download_url: str, name: str, dest: str = "telegram", chat_id: Optional[int] = None, size: int = 0):
        """Main entry point: Download -> Pack -> Upload."""
        task_id = f"{name}_{int(time.time())}"
        with self._tasks_lock:
            self._active_tasks[task_id] = {
                'name': name,
                'dest': dest,
                'status': 'enqueued',
                'size': size,
                'start_time': time.time()
            }
        
        try:
            self._process_item_logic(download_url, name, dest, chat_id, size, task_id)
        finally:
            with self._tasks_lock:
                if task_id in self._active_tasks:
                    del self._active_tasks[task_id]

    def _process_item_logic(self, download_url: str, name: str, dest: str, chat_id: Optional[int], size: int, task_id: str):
        # Check if we should queue
        item = {
            'url': download_url,
            'name': name,
            'dest': dest,
            'chat_id': chat_id,
            'size': size
        }
        
        if self.storage_queue.enqueue(item):
            # Queued due to low space
            self._update_task_status(task_id, "waiting (low disk)")
            self._notify(chat_id, f"⏸️ Queued: {name} (low disk space, {self.storage_queue.pending_count()} in queue)")
        else:
            # Process immediately
            _executor.submit(self._run_task, download_url, name, dest, chat_id, size, task_id)

    def _update_task_status(self, task_id: str, status: str):
        with self._tasks_lock:
            if task_id in self._active_tasks:
                self._active_tasks[task_id]['status'] = status

    def get_active_tasks(self) -> dict:
        with self._tasks_lock:
            return self._active_tasks.copy()

    def upload_local_file(self, path: str, dest: str, chat_id: Optional[int] = None):
        """Upload a local file or directory to destination."""
        items_to_upload = []
        if os.path.isdir(path):
            items_to_upload = packager.prepare(path, dest=dest)
        else:
            items_to_upload = [{"name": os.path.basename(path), "path": path, "zipped": False}]

        for item in items_to_upload:
            if item.get("skipped"):
                self._notify(chat_id, f"⚠️ Skipped {item['name']}: {item['reason']}")
                continue
            
            upload_path = item.get("zip_path") or item["path"]
            if dest == "telegram":
                self._upload_telegram(upload_path, chat_id)
            elif dest == "gdrive":
                self._upload_gdrive(upload_path, chat_id)
            
            # Cleanup created zips
            if item.get("zipped") and item.get("zip_path") and os.path.exists(item["zip_path"]):
                os.remove(item["zip_path"])
            
    def _run_task(self, url: str, name: str, dest: str, chat_id: Optional[int], size: int, task_id: str):
        local_path = os.path.join(DOWNLOAD_DIR, name)
        try:
            # 1. Download
            self._update_task_status(task_id, "downloading")
            self._notify(chat_id, f"⬇️ Downloading: {name}")
            local_path = self._download_file(url, local_path, task_id)
            
            # 2. Package
            self._update_task_status(task_id, "packaging")
            items_to_upload = []
            if os.path.isdir(local_path):
                items_to_upload = packager.prepare(local_path, dest=dest)
            else:
                items_to_upload = [{"name": name, "path": local_path, "zipped": False}]

            # 3. Upload all prepared items
            for item in items_to_upload:
                if item.get("skipped"):
                    self._notify(chat_id, f"⚠️ Skipped {item['name']}: {item['reason']}")
                    continue
                
                upload_path = item.get("zip_path") or item["path"]
                status_prefix = f"uploading {item['name']}"
                self._update_task_status(task_id, status_prefix)
                
                if dest == "telegram":
                    self._upload_telegram(upload_path, chat_id, task_id)
                elif dest == "gdrive":
                    self._upload_gdrive(upload_path, chat_id, task_id)
            
            # 4. Cleanup items that were created (zips)
            for item in items_to_upload:
                if item.get("zipped") and item.get("zip_path") and os.path.exists(item["zip_path"]):
                    os.remove(item["zip_path"])
            
            # 4. Cleanup
            if os.path.exists(local_path):
                if os.path.isdir(local_path):
                    shutil.rmtree(local_path)
                else:
                    os.remove(local_path)
                
            self._notify(chat_id, f"✅ Completed: {name}")
            
            # 5. Process queue if space freed up
            self._process_queue()
            
        except Exception as e:
            logger.error(f"Failed to process {name}: {e}")
            self._notify(chat_id, f"❌ Error processing {name}: {e}")

    def _download_file(self, url: str, dest_path: str, task_id: Optional[str] = None) -> str:
        """Download file with progress logging. Supports http(s) and sftp."""
        if url.startswith("sftp://"):
            return self._download_sftp(url, dest_path, task_id)
        
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return dest_path

    def _download_sftp(self, url: str, dest_path: str, task_id: Optional[str] = None) -> str:
        if not paramiko:
            raise RuntimeError("paramiko not installed")
        
        remote_path = url[7:] # strip sftp://
        logger.info(f"Starting SFTP download from {SEEDBOX_HOST}:{SEEDBOX_SFTP_PORT} {remote_path}")
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            logger.info(f"DEBUG: Attempting SFTP login with user: '{SFTP_USER}' on {SEEDBOX_HOST}:{SEEDBOX_SFTP_PORT}")
            if not SFTP_USER or not SFTP_PASS:
                 raise RuntimeError("SFTP credentials (SFTP_USER/SFTP_PASS) not set in config")

            ssh.connect(
                hostname=SEEDBOX_HOST, 
                port=SEEDBOX_SFTP_PORT, 
                username=SFTP_USER, 
                password=SFTP_PASS,
                allow_agent=False,
                look_for_keys=False,
                timeout=30,
                auth_timeout=30,
                banner_timeout=30
            )
            sftp = ssh.open_sftp()
            
            try:
                attr = sftp.stat(remote_path)
                if str(attr).startswith('d'):
                    self._download_sftp_dir(sftp, remote_path, dest_path)
                else:
                    sftp.get(remote_path, dest_path)
            except IOError as e:
                raise RuntimeError(f"SFTP Error: {e}")
                
            sftp.close()
        except Exception as e:
            logger.error(f"SFTP Connection Error: {e}")
            raise
        finally:
            ssh.close()
            
        return dest_path
走
    def _download_sftp_dir(self, sftp, remote_dir, local_dir):
        os.makedirs(local_dir, exist_ok=True)
        for entry in sftp.listdir_attr(remote_dir):
            remote_path = remote_dir + "/" + entry.filename
            local_path = os.path.join(local_dir, entry.filename)
            if str(entry).startswith('d'):
                self._download_sftp_dir(sftp, remote_path, local_path)
            else:
                sftp.get(remote_path, local_path)

    def _upload_telegram(self, path: str, chat_id: int, task_id: Optional[str] = None):
        """Upload to Telegram, using Telethon for large files."""
        if not self.updater or not chat_id:
            logger.warning("Telegram upload skipped: no updater/chat_id")
            return

        size = os.path.getsize(path)
        if size > MAX_TG_SIZE:
             self._notify(chat_id, f"⚠️ File {os.path.basename(path)} too large for Telegram ({size / 1024**3:.2f} GB). Skipping.")
             return

        self._notify(chat_id, f"⬆️ Uploading to Telegram: {os.path.basename(path)}")
        
        # Use Telethon for files >50MB, bot API for smaller files
        if size > 50 * 1024 * 1024:
            self._upload_telegram_large(path, chat_id)
        else:
            # Bot API for small files (faster)
            with open(path, 'rb') as f:
                self.updater.bot.send_document(chat_id=chat_id, document=f, filename=os.path.basename(path))
    
    def _upload_telegram_large(self, path: str, chat_id: int):
        """Upload large file using Telethon (user API)."""
        try:
            from bot.telethon_uploader import get_telethon_uploader
            import asyncio
            
            uploader = get_telethon_uploader()
            if not uploader:
                self._notify(chat_id, "⚠️ Telethon not configured. Large file upload failed. Set TELEGRAM_API_ID and TELEGRAM_API_HASH.")
                return
            
            self._notify(chat_id, f"⬆️ Uploading via Telethon (user API)...")
            
            # Progress callback
            def progress(current, total):
                percent = (current / total) * 100
                # Only notify every 10%
                if int(percent) % 10 == 0 and int(percent) != 0:
                    logger.info(f"Upload progress: {percent:.0f}%")
            
            # Run async upload
            asyncio.run(uploader.upload_file(path, chat_id, progress_callback=progress))
            
        except ImportError:
            self._notify(chat_id, "⚠️ Telethon not installed. Install with: pip install telethon")
            logger.error("Telethon not available for large file upload")
        except Exception as e:
            self._notify(chat_id, f"❌ Telethon upload failed: {e}")
            logger.error(f"Telethon upload error: {e}")

    def _upload_gdrive(self, path: str, chat_id: Optional[int] = None, task_id: Optional[str] = None):
        """Upload to Google Drive via rclone."""
        self._notify(chat_id, f"⬆️ Uploading to GDrive: {os.path.basename(path)}")
        
        # Check if rclone is available
        if shutil.which("rclone") is None:
             self._notify(chat_id, "❌ Error: rclone not found in path")
             logger.error("rclone not found")
             return

        try:
            # Check for local rclone.conf in repo root
            config_path = os.path.join(os.getcwd(), "rclone.conf")
            
            if os.path.exists(config_path):
                logger.info(f"Using local rclone config: {config_path}")
                cmd = ["rclone", "--config", config_path, "copy", path, DRIVE_DEST]
            else:
                logger.info("Using default rclone config")
                cmd = ["rclone", "copy", path, DRIVE_DEST]
            
            logger.info(f"Running rclone: {' '.join(cmd)}")
            
            # Run blocking since we are in a thread
            proc = subprocess.run(cmd, capture_output=True, text=True)
            
            if proc.returncode == 0:
                self._notify(chat_id, f"✅ Uploaded to GDrive: {os.path.basename(path)}")
            else:
                logger.error(f"rclone failed: {proc.stderr}")
                self._notify(chat_id, f"❌ GDrive upload failed: {proc.stderr[:100]}")
                
        except Exception as e:
            logger.error(f"Upload GDrive error: {e}")
            self._notify(chat_id, f"❌ Upload GDrive exception: {e}")

    def _process_queue(self):
        """Process queued items if space is now available."""
        while True:
            item = self.storage_queue.dequeue()
            if not item:
                break
            
            # Submit to worker
            _executor.submit(
                self._worker,
                item['url'],
                item['name'],
                item['dest'],
                item['chat_id']
            )
            
            # Notify that item is now processing
            self._notify(item['chat_id'], f"▶️ Processing from queue: {item['name']}")

    def _notify(self, chat_id: Optional[int], text: str):
        if self.updater and chat_id:
             try:
                 self.updater.bot.send_message(chat_id=chat_id, text=text)
             except Exception as e:
                 logger.error(f"Failed to send notification: {e}")
