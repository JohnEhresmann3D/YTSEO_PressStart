"""Persistent OAuth token storage + in-memory pending-flow tracker.

Tokens are written to ``DATA_DIR/tokens.json`` (gitignored). Pending OAuth
state values are kept in memory only — they expire after 30 minutes.
"""

from __future__ import annotations

import json
import time
from threading import Lock

from ytseo.core.config import DATA_DIR

TOKENS_FILE = DATA_DIR / "tokens.json"

_io_lock = Lock()
_pending: dict[str, dict] = {}
_PENDING_TTL_S = 30 * 60


def _load() -> dict:
    if not TOKENS_FILE.exists():
        return {}
    try:
        return json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(tokens: dict) -> None:
    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2), encoding="utf-8")


def load_tokens() -> dict:
    with _io_lock:
        return _load()


def get_token(platform: str) -> dict | None:
    with _io_lock:
        return _load().get(platform)


def set_token(platform: str, token: dict) -> None:
    with _io_lock:
        tokens = _load()
        tokens[platform] = token
        _save(tokens)


def remove_token(platform: str) -> None:
    with _io_lock:
        tokens = _load()
        tokens.pop(platform, None)
        _save(tokens)


def has_token(platform: str) -> bool:
    return get_token(platform) is not None


def store_pending(state: str, data: dict) -> None:
    """Stash transient OAuth flow data (verifier, redirect_uri, platform) for callback."""
    now = time.time()
    _pending[state] = {**data, "created_at": now}
    cutoff = now - _PENDING_TTL_S
    for k in [k for k, v in _pending.items() if v.get("created_at", 0) < cutoff]:
        _pending.pop(k, None)


def pop_pending(state: str) -> dict | None:
    return _pending.pop(state, None)
