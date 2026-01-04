"""Redis-backed job queue and locking utilities with local fallback.

- If `REDIS_URL` is set, uses redis-py for cross-dyno locking and job storage.
- Otherwise, falls back to in-memory structures (suitable for local tests).
"""

import os
import time
import json
import threading
from typing import Optional, Dict, Any, List

from bot.config import REDIS_URL

if REDIS_URL:
    import redis

# Global storage queue instance (shared across all downloaders)
_global_storage_queue = None
_queue_lock = threading.Lock()

def get_storage_queue(download_dir: str = "downloads", min_free_gb: float = 20.0):
    """Get or create the global storage queue singleton."""
    global _global_storage_queue
    with _queue_lock:
        if _global_storage_queue is None:
            _global_storage_queue = StorageAwareQueue(download_dir, min_free_gb)
        return _global_storage_queue



class RedisUnavailable(RuntimeError):
    pass


class JobQueue:
    def __init__(self):
        self._local_lock = threading.Lock()
        self._local_jobs: Dict[str, Dict[str, Any]] = {}
        if REDIS_URL:
            self._r = redis.from_url(REDIS_URL)
        else:
            self._r = None

    def enqueue(self, job_id: str, payload: Dict[str, Any]):
        if self._r:
            self._r.hset('jobs', job_id, json.dumps(payload))
        else:
            with self._local_lock:
                self._local_jobs[job_id] = payload

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        if self._r:
            v = self._r.hget('jobs', job_id)
            return json.loads(v) if v else None
        else:
            with self._local_lock:
                return self._local_jobs.get(job_id)

    def set_status(self, job_id: str, status: str):
        rec = self.get(job_id) or {}
        rec['status'] = status
        self.enqueue(job_id, rec)


class Lock:
    def __init__(self, name: str, timeout: int = 60):
        self.name = name
        self.timeout = timeout
        self._local = threading.Lock()
        self._r = None
        if REDIS_URL:
            import redis
            self._r = redis.from_url(REDIS_URL)

    def acquire(self) -> bool:
        if self._r:
            # Use SETNX with expiry for simple locking
            now = int(time.time())
            ok = self._r.set(self.name, now, nx=True, ex=self.timeout)
            return bool(ok)
        else:
            return self._local.acquire(blocking=False)

    def release(self):
        if self._r:
            try:
                self._r.delete(self.name)
            except Exception:
                pass
        else:
            try:
                self._local.release()
            except Exception:
                pass


class StorageAwareQueue:
    """Download queue that respects disk space constraints."""
    
    def __init__(self, download_dir: str = "downloads", min_free_gb: float = 5.0):
        self.download_dir = download_dir
        self.min_free_bytes = int(min_free_gb * 1024 * 1024 * 1024)
        self._queue = []
        self._lock = threading.Lock()
        
    def has_space(self, required_bytes: int = 0) -> bool:
        """Check if we have enough disk space."""
        import shutil
        try:
            usage = shutil.disk_usage(self.download_dir)
            available = usage.free
            return available > (self.min_free_bytes + required_bytes)
        except Exception:
            # If we can't check, assume we have space
            return True
    
    def enqueue(self, item: Dict[str, Any]) -> bool:
        """Add item to queue. Returns True if queued, False if space available to process."""
        size = item.get('size', 0)
        
        if self.has_space(size):
            return False  # Don't queue, process immediately
        
        with self._lock:
            self._queue.append(item)
        return True  # Queued
    
    def dequeue(self) -> Optional[Dict[str, Any]]:
        """Dequeue next item if space available."""
        with self._lock:
            if not self._queue:
                return None
            
            # Find first item that fits
            for i, item in enumerate(self._queue):
                if self.has_space(item.get('size', 0)):
                    return self._queue.pop(i)
            
            return None
    
    def pending_count(self) -> int:
        """Get number of pending items."""
        with self._lock:
            return len(self._queue)
    
    def get_queue(self) -> List[Dict[str, Any]]:
        """Get copy of queue."""
        with self._lock:
            return self._queue.copy()
