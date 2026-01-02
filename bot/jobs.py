"""Background job runner for yt-dlp and similar long-running tasks.

- Uses ThreadPoolExecutor for background execution
- Enforces runtime timeout (env var YTDL_MAX_RUNTIME)
- Provides simple job tracking in memory (job id -> status)
"""

import os
import uuid
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any

from bot.queue import JobQueue, Lock

YTDL_MAX_RUNTIME = int(os.getenv("YTDL_MAX_RUNTIME", 600))  # seconds
YTDL_CMD = os.getenv("YTDL_CMD", "yt-dlp")

_executor = ThreadPoolExecutor(max_workers=2)
_jobs_lock = threading.Lock()
_local_jobs: Dict[str, Dict[str, Any]] = {}
_queue = JobQueue()


def _run_ytdl(job_id: str, url: str, out_dir: str = None):
    # Update central queue status
    _queue.set_status(job_id, 'running')
    cmd = [YTDL_CMD, url]
    if out_dir:
        cmd.extend(["-o", os.path.join(out_dir, "%(title)s.%(ext)s")])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=YTDL_MAX_RUNTIME)
        status = 'done' if proc.returncode == 0 else 'failed'
        _queue.enqueue(job_id, {'url': url, 'out_dir': out_dir, 'status': status, 'returncode': proc.returncode, 'stdout': proc.stdout, 'stderr': proc.stderr})
    except subprocess.TimeoutExpired as exc:
        _queue.enqueue(job_id, {'url': url, 'out_dir': out_dir, 'status': 'timeout', 'stderr': str(exc)})
    except Exception as exc:
        _queue.enqueue(job_id, {'url': url, 'out_dir': out_dir, 'status': 'error', 'stderr': str(exc)})


def enqueue_ytdl(url: str, out_dir: str = None) -> str:
    jid = str(uuid.uuid4())
    _queue.enqueue(jid, {'url': url, 'out_dir': out_dir, 'status': 'queued'})
    _executor.submit(_run_ytdl, jid, url, out_dir)
    return jid


def job_status(job_id: str) -> Dict[str, Any]:
    return _queue.get(job_id) or {'status': 'unknown'}
