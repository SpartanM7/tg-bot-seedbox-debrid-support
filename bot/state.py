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


    # ───────── UPLOAD RESUME ─────────


    @abstractmethod
    def is_uploaded(self, file_hash: str, dest: str) -> bool:
        pass


    @abstractmethod
    def mark_uploaded(self, file_hash: str, dest: str, meta: Dict[str, Any]):
        pass


    # ───────── RSS FEEDS ─────────


    @abstractmethod
    def get_rss_feeds(self) -> List[Dict[str, Any]]:
        """Get all RSS feeds configuration"""
        pass


    @abstractmethod
    def save_rss_feeds(self, feeds: List[Dict[str, Any]]):
        """Save RSS feeds configuration"""
        pass


    @abstractmethod
    def add_rss_item_status(self, feed_url: str, item_id: str, title: str, status: str, error: str = None):
        """Track RSS item processing status (added, downloading, downloaded, uploading, uploaded, failed)"""
        pass


    @abstractmethod
    def get_rss_item_status(self, feed_url: str, item_id: str) -> Optional[Dict[str, Any]]:
        """Get RSS item status"""
        pass


    @abstractmethod
    def list_rss_items_by_status(self, status: str) -> List[Dict[str, Any]]:
        """List all RSS items with a specific status (e.g., 'upload_failed')"""
        pass


    @abstractmethod
    def get_rss_feed_stats(self, feed_url: str) -> Dict[str, int]:
        """Get statistics for a feed (total, uploaded, failed, etc.)"""
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


    # ───────── RSS FEEDS ─────────


    def get_rss_feeds(self) -> List[Dict[str, Any]]:
        """Get all RSS feeds from Redis"""
        data = self.r.get("rss:feeds")
        if not data:
            return []
        return json.loads(data)


    def save_rss_feeds(self, feeds: List[Dict[str, Any]]):
        """Save RSS feeds to Redis"""
        self.r.set("rss:feeds", json.dumps(feeds))


    def add_rss_item_status(self, feed_url: str, item_id: str, title: str, status: str, error: str = None):
        """
        Track RSS item processing status
        Statuses: added, downloading, downloaded, uploading, uploaded, download_failed, upload_failed
        """
        key = f"rss:item:{feed_url}:{item_id}"
        data = {
            "feed_url": feed_url,
            "item_id": item_id,
            "title": title,
            "status": status,
            "error": error,
            "updated_at": int(time.time())
        }

        # Store item data
        self.r.set(key, json.dumps(data))

        # Add to status index for fast lookups
        self.r.sadd(f"rss:status:{status}", key)

        # Remove from old status sets (if status changed)
        for old_status in ["added", "downloading", "downloaded", "uploading", "uploaded", "download_failed", "upload_failed"]:
            if old_status != status:
                self.r.srem(f"rss:status:{old_status}", key)

        # Keep 30 days
        self.r.expire(key, 86400 * 30)


    def get_rss_item_status(self, feed_url: str, item_id: str) -> Optional[Dict[str, Any]]:
        """Get RSS item status"""
        key = f"rss:item:{feed_url}:{item_id}"
        data = self.r.get(key)
        if not data:
            return None
        return json.loads(data)


    def list_rss_items_by_status(self, status: str) -> List[Dict[str, Any]]:
        """List all RSS items with a specific status"""
        items = []
        keys = self.r.smembers(f"rss:status:{status}")
        for key in keys:
            data = self.r.get(key)
            if data:
                items.append(json.loads(data))
        return items


    def get_rss_feed_stats(self, feed_url: str) -> Dict[str, int]:
        """Get statistics for a specific RSS feed"""
        stats = {
            "total": 0,
            "uploaded": 0,
            "downloading": 0,
            "uploading": 0,
            "download_failed": 0,
            "upload_failed": 0,
        }

        # Count items by status
        pattern = f"rss:item:{feed_url}:*"
        for key in self.r.keys(pattern):
            data = self.r.get(key)
            if data:
                item = json.loads(data)
                stats["total"] += 1
                status = item.get("status", "unknown")
                if status in stats:
                    stats[status] += 1

        return stats



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
            "uploads": {},
            "rss_feeds": [],           # ← NEW
            "rss_items": {},           # ← NEW: {feed_url: {item_id: {status, title, etc}}}
        }
        self._load()
        logger.info(f"Using local file {filepath} for state persistence")


    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    loaded = json.load(f)
                    self.data.update(loaded)
                    # Ensure new keys exist
                    self.data.setdefault("rss_feeds", [])
                    self.data.setdefault("rss_items", {})
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


    # ───────── RSS FEEDS ─────────


    def get_rss_feeds(self) -> List[Dict[str, Any]]:
        """Get all RSS feeds"""
        return self.data.get("rss_feeds", [])


    def save_rss_feeds(self, feeds: List[Dict[str, Any]]):
        """Save RSS feeds"""
        self.data["rss_feeds"] = feeds
        self._save()


    def add_rss_item_status(self, feed_url: str, item_id: str, title: str, status: str, error: str = None):
        """Track RSS item processing status"""
        items = self.data.setdefault("rss_items", {}).setdefault(feed_url, {})
        items[item_id] = {
            "feed_url": feed_url,
            "item_id": item_id,
            "title": title,
            "status": status,
            "error": error,
            "updated_at": int(time.time())
        }
        self._save()


    def get_rss_item_status(self, feed_url: str, item_id: str) -> Optional[Dict[str, Any]]:
        """Get RSS item status"""
        return self.data.get("rss_items", {}).get(feed_url, {}).get(item_id)


    def list_rss_items_by_status(self, status: str) -> List[Dict[str, Any]]:
        """List all RSS items with a specific status"""
        items = []
        for feed_url, feed_items in self.data.get("rss_items", {}).items():
            for item_id, item_data in feed_items.items():
                if item_data.get("status") == status:
                    items.append(item_data)
        return items


    def get_rss_feed_stats(self, feed_url: str) -> Dict[str, int]:
        """Get statistics for a specific RSS feed"""
        stats = {
            "total": 0,
            "uploaded": 0,
            "downloading": 0,
            "uploading": 0,
            "download_failed": 0,
            "upload_failed": 0,
        }

        feed_items = self.data.get("rss_items", {}).get(feed_url, {})
        for item_id, item_data in feed_items.items():
            stats["total"] += 1
            status = item_data.get("status", "unknown")
            if status in stats:
                stats[status] += 1

        return stats



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
