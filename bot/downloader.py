"""
Downloader module for retrieving files and uploading them.

Handles:
- Downloading from HTTP links (Real-Debrid / direct)
- Downloading from SFTP (Seedbox / rTorrent)
- Recursive upload of all files (no directory uploads)
- Uploading to Telegram (split if large)
- Uploading to Google Drive (rclone)
- Upload resume & deduplication via state hash tracking
- File count tracking for status display
"""

import os
import time
import threading
import requests
import logging
import subprocess
import stat
import hashlib
from typing import List, Optional, Dict, Any

try:
    import paramiko
except ImportError:
    paramiko = None

from bot.config import (
    SEEDBOX_HOST,
    SEEDBOX_SFTP_PORT,
    SFTP_USER,
    SFTP_PASS,
    DRIVE_DEST,
    MAX_ZIP_SIZE_BYTES,
)
from bot.state import get_state
from bot.splitter import split_file
from bot.telethon_uploader import telethon_upload_file
from bot.packager import create_7z_archive

logger = logging.getLogger(__name__)

MAX_TG_SIZE = int(os.getenv("MAX_TG_SIZE", str(2 * 1024 * 1024 * 1024)))  # 2GB default
MAX_ZIP_SIZE = int(MAX_ZIP_SIZE_BYTES or 100 * 1024 * 1024)  # 100MB default


def count_sftp_files(sftp, path):
    """Recursively count files in SFTP directory."""
    count = 0
    try:
        for entry in sftp.listdir_attr(path):
            full_path = f"{path}/{entry.filename}"
            if stat.S_ISDIR(entry.st_mode):
                count += count_sftp_files(sftp, full_path)
            else:
                count += 1
    except Exception as e:
        logger.error(f"Error counting SFTP files in {path}: {e}")
    return count


def hash_file(filepath: str) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


