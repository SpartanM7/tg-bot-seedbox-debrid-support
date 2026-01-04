import os
import json
import logging
import json
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

try:
    import redis
except ImportError:
    redis = None

logger = logging.getLogger(__name__)

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

class RedisState(StateManager):
    def __init__(self, url: str):
        if redis is None:
            raise ImportError("Redis module not installed")
        self.r = redis.from_url(url, decode_responses=True)
        # Verify connection
        self.r.ping()
        logger.info("Connected to Redis for state persistence")

    def is_seen(self, feed_url: str, item_id: str) -> bool:
        return bool(self.r.sismember(f"rss:seen:{feed_url}", item_id))

    def add_seen(self, feed_url: str, item_id: str):
        self.r.sadd(f"rss:seen:{feed_url}", item_id)

    def set_job(self, job_id: str, data: Dict[str, Any]):
        # Store as simple JSON string or hash. JSON string is easier for structure.
        self.r.set(f"job:{job_id}", json.dumps(data), ex=86400) # 24h expiry

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        data = self.r.get(f"job:{job_id}")
        if data:
            return json.loads(data)
        return None

    def list_jobs(self) -> Dict[str, Dict[str, Any]]:
        keys = self.r.keys("job:*")
        jobs = {}
        for k in keys:
            job_id = k.split(":", 1)[1]
            data = self.r.get(k)
            if data:
                jobs[job_id] = json.loads(data)
        return jobs

    def add_processed(self, item_id: str):
        self.r.sadd("processed_torrents", item_id)

    def is_processed(self, item_id: str) -> bool:
        return bool(self.r.sismember("processed_torrents", item_id))

    def set_intent(self, item_id: str, dest: str):
        self.r.set(f"intent:{item_id}", dest)

    def get_intent(self, item_id: str) -> Optional[str]:
        v = self.r.get(f"intent:{item_id}")
        return v if v else None

class JsonFileState(StateManager):
    def __init__(self, filepath: str = "state.json"):
        self.filepath = filepath

        self.data = {
            "seen": {},  # type: Dict[str, List[str]]
            "jobs": {},   # type: Dict[str, Dict[str, Any]]
            "processed": [], # type: List[str]
            "intents": {} # type: Dict[str, str]
        }
        self._load()
        logger.info(f"Using local file {filepath} for state persistence")

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f:
                    self.data = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load state file: {e}")

    def _save(self):
        try:
            with open(self.filepath, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state file: {e}")

    def is_seen(self, feed_url: str, item_id: str) -> bool:
        # seen dict maps feed_url -> list of item_ids
        seen_list = self.data["seen"].get(feed_url, [])
        return item_id in seen_list

    def add_seen(self, feed_url: str, item_id: str):
        if feed_url not in self.data["seen"]:
            self.data["seen"][feed_url] = []
        if item_id not in self.data["seen"][feed_url]:
            self.data["seen"][feed_url].append(item_id)
            self._save()

    def set_job(self, job_id: str, data: Dict[str, Any]):
        self.data["jobs"][job_id] = data
        self._save()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.data["jobs"].get(job_id)

    def list_jobs(self) -> Dict[str, Dict[str, Any]]:
        return self.data.get("jobs", {})

    def add_processed(self, item_id: str):
        if "processed" not in self.data:
            self.data["processed"] = []
        if item_id not in self.data["processed"]:
            self.data["processed"].append(item_id)
            self._save()

    def is_processed(self, item_id: str) -> bool:
        return item_id in self.data.get("processed", [])

    def set_intent(self, item_id: str, dest: str):
        if "intents" not in self.data:
            self.data["intents"] = {}
        self.data["intents"][item_id] = dest
        self._save()

    def get_intent(self, item_id: str) -> Optional[str]:
        return self.data.get("intents", {}).get(item_id)

def get_state() -> StateManager:
    from bot.config import REDIS_URL
    if REDIS_URL:
        try:
            return RedisState(REDIS_URL)
        except Exception as e:
            logger.warning(f"Redis configured but failed to connect: {e}. Falling back to file.")
    return JsonFileState()
