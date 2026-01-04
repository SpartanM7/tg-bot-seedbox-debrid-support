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
from bot.utils.thumbnailer import generate_thumbnail
from bot.state import get_state
from bot.storage_queue import get_storage_queue
from bot.config import SEEDBOX_HOST, SEEDBOX_SFTP_PORT, RUTORRENT_USER, RUTORRENT_PASS, DRIVE_DEST, SFTP_USER, SFTP_PASS, TG_UPLOAD_TARGET

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
        
        # The background logic or queue will now manage the task_id entry in self._active_tasks
        self._process_item_logic(download_url, name, dest, chat_id, size, task_id)

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
                
            # 5. Final Report
            report = f"✅ **Completed Transfer**\n\n"
            report += f"📁 **Name**: `{name}`\n"
            if "sftp://" not in url: # If it was a torrent/box hash, we might have it
                 # Try to extract hash from URL or use name
                 pass

            report += "\n🚀 **Uploaded Files:**\n"
            for item in items_to_upload:
                if item.get("skipped"): continue
                fname = item['name']
                # Telegram link is hard to get via Telethon easily without extra logic, 
                # but we can list the names.
                report += f"• `{fname}`\n"
            
            # Management Buttons (stubs for the bot to handle)
            report += f"\n🛠 **Management:**\n"
            # Extract hash if present in URL (box hash usually 40 chars)
            box_hash = None
            if len(url) == 40 or "hash=" in url:
                 box_hash = url if len(url) == 40 else url.split("hash=")[1].split("&")[0]
            
            if box_hash:
                report += f"停止: `/sb_stop {box_hash}`\n"
                report += f"删除: `/sb_delete {box_hash}`\n"

            self._notify(chat_id, report)
            
            # 6. Process queue if space freed up
            self._process_queue()
            
        except Exception as e:
            logger.error(f"Failed to process {name}: {e}")
            self._notify(chat_id, f"❌ Error processing {name}: {e}")
        finally:
            with self._tasks_lock:
                if task_id in self._active_tasks:
                    del self._active_tasks[task_id]

    def _download_file(self, url: str, dest_path: str, task_id: Optional[str] = None) -> str:
        """Download file with progress logging. Supports http(s) and sftp.
        Includes retry logic for transient HTTP errors."""
        if url.startswith("sftp://"):
            return self._download_sftp(url, dest_path, task_id)
        
        max_retries = 5
        for attempt in range(max_retries):
            try:
                with requests.get(url, stream=True, timeout=30) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get('content-length', 0))
                    downloaded = 0
                    with open(dest_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                if task_id and total_size > 0:
                                    downloaded += len(chunk)
                                    # Every ~5MB
                                    if downloaded % (5 * 1024 * 1024) < 16384:
                                        percent = (downloaded / total_size) * 100
                                        self._update_task_status(task_id, f"downloading ({percent:.1f}%)")
                    return dest_path
            except (requests.exceptions.HTTPError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                # Retry on 5xx or 429
                status_code = getattr(e.response, 'status_code', None)
                if attempt < max_retries - 1 and (status_code in [500, 502, 503, 504, 429] or status_code is None):
                    wait_time = 2 ** attempt
                    logger.warning(f"Download attempt {attempt+1} failed ({e}). Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                logger.error(f"Download failed after {attempt+1} attempts: {e}")
                raise
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
            
            def sftp_cb(transferred, total):
                if task_id and total > 0:
                    percent = (transferred / total) * 100
                    if int(percent) % 5 == 0:
                        self._update_task_status(task_id, f"downloading (SFTP {percent:.1f}%)")

            try:
                attr = sftp.stat(remote_path)
                if str(attr).startswith('d'):
                    # Count total files first
                    total_files = self._get_sftp_file_count(sftp, remote_path)
                    logger.info(f"SFTP Directory contains {total_files} files.")
                    self._download_sftp_dir(sftp, remote_path, dest_path, task_id, total_files=total_files)
                else:
                    sftp.get(remote_path, dest_path, callback=sftp_cb)
            except IOError as e:
                raise RuntimeError(f"SFTP Error: {e}")
                
            sftp.close()
        except Exception as e:
            logger.error(f"SFTP Connection Error: {e}")
            raise
        finally:
            ssh.close()
            
        return dest_path

    def _get_sftp_file_count(self, sftp, remote_dir) -> int:
        count = 0
        try:
            for entry in sftp.listdir_attr(remote_dir):
                if str(entry).startswith('d'):
                    count += self._get_sftp_file_count(sftp, remote_dir + "/" + entry.filename)
                else:
                    count += 1
        except Exception:
            pass
        return count

    def _download_sftp_dir(self, sftp, remote_dir, local_dir, task_id: Optional[str] = None, total_files: int = 0, current_index: List[int] = None):
        if current_index is None: current_index = [0]
        os.makedirs(local_dir, exist_ok=True)
        for entry in sftp.listdir_attr(remote_dir):
            remote_path = remote_dir + "/" + entry.filename
            local_path = os.path.join(local_dir, entry.filename)
            if str(entry).startswith('d'):
                self._download_sftp_dir(sftp, remote_path, local_path, task_id, total_files, current_index)
            else:
                current_index[0] += 1
                curr = current_index[0]
                total_str = f" {curr}/{total_files}" if total_files > 0 else ""
                
                def cb(t, total):
                    if task_id and total > 0:
                        p = (t / total) * 100
                        if int(p) % 10 == 0:
                             self._update_task_status(task_id, f"downloading{total_str} {entry.filename} ({p:.1f}%)")
                
                if task_id: self._update_task_status(task_id, f"downloading{total_str} {entry.filename} (0.0%)")
                sftp.get(remote_path, local_path, callback=cb)

    def _upload_telegram(self, path: str, chat_id: int, task_id: Optional[str] = None):
        """Upload to Telegram, using Telethon for large files."""
        if not self.updater or not chat_id:
            logger.warning("Telegram upload skipped: no updater/chat_id")
            return

        size = os.path.getsize(path)
        if size > MAX_TG_SIZE:
             self._notify(chat_id, f"⚠️ File {os.path.basename(path)} too large for Telegram ({size / 1024**3:.2f} GB). Skipping.")
             return

        # Generate thumbnail for videos
        thumb_path = None
        ext = os.path.splitext(path)[1].lower()
        if ext in ['.mp4', '.mkv', '.avi', '.mov', '.m4v']:
            thumb_path = generate_thumbnail(path)

        self._notify(chat_id, f"⬆️ Uploading to Telegram: {os.path.basename(path)}")
        
        # Use Telethon for files >50MB, bot API for smaller files
        if size > 50 * 1024 * 1024:
            self._upload_telegram_large(path, chat_id, task_id, thumb_path=thumb_path)
        else:
            # Bot API for small files
            target = TG_UPLOAD_TARGET or chat_id
            with open(path, 'rb') as f:
                thumb_file = open(thumb_path, 'rb') if thumb_path else None
                try:
                    self.updater.bot.send_document(
                        chat_id=target, 
                        document=f, 
                        filename=os.path.basename(path),
                        thumb=thumb_file,
                        caption=os.path.basename(path)
                    )
                finally:
                    if thumb_file: thumb_file.close()

        # Cleanup thumbnail
        if thumb_path and os.path.exists(thumb_path):
            os.remove(thumb_path)
    
    def _upload_telegram_large(self, path: str, chat_id: int, task_id: Optional[str] = None, thumb_path: str = None):
        """Upload large file using Telethon (user API)."""
        try:
            from bot.telethon_uploader import get_telethon_uploader
            import asyncio
            
            uploader = get_telethon_uploader()
            if not uploader:
                self._notify(chat_id, "⚠️ Telethon not configured. Large file upload failed.")
                return
            
            # Progress callback
            def progress(current, total):
                if task_id and total > 0:
                    percent = (current / total) * 100
                    # Only update system status every roughly 5%
                    if int(percent) % 5 == 0:
                        self._update_task_status(task_id, f"uploading ({percent:.1f}%)")
            
            # Run async upload
            asyncio.run(uploader.upload_file(path, chat_id, thumb_path=thumb_path, progress_callback=progress))
            
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