class Downloader:
    """Handles downloading and uploading of files."""

    def __init__(self, telegram_updater=None):
        self.updater = telegram_updater
        self._lock = threading.Lock()
        self._active_tasks = {}

    def get_active_tasks(self) -> dict:
        """Return a copy of active tasks for status display."""
        with self._lock:
            return self._active_tasks.copy()

    def _update_task_status(self, task_id, status, progress=None, uploaded_files=None, total_files=None):
        """Update task status with optional progress and file count."""
        with self._lock:
            if task_id in self._active_tasks:
                self._active_tasks[task_id]["status"] = status
                if progress is not None:
                    self._active_tasks[task_id]["progress_percent"] = progress
                if uploaded_files is not None:
                    self._active_tasks[task_id]["uploaded_files"] = uploaded_files
                if total_files is not None:
                    self._active_tasks[task_id]["total_files"] = total_files

    def _register_task(self, task_id, name, status="starting"):
        """Register a new active task."""
        with self._lock:
            self._active_tasks[task_id] = {
                "name": name,
                "status": status,
                "start_time": time.time(),
                "total_files": 0,
                "uploaded_files": 0,
                "progress_percent": 0.0,
            }

    def _unregister_task(self, task_id):
        """Remove task from active list."""
        with self._lock:
            self._active_tasks.pop(task_id, None)

    def process_item(self, url, name, dest="telegram", chat_id=None, size=0):
        """Main entry point: download and upload a file or folder."""
        task_id = f"{int(time.time())}_{name[:20]}"
        self._register_task(task_id, name, "queued")

        t = threading.Thread(
            target=self._process_item_worker,
            args=(task_id, url, name, dest, chat_id, size),
            daemon=True,
        )
        t.start()

    def _process_item_worker(self, task_id, url, name, dest, chat_id, size):
        """Background worker for processing items."""
        try:
            self._update_task_status(task_id, "downloading")

            if url.startswith("sftp://"):
                remote_path = url[7:]
                local_path = f"/tmp/{name}"
                self._download_sftp(remote_path, local_path, task_id)
            else:
                local_path = f"/tmp/{name}"
                self._download_http(url, local_path, task_id, size)

            # Upload
            self._update_task_status(task_id, "uploading")
            self._upload(local_path, name, dest, chat_id, task_id)

            logger.info(f"✅ Completed: {name}")

        except Exception as e:
            logger.error(f"❌ Error processing {name}: {e}")
            self._update_task_status(task_id, f"error: {e}")
        finally:
            time.sleep(5)
            self._unregister_task(task_id)

    def _download_http(self, url, dest, task_id, expected_size=0):
        """Download file from HTTP URL with progress tracking."""
        self._update_task_status(task_id, "downloading")

        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()

        total_size = int(r.headers.get("content-length", expected_size))
        downloaded = 0

        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    # Update progress every 1MB
                    if total_size > 0 and downloaded % (1024 * 1024) == 0:
                        progress = (downloaded / total_size) * 100
                        self._update_task_status(task_id, "downloading", progress=progress)

        logger.info(f"Downloaded {dest} ({downloaded} bytes)")
        return dest

    def _download_sftp(self, remote_path, dest, task_id):
        """Download file or directory from SFTP."""
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
        )

        sftp = ssh.open_sftp()
        try:
            attr = sftp.stat(remote_path)
            if stat.S_ISDIR(attr.st_mode):
                total = count_sftp_files(sftp, remote_path)
                self._update_task_status(task_id, "downloading", total_files=total, uploaded_files=0)
                self._download_sftp_dir(sftp, remote_path, dest, task_id, total, [0])
            else:
                self._update_task_status(task_id, "downloading", total_files=1)
                sftp.get(remote_path, dest)
                self._update_task_status(task_id, "downloading", uploaded_files=1)
        finally:
            sftp.close()
            ssh.close()
        return dest

    def _download_sftp_dir(self, sftp, remote_path, local_path, task_id, total, counter):
        """Recursively download directory from SFTP with file counting."""
        os.makedirs(local_path, exist_ok=True)

        for entry in sftp.listdir_attr(remote_path):
            remote_file = f"{remote_path}/{entry.filename}"
            local_file = os.path.join(local_path, entry.filename)

            if stat.S_ISDIR(entry.st_mode):
                self._download_sftp_dir(sftp, remote_file, local_file, task_id, total, counter)
            else:
                sftp.get(remote_file, local_file)
                counter[0] += 1
                # Update status with file count
                self._update_task_status(
                    task_id, 
                    f"Downloading (Sftp {counter[0]}/{total} Files)",
                    uploaded_files=counter[0],
                    total_files=total
                )
                logger.debug(f"Downloaded {remote_file} -> {local_file} ({counter[0]}/{total})")

    def _upload(self, local_path, name, dest, chat_id, task_id):
        """Upload file or folder to destination."""
        state = get_state()

        if os.path.isdir(local_path):
            files = []
            for root, dirs, filenames in os.walk(local_path):
                for fn in filenames:
                    files.append(os.path.join(root, fn))

            total_files = len(files)
            self._update_task_status(task_id, "uploading", total_files=total_files, uploaded_files=0)

            for idx, fpath in enumerate(files, 1):
                fhash = hash_file(fpath)
                if state.is_uploaded(fhash, dest):
                    logger.info(f"Skipping already uploaded: {fpath}")
                    self._update_task_status(task_id, "uploading", uploaded_files=idx)
                    continue

                self._upload_single_file(fpath, dest, chat_id, task_id)
                state.mark_uploaded(fhash, dest, {"name": os.path.basename(fpath)})

                # Update file progress
                self._update_task_status(task_id, "uploading", uploaded_files=idx)
        else:
            # Single file
            self._update_task_status(task_id, "uploading", total_files=1, uploaded_files=0)
            fhash = hash_file(local_path)
            if not state.is_uploaded(fhash, dest):
                self._upload_single_file(local_path, dest, chat_id, task_id)
                state.mark_uploaded(fhash, dest, {"name": name})
            self._update_task_status(task_id, "uploading", uploaded_files=1)

    def _upload_single_file(self, filepath, dest, chat_id, task_id):
        """Upload a single file to the specified destination."""
        fname = os.path.basename(filepath)
        fsize = os.path.getsize(filepath)

        if dest == "gdrive":
            self._upload_to_gdrive(filepath, task_id)
        elif dest == "telegram":
            self._upload_to_telegram(filepath, chat_id, task_id)
        else:
            logger.warning(f"Unknown dest '{dest}', defaulting to telegram")
            self._upload_to_telegram(filepath, chat_id, task_id)

    def _upload_to_gdrive(self, filepath, task_id):
        """Upload file to Google Drive using rclone."""
        self._update_task_status(task_id, "uploading to gdrive")
        cmd = ["rclone", "copy", filepath, DRIVE_DEST, "-P"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"rclone failed: {result.stderr}")
        logger.info(f"Uploaded to GDrive: {filepath}")

    def _upload_to_telegram(self, filepath, chat_id, task_id):
        """Upload file to Telegram with splitting if needed."""
        if not chat_id:
            logger.warning("No chat_id provided for Telegram upload")
            return

        fsize = os.path.getsize(filepath)

        if fsize <= MAX_TG_SIZE:
            # Direct upload
            self._update_task_status(task_id, "uploading to telegram")
            telethon_upload_file(filepath, chat_id)
        else:
            # Split and upload
            self._update_task_status(task_id, "splitting file")
            parts = split_file(filepath, MAX_TG_SIZE)

            total_parts = len(parts)
            self._update_task_status(task_id, "uploading to telegram", total_files=total_parts, uploaded_files=0)

            for idx, part in enumerate(parts, 1):
                telethon_upload_file(part, chat_id)
                self._update_task_status(task_id, "uploading to telegram", uploaded_files=idx)
                os.remove(part)

        logger.info(f"Uploaded to Telegram: {filepath}")
