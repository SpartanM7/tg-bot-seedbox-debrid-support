"""Background job runner for yt-dlp and similar long-running tasks.

- Uses ThreadPoolExecutor for background execution
- Persists job status via bot.state
- Enforces runtime timeout
"""

import os
import uuid
import threading
import subprocess
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any

from bot.state import get_state
from bot.downloader import Downloader

logger = logging.getLogger(__name__)

YTDL_MAX_RUNTIME = int(os.getenv("YTDL_MAX_RUNTIME", 600))  # seconds
YTDL_CMD = os.getenv("YTDL_CMD", "yt-dlp")

_executor = ThreadPoolExecutor(max_workers=2)
_state_manager = get_state()
_updater = None

def set_updater(updater):
    global _updater
    _updater = updater

def _run_ytdl(job_id: str, url: str, out_dir: str = None, dest: str = "telegram", chat_id: int = None):
    # Update status to running
    logger.info(f"Starting job {job_id} for {url}")
    _state_manager.set_job(job_id, {
        'url': url, 
        'out_dir': out_dir, 
        'status': 'running', 
        'start_time': time.time()
    })

    cmd = [YTDL_CMD, url]
    
    # Check for disk space before starting
    from bot.queue import get_storage_queue
    storage_queue = get_storage_queue()
    if not storage_queue.has_space():
        logger.warning(f"Job {job_id} paused: low disk space")
        _state_manager.set_job(job_id, {
            'url': url,
            'status': 'paused',
            'reason': 'low disk space',
            'start_time': time.time()
        })
        # Note: In a real production system, we'd wait or re-enqueue. 
        # For now, we fail fast to avoid crashing the dyno, or we can loop.
        # Let's simple check and fail for now, or the user can retry.
        # Improvement: actually wait for space.
        return

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        # Using specific template to easily find file? 
        # Actually yt-dlp might download multiple files.
        # We'll simple scan out_dir after download if it's unique to this job.
        # For multithreading safety, use unique out_dir per job?
        # Current design assumes out_dir is shared or unique.
        # Let's use unique folder for this job to identify files easily.
        job_dir = os.path.join(out_dir, job_id) if out_dir else os.path.join("downloads", job_id)
        os.makedirs(job_dir, exist_ok=True)
        cmd.extend(["-o", os.path.join(job_dir, "%(title)s.%(ext)s")])
    else:
        # Default temp dir
        job_dir = os.path.join("downloads", job_id)
        os.makedirs(job_dir, exist_ok=True)
        cmd.extend(["-o", os.path.join(job_dir, "%(title)s.%(ext)s")])
    
    # Restrict output format to avoid huge files if needed, or let user decide.
    # We default to something reasonable if not specified, but yt-dlp defaults are usually okay.

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=YTDL_MAX_RUNTIME)
        status = 'done' if proc.returncode == 0 else 'failed'
        
        result_data = {
            'url': url,
            'out_dir': out_dir,
            'status': status,
            'returncode': proc.returncode,
            'end_time': time.time()
        }
        
        # Only save stderr if failed to save space
        if status == 'failed':
            result_data['stderr'] = proc.stderr[-1000:] # last 1000 chars
        
        _state_manager.set_job(job_id, result_data)
        logger.info(f"Job {job_id} finished with status {status}")

        if status == 'done':
            # Trigger upload
            # Find files in job_dir
            if _updater:
                downloader = Downloader(_updater)
                for f in os.listdir(job_dir):
                    fpath = os.path.join(job_dir, f)
                    if os.path.isfile(fpath):
                        downloader.upload_local_file(fpath, dest=dest, chat_id=chat_id)
            
            # Cleanup
            try:
                import shutil
                shutil.rmtree(job_dir)
            except Exception as e:
                logger.error(f"Failed to cleanup {job_dir}: {e}")

    except subprocess.TimeoutExpired as exc:
        _state_manager.set_job(job_id, {
            'url': url, 
            'out_dir': out_dir, 
            'status': 'timeout', 
            'stderr': str(exc),
            'end_time': time.time()
        })
        logger.warning(f"Job {job_id} timed out")
    except Exception as exc:
        _state_manager.set_job(job_id, {
            'url': url, 
            'out_dir': out_dir, 
            'status': 'error', 
            'stderr': str(exc),
            'end_time': time.time()
        })
        logger.exception(f"Job {job_id} failed with exception")


def enqueue_ytdl(url: str, out_dir: str = None, dest: str = "telegram", chat_id: int = None) -> str:
    jid = str(uuid.uuid4())
    initial_state = {'url': url, 'out_dir': out_dir, 'status': 'queued', 'created_at': time.time()}
    _state_manager.set_job(jid, initial_state)
    _executor.submit(_run_ytdl, jid, url, out_dir, dest, chat_id)
    return jid


def job_status(job_id: str) -> Dict[str, Any]:
    return _state_manager.get_job(job_id) or {'status': 'unknown'}
