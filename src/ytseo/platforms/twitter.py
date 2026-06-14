"""X (Twitter) API v2 — OAuth 2.0 PKCE + chunked media upload + post tweet.

Notes:
- Chunked media upload uses INIT / APPEND / FINALIZE / STATUS on /2/media/upload.
- Posting endpoint is /2/tweets (v2). The newer alias /2/posts also exists.
- Required user scopes: tweet.write, media.write, users.read, offline.access.
- Free-tier X developer accounts may not have media.write — Basic tier may be required.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import time
from urllib.parse import urlencode

import httpx

log = logging.getLogger(__name__)

X_AUTH_URL = "https://twitter.com/i/oauth2/authorize"
X_TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
X_API_BASE = "https://api.twitter.com"
X_SCOPES = ["tweet.read", "tweet.write", "users.read", "media.write", "offline.access"]

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB (under the 5 MiB cap)


def _client_id() -> str:
    return os.environ.get("X_CLIENT_ID", "")


def _client_secret() -> str:
    return os.environ.get("X_CLIENT_SECRET", "")


def is_configured() -> bool:
    return bool(_client_id())


def _basic_auth() -> tuple[str, str] | None:
    """Confidential clients send Basic auth; public clients (no secret) don't."""
    if _client_id() and _client_secret():
        return (_client_id(), _client_secret())
    return None


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def build_auth_url(redirect_uri: str, state: str) -> tuple[str, str]:
    """Returns (auth_url, code_verifier). Caller must persist verifier with state."""
    verifier, challenge = _pkce_pair()
    params = {
        "response_type": "code",
        "client_id": _client_id(),
        "redirect_uri": redirect_uri,
        "scope": " ".join(X_SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{X_AUTH_URL}?{urlencode(params)}", verifier


def exchange_code(code: str, redirect_uri: str, verifier: str) -> dict:
    data = {
        "code": code,
        "grant_type": "authorization_code",
        "client_id": _client_id(),
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = httpx.post(X_TOKEN_URL, data=data, headers=headers, auth=_basic_auth(), timeout=30)
    r.raise_for_status()
    tok = r.json()
    return _normalize_token(tok)


def refresh_token(token: dict) -> dict:
    if not token.get("refresh_token"):
        return token
    data = {
        "grant_type": "refresh_token",
        "refresh_token": token["refresh_token"],
        "client_id": _client_id(),
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = httpx.post(X_TOKEN_URL, data=data, headers=headers, auth=_basic_auth(), timeout=30)
    r.raise_for_status()
    tok = r.json()
    refreshed = _normalize_token(tok)
    # X may not always rotate the refresh token; keep the old one if missing.
    if not refreshed.get("refresh_token"):
        refreshed["refresh_token"] = token.get("refresh_token")
    return refreshed


def _normalize_token(tok: dict) -> dict:
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "expires_at": time.time() + int(tok.get("expires_in", 7200)),
        "token_type": tok.get("token_type", "bearer"),
        "scope": tok.get("scope", " ".join(X_SCOPES)),
    }


def _ensure_fresh(token: dict) -> dict:
    expires_at = token.get("expires_at") or 0
    if expires_at and expires_at < time.time() + 60:
        log.info("X access token expired/expiring — refreshing")
        return refresh_token(token)
    return token


def _media_id(resp_json: dict) -> str:
    """v2 returns ``{data: {id: "..."}}``; some flows still echo v1.1 fields."""
    data = resp_json.get("data") or resp_json
    mid = data.get("id") or data.get("media_id_string") or data.get("media_id")
    if mid is None:
        raise RuntimeError(f"X media upload: missing id in response: {resp_json}")
    return str(mid)


def _processing_info(resp_json: dict) -> dict | None:
    data = resp_json.get("data") or resp_json
    return data.get("processing_info")


def upload_video(token: dict, video_path: str, text: str) -> dict:
    """Upload + post. Returns ``{status, tweet_id, url, updated_token}``.

    ``updated_token`` is included so the caller can persist a refreshed token.
    """
    token = _ensure_fresh(token)
    headers = {"Authorization": f"Bearer {token['access_token']}"}

    total = os.path.getsize(video_path)
    log.info("X upload: %s (%d bytes)", video_path, total)

    # ── INIT ─────────────────────────────────────────────────────────────
    r = httpx.post(
        f"{X_API_BASE}/2/media/upload",
        headers=headers,
        data={
            "command": "INIT",
            "total_bytes": str(total),
            "media_type": "video/mp4",
            "media_category": "tweet_video",
        },
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"X INIT failed ({r.status_code}): {r.text}")
    media_id = _media_id(r.json())

    # ── APPEND ───────────────────────────────────────────────────────────
    segment = 0
    with open(video_path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            r = httpx.post(
                f"{X_API_BASE}/2/media/upload",
                headers=headers,
                data={
                    "command": "APPEND",
                    "media_id": media_id,
                    "segment_index": str(segment),
                },
                files={"media": ("chunk", chunk, "application/octet-stream")},
                timeout=180,
            )
            if r.status_code >= 400:
                raise RuntimeError(f"X APPEND segment {segment} failed ({r.status_code}): {r.text}")
            segment += 1

    # ── FINALIZE ─────────────────────────────────────────────────────────
    r = httpx.post(
        f"{X_API_BASE}/2/media/upload",
        headers=headers,
        data={"command": "FINALIZE", "media_id": media_id},
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"X FINALIZE failed ({r.status_code}): {r.text}")

    proc = _processing_info(r.json())
    while proc and proc.get("state") in ("pending", "in_progress"):
        wait = int(proc.get("check_after_secs", 5))
        time.sleep(max(1, wait))
        r = httpx.get(
            f"{X_API_BASE}/2/media/upload",
            headers=headers,
            params={"command": "STATUS", "media_id": media_id},
            timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"X STATUS failed ({r.status_code}): {r.text}")
        proc = _processing_info(r.json())

    if proc and proc.get("state") == "failed":
        raise RuntimeError(f"X media processing failed: {proc.get('error', {})}")

    # ── POST TWEET ───────────────────────────────────────────────────────
    body = {"text": (text or "")[:280], "media": {"media_ids": [media_id]}}
    r = httpx.post(
        f"{X_API_BASE}/2/tweets",
        headers={**headers, "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"X tweet create failed ({r.status_code}): {r.text}")
    tweet = r.json().get("data", {})
    tweet_id = tweet.get("id")

    return {
        "status": "posted",
        "tweet_id": tweet_id,
        "url": f"https://x.com/i/status/{tweet_id}" if tweet_id else None,
        "updated_token": token,
    }
