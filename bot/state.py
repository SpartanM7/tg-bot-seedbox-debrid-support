import os
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

try:
    import redis
except ImportError:
    redis = None

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# ABSTRACT BASE
# ─────────────────────────────────────────────

class StateManager(ABC):
    @abstractmethod
    def is_seen(self, feed_url: str, item_id: str) -> bool:
        pass

    @abstractmethod
    def add_seen(self, feed_url: str, item_id: str):
        pass

    @abstractmethod
    def set_job(self, job_id: str, data: Dict[str, Any]):
        pass

    @abstractmethod
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def list_jobs(self) -> Dict[str, Dict[str, Any]]:
        pass

    @abstractmethod
    def add_processed(self, item_id: str):
        pass

    @abstractmethod
    def is_processed(self, item_id: str) -> bool:
        pass

    @abstractmethod
    def set_intent(self, item_id: str, dest: str):
        pass

    @abstractmethod
    def get_intent(self, item_id: str) -> Optional[str]:
        pass

    # ───────── NEW (UPLOAD RESUME) ─────────

    @abstractmethod
    def is_uploaded(self, file_hash: str, dest: str) -> bool:
        pass

    @abstractmethod
    def mark_uploaded(self, file_hash: str, dest: str, meta: Dict[str, Any]):
        pass


# ─────────────────────────────────────────────
# REDIS IMPLEMENTATION (PRODUCTION)
# ─────────────────────────────────────────────

class RedisState(StateManager):
    def __init__(self, url: str):
        if redis is None:
            raise ImportError("Redis module not installed")
        self.r = redis.from_url(url, decode_responses=True)
        self.r.ping()
        logger.info("Connected to Redis for state persistence")

    # Existing methods unchanged
    def is_seen(self, feed_url: str, item_id: str) -> bool:
        return bool(self.r.sismember(f"rss:seen:{feed_url}", item_id))

    def add_seen(self, feed_url: str, item_id: str):
        self.r.sadd(f"rss:seen:{feed_url}", item_id)

    def set_job(self, job_id: str, data: Dict[str, Any]):
        self.r.set(f"job:{job_id}", json.dumps(data), ex=86400)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        v = self.r.get(f"job:{job_id}")
        return json.loads(v) if v else None

    def list_jobs(self) -> Dict[str, Dict[str, Any]]:
        out = {}
        for k in self.r.keys("job:*"):
            job_id = k.split(":", 1)[1]
            out[job_id] = json.loads(self.r.get(k))
        return out

    def add_processed(self, item_id: str):
        self.r.sadd("processed_torrents", item_id)

    def is_processed(self, item_id: str) -> bool:
        return bool(self.r.sismember("processed_torrents", item_id))

    def set_intent(self, item_id: str, dest: str):
        self.r.set(f"intent:{item_id}", dest)

    def get_intent(self, item_id: str) -> Optional[str]:
        return self.r.get(f"intent:{item_id}")

    # ───────── UPLOAD RESUME ─────────

    def is_uploaded(self, file_hash: str, dest: str) -> bool:
        key = f"upload:{file_hash}"
        data = self.r.get(key)
        if not data:
            return False
        return bool(json.loads(data).get(dest))

    def mark_uploaded(self, file_hash: str, dest: str, meta: Dict[str, Any]):
        key = f"upload:{file_hash}"
        data = self.r.get(key)
        payload = json.loads(data) if data else {}
        payload.update(meta)
        payload[dest] = True
        payload["ts"] = int(time.time())
        self.r.set(key, json.dumps(payload))


# ─────────────────────────────────────────────
# JSON FILE FALLBACK (LOCAL / DEV)
# ─────────────────────────────────────────────

class JsonFileState(StateManager):
    def __init__(self, filepath: str = "state.json"):
        self.filepath = filepath
        self.data = {
            "seen": {},
            "jobs": {},
            "processed": [],
            "intents": {},
            "uploads": {},   # ← NEW
        }
        self._load()
        logger.info(f"Using local file {filepath} for state persistence")

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    self.data.update(json.load(f))
            except Exception as e:
                logger.error(f"Failed to load state file: {e}")

    def _save(self):
        with open(self.filepath, "w") as f:
            json.dump(self.data, f, indent=2)

    # Existing methods unchanged
    def is_seen(self, feed_url: str, item_id: str) -> bool:
        return item_id in self.data["seen"].get(feed_url, [])

    def add_seen(self, feed_url: str, item_id: str):
        self.data.setdefault("seen", {}).setdefault(feed_url, []).append(item_id)
        self._save()

    def set_job(self, job_id: str, data: Dict[str, Any]):
        self.data["jobs"][job_id] = data
        self._save()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.data["jobs"].get(job_id)

    def list_jobs(self) -> Dict[str, Dict[str, Any]]:
        return self.data.get("jobs", {})

    def add_processed(self, item_id: str):
        self.data.setdefault("processed", []).append(item_id)
        self._save()

    def is_processed(self, item_id: str) -> bool:
        return item_id in self.data.get("processed", [])

    def set_intent(self, item_id: str, dest: str):
        self.data.setdefault("intents", {})[item_id] = dest
        self._save()

    def get_intent(self, item_id: str) -> Optional[str]:
        return self.data.get("intents", {}).get(item_id)

    # ───────── UPLOAD RESUME ─────────

    def is_uploaded(self, file_hash: str, dest: str) -> bool:
        return bool(self.data.get("uploads", {}).get(file_hash, {}).get(dest))

    def mark_uploaded(self, file_hash: str, dest: str, meta: Dict[str, Any]):
        entry = self.data.setdefault("uploads", {}).setdefault(file_hash, {})
        entry.update(meta)
        entry[dest] = True
        entry["ts"] = int(time.time())
        self._save()


# ─────────────────────────────────────────────
# FACTORY
# ─────────────────────────────────────────────

def get_state() -> StateManager:
    from bot.config import REDIS_URL
    if REDIS_URL:
        try:
            return RedisState(REDIS_URL)
        except Exception as e:
            logger.warning(f"Redis failed, falling back to file: {e}")
    return JsonFileState()
