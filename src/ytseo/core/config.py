import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Load .env from project root (no-op if file doesn't exist)
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = Path(os.environ.get("YTSEO_DATA_DIR", str(PROJECT_ROOT / "data")))
UPLOADS_DIR = DATA_DIR / "uploads"
AUDIO_DIR = DATA_DIR / "audio"
MODELS_DIR = DATA_DIR / "models"

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")

# Ensure directories exist
for d in (UPLOADS_DIR, AUDIO_DIR, MODELS_DIR):
    d.mkdir(parents=True, exist_ok=True)
