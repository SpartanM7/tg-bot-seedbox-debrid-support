import os
import subprocess
import logging

logger = logging.getLogger(__name__)

def generate_thumbnail(video_path: str) -> str:
    """Generates a JPG thumbnail for a video file. Returns path to thumbnail or None."""
    if not os.path.exists(video_path):
        return None

    # Check for ffmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except Exception:
        logger.warning("ffmpeg not found, thumbnail generation skipped")
        return None

    thumb_path = video_path + ".thumb.jpg"
    
    # Command: extract frame at 10% or 5s, whichever is first
    # We use -ss 00:00:05 as a simple heuristic
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-ss", "00:00:05",
        "-vframes", "1",
        "-q:v", "2",
        thumb_path
    ]
    
    try:
        # Run quietly
        subprocess.run(cmd, capture_output=True, check=True)
        if os.path.exists(thumb_path):
            return thumb_path
    except Exception as e:
        logger.error(f"Thumbnail generation failed for {video_path}: {e}")
        
    return None
