
import os
import zipfile
import threading
from typing import List, Dict, Any

ZIP_KEYWORDS = ("pic", "pics", "image", "images")
_lock = threading.Lock()
MAX_ZIP_SIZE_BYTES = int(os.getenv("MAX_ZIP_SIZE_BYTES", 100 * 1024 * 1024))  # default 100MB


def should_zip(name: str) -> bool:
    """Return True if folder name matches image keywords (case-insensitive)."""
    return any(k in name.lower() for k in ZIP_KEYWORDS)


def folder_size_bytes(folder: str) -> int:
    """Return total size in bytes of all files inside a folder."""
    total = 0
    for root, _, files in os.walk(folder):
        for f in files:
            full = os.path.join(root, f)
            try:
                total += os.path.getsize(full)
            except OSError:
                # If file disappears, skip it
                continue
    return total


def zip_folder(folder: str) -> str:
    """Zip a folder and return the path to the created zip file."""
    z = folder + ".zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(folder):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, folder)
                zipf.write(full, rel)
    return z


def prepare(base: str, dest: str = "telegram") -> List[Dict[str, Any]]:
    """
    Prepare items under `base` for upload.

    Parameters:
    - base: directory to scan
    - dest: "telegram" or "gdrive" (affects behavior for large folders)

    Returns a list of dicts with keys:
    - name: original entry name
    - path: path to file or folder
    - zipped: bool
    - zip_path: path to zip if zipped
    - skipped: bool
    - reason: reason for skip if any
    """
    results: List[Dict[str, Any]] = []
    with _lock:
        for n in os.listdir(base):
            p = os.path.join(base, n)
            record = {"name": n, "path": p, "zipped": False, "zip_path": None, "skipped": False, "reason": None}
            if os.path.isdir(p) and should_zip(n):
                size = folder_size_bytes(p)
                if size > MAX_ZIP_SIZE_BYTES and dest.lower() == "telegram":
                    record["skipped"] = True
                    record["reason"] = f"folder too large for Telegram ({size} bytes)"
                else:
                    # zip it
                    zip_path = zip_folder(p)
                    record["zipped"] = True
                    record["zip_path"] = zip_path
            results.append(record)
    return results
