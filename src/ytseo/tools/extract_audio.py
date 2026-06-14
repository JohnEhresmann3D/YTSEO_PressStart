"""Extract audio from video files using ffmpeg."""

import subprocess
import uuid
from pathlib import Path

from ytseo.core.config import AUDIO_DIR


def extract_audio(video_path: str) -> str:
    """Extract audio from a video file as 16kHz mono WAV for Whisper.

    Args:
        video_path: Absolute path to the video file.

    Returns:
        Absolute path to the extracted WAV file.
    """
    video = Path(video_path)
    if not video.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    output_name = f"{video.stem}_{uuid.uuid4().hex[:8]}.wav"
    output_path = AUDIO_DIR / output_name

    cmd = [
        "ffmpeg", "-i", str(video),
        "-vn",                    # no video
        "-acodec", "pcm_s16le",   # 16-bit PCM
        "-ar", "16000",           # 16kHz sample rate
        "-ac", "1",               # mono
        "-y",                     # overwrite
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[:500]}")

    return str(output_path)
