"""Redis-backed job queue and locking utilities with local fallback.

- If `REDIS_URL` is set, uses redis-py for cross-dyno locking and job storage.
- Otherwise, falls back to in-memory structures (suitable for local tests).
"""

import os
import time
import json
import threading
from typing import Optional, Dict, Any

REDIS_URL = os.getenv('REDIS_URL')

if REDIS_URL:
    import redis


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
