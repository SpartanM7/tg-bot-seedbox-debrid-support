import os
import subprocess
import math
import logging
from typing import List

logger = logging.getLogger(__name__)

# 1.9 GB to be safe
CHUNK_SIZE = 1900 * 1024 * 1024 

def split_file(path: str) -> List[str]:
    """Split a file into parts if it exceeds CHUNK_SIZE.
    Returns a list of paths to the parts.
    """
    size = os.path.getsize(path)
    if size <= CHUNK_SIZE:
        return [path]

    ext = os.path.splitext(path)[1].lower()
    # Video extensions that ffmpeg should handle
    if ext in ['.mp4', '.mkv', '.avi', '.mov', '.m4v', '.flv', '.wmv']:
        return _split_video(path)
    else:
        return _split_binary(path)

def _split_binary(path: str) -> List[str]:
    logger.info(f"Splitting binary file: {path}")
    parts = []
    base_name = os.path.basename(path)
    dir_name = os.path.dirname(path)
    
    # Use a small buffer to avoid memory spikes
    BUFFER_SIZE = 1024 * 1024 # 1MB
    
    with open(path, 'rb') as f:
        part_idx = 1
        while True:
            part_path = os.path.join(dir_name, f"{base_name}.part{part_idx:03d}")
            bytes_written = 0
            
            with open(part_path, 'wb') as out:
                while bytes_written < CHUNK_SIZE:
                    chunk = f.read(min(BUFFER_SIZE, CHUNK_SIZE - bytes_written))
                    if not chunk:
                        break
                    out.write(chunk)
                    bytes_written += len(chunk)
            
            if bytes_written == 0:
                # No more data read, delete the empty part file and break
                if os.path.exists(part_path):
                    os.remove(part_path)
                break
                
            parts.append(part_path)
            logger.info(f"Created part: {os.path.basename(part_path)} ({bytes_written / 1024**2:.1f} MB)")
            part_idx += 1
            
    return parts

def _split_video(path: str) -> List[str]:
    logger.info(f"Splitting video file: {path}")
    try:
        duration = _get_duration(path)
        size = os.path.getsize(path)
        
        if duration <= 0:
            logger.warning(f"Could not determine duration for {path}, falling back to binary split.")
            return _split_binary(path)

        num_parts = math.ceil(size / CHUNK_SIZE)
        # Calculate time per part
        time_per_part = duration / num_parts
        
        parts = []
        base_name = os.path.basename(path)
        name_no_ext, ext = os.path.splitext(base_name)
        dir_name = os.path.dirname(path)
        
        # Pattern for generated segments
        output_pattern = os.path.join(dir_name, f"{name_no_ext}_part%03d{ext}")
        
        cmd = [
            "ffmpeg", "-i", path,
            "-c", "copy",
            "-map", "0",
            "-f", "segment",
            "-segment_time", str(time_per_part),
            "-reset_timestamps", "1",
            output_pattern
        ]
        
        logger.info(f"Running ffmpeg split: {' '.join(cmd)}")
        subprocess.run(cmd, capture_output=True, check=True)
        
        # Collect generated files
        for i in range(num_parts + 5): # extra buffer
            p = os.path.join(dir_name, f"{name_no_ext}_part{i:03d}{ext}")
            if os.path.exists(p):
                parts.append(p)
        
        if not parts:
            logger.error("FFmpeg produced no parts.")
            return _split_binary(path)
            
        return parts

    except Exception as e:
        logger.error(f"FFmpeg split failed for {path}: {e}. Falling back to binary split.")
        return _split_binary(path)

def _get_duration(path: str) -> float:
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return float(res.stdout.strip())
    except Exception as e:
        logger.debug(f"ffprobe failed: {e}")
        return 0.0
