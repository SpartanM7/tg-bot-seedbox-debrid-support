"""
Downloader module for retrieving files and uploading them.

Handles:
- Downloading from HTTP links (Real-Debrid / direct)
- Downloading from SFTP (Seedbox / rTorrent)
- Zipping folders (via packager)
- Uploading to Telegram (split if large)
- Uploading to Google Drive (rclone)
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
from bot.config import (
    SEEDBOX_HOST,
    SEEDBOX_SFTP_PORT,
    DRIVE_DEST,
    SFTP_USER,
    SFTP_PASS,
    TG_UPLOAD_TARGET,
)

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "downloads"
MAX_TG_SIZE = 2 * 1024 * 1024 * 1024 - 1024  # ~2GB
_executor = ThreadPoolExecutor(max_workers=2)
_state = get_state()


class Downloader:
    def __init__(self, telegram_updater=None):
        self.updater = telegram_updater
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        self.storage_queue = get_storage_queue(DOWNLOAD_DIR, min_free_gb=20.0)

        self._active_tasks = {}
        self._tasks_lock = threading.Lock()

    # ─────────────────────────────────────────────
    # STATUS
    # ─────────────────────────────────────────────

    def get_active_tasks(self) -> dict:
        with self._tasks_lock:
            return self._active_tasks.copy()

    def _update_task_status(self, task_id: str, status: str):
        with self._tasks_lock:
            if task_id in self._active_tasks:
                self._active_tasks[task_id]["status"] = status

    # ─────────────────────────────────────────────
    # ENTRY
    # ─────────────────────────────────────────────

    def process_item(self, download_url, name, dest="telegram",
                     chat_id=None, size=0):

        task_id = f"{name}_{int(time.time())}"
        with self._tasks_lock:
            self._active_tasks[task_id] = {
                "name": name,
                "dest": dest,
                "status": "enqueued",
                "size": size,
                "start_time": time.time(),
            }

        item = {
            "url": download_url,
            "name": name,
            "dest": dest,
            "chat_id": chat_id,
            "size": size,
        }

        if self.storage_queue.enqueue(item):
            self._update_task_status(task_id, "waiting (low disk)")
            self._notify(chat_id, f"⏸️ Queued: {name}")
        else:
            _executor.submit(
                self._run_task,
                download_url,
                name,
                dest,
                chat_id,
                size,
                task_id,
            )

    # ─────────────────────────────────────────────
    # CORE WORKER
    # ─────────────────────────────────────────────

    def _run_task(self, url, name, dest, chat_id, size, task_id):
        local_path = os.path.join(DOWNLOAD_DIR, name)

        try:
            self._update_task_status(task_id, "downloading (0%)")
            self._notify(chat_id, f"⬇️ Downloading: {name}")

            local_path = self._download_file(url, local_path, task_id)

            self._update_task_status(task_id, "packaging")

            if os.path.isdir(local_path):
                items = packager.prepare(local_path, dest=dest)
            else:
                items = [{"name": name, "path": local_path, "zipped": False}]

            for item in items:
                if item.get("skipped"):
                    self._notify(chat_id, f"⚠️ Skipped {item['name']}: {item['reason']}")
                    continue

                upload_path = item.get("zip_path") or item["path"]
                self._update_task_status(task_id, f"uploading {item['name']} (0%)")

                if dest == "telegram":
                    self._upload_telegram(upload_path, chat_id, task_id)
                else:
                    self._upload_gdrive(upload_path, chat_id)

            self._update_task_status(task_id, "completed")
            self._notify(chat_id, f"✅ **Completed Transfer**\n\n📁 `{name}`")

        except Exception as e:
            logger.exception("Task failed")
            self._update_task_status(task_id, "error")
            self._notify(chat_id, f"❌ Error: {e}")

        finally:
            with self._tasks_lock:
                self._active_tasks.pop(task_id, None)

    # ─────────────────────────────────────────────
    # DOWNLOAD (HTTP + SFTP)
    # ─────────────────────────────────────────────

    def _download_file(self, url, dest, task_id):
        parsed = urlparse(url)

        if parsed.scheme == "sftp":
            return self._download_sftp(parsed.path, dest, task_id)

        return self._download_http(url, dest, task_id)

    def _download_http(self, url, dest, task_id):
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0

            with open(dest, "wb") as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
                        if total:
                            downloaded += len(chunk)
                            if downloaded % (5 * 1024 * 1024) < 8192:
                                percent = (downloaded / total) * 100
                                self._update_task_status(
                                    task_id, f"downloading ({percent:.1f}%)"
                                )
        return dest

    def _download_sftp(self, remote_path, dest, task_id):
        if not paramiko:
            raise RuntimeError("paramiko not installed")

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        ssh.connect(
            hostname=SEEDBOX_HOST,
            port=SEEDBOX_SFTP_PORT,
            username=SFTP_USER,
            password=SFTP_PASS,
            allow_agent=False,
            look_for_keys=False,
            timeout=30,
        )

        sftp = ssh.open_sftp()

        try:
            attr = sftp.stat(remote_path)

            if str(attr).startswith("d"):
                self._download_sftp_dir(sftp, remote_path, dest, task_id)
            else:
                size = attr.st_size

                def cb(sent, total):
                    if total and sent % (10 * 1024 * 1024) < 8192:
                        percent = (sent / total) * 100
                        self._update_task_status(
                            task_id, f"downloading (SFTP {percent:.1f}%)"
                        )

                sftp.get(remote_path, dest, callback=cb)

        finally:
            sftp.close()
            ssh.close()

        return dest

    def _download_sftp_dir(self, sftp, remote_dir, local_dir, task_id):
        os.makedirs(local_dir, exist_ok=True)

        for entry in sftp.listdir_attr(remote_dir):
            rpath = f"{remote_dir}/{entry.filename}"
            lpath = os.path.join(local_dir, entry.filename)

            if str(entry).startswith("d"):
                self._download_sftp_dir(sftp, rpath, lpath, task_id)
            else:
                sftp.get(rpath, lpath)

    # ─────────────────────────────────────────────
    # TELEGRAM UPLOAD
    # ─────────────────────────────────────────────

    def _upload_telegram(self, path, chat_id, task_id):
        size = os.path.getsize(path)

        if size > MAX_TG_SIZE:
            from bot.utils.splitter import split_file
            parts = split_file(path)
            for i, part in enumerate(parts):
                self._update_task_status(task_id, f"uploading part {i+1}/{len(parts)} (0%)")
                self._upload_telegram_real(part, chat_id, task_id)
                os.remove(part)
        else:
            self._upload_telegram_real(path, chat_id, task_id)

    def _upload_telegram_real(self, path, chat_id, task_id):
        size = os.path.getsize(path)
        thumb = None

        if os.path.splitext(path)[1].lower() in (".mp4", ".mkv", ".avi", ".mov", ".m4v"):
            thumb = generate_thumbnail(path)

        if size > 50 * 1024 * 1024:
            self._upload_telegram_large(path, chat_id, task_id, thumb)
        else:
            self.updater.bot.send_document(
                chat_id=TG_UPLOAD_TARGET or chat_id,
                document=open(path, "rb"),
                caption=os.path.basename(path),
            )

        if thumb and os.path.exists(thumb):
            os.remove(thumb)

    def _upload_telegram_large(self, path, chat_id, task_id, thumb_path):
        from bot.telethon_uploader import get_telethon_uploader
        from bot.telegram_loop import get_telegram_loop
        import asyncio

        uploader = get_telethon_uploader()
        loop = get_telegram_loop()

        def progress(current, total):
            if total and int((current / total) * 100) % 5 == 0:
                percent = (current / total) * 100
                self._update_task_status(task_id, f"uploading ({percent:.1f}%)")

        future = asyncio.run_coroutine_threadsafe(
            uploader.upload_file(
                path,
                chat_id,
                thumb_path=thumb_path,
                progress_callback=progress,
            ),
            loop,
        )
        future.result()

    # ─────────────────────────────────────────────
    # GOOGLE DRIVE
    # ─────────────────────────────────────────────

    def _upload_gdrive(self, path, chat_id=None):
        subprocess.run(["rclone", "copy", path, DRIVE_DEST], check=False)

    # ─────────────────────────────────────────────
    # NOTIFY
    # ─────────────────────────────────────────────

    def _notify(self, chat_id, text):
        if self.updater and chat_id:
            try:
                self.updater.bot.send_message(chat_id=chat_id, text=text)
            except Exception:
                logger.error("Failed to send notification")
