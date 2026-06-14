"""YouTube Data API v3 — OAuth + resumable video upload."""

from __future__ import annotations

import logging
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

log = logging.getLogger(__name__)

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _client_id() -> str:
    return os.environ.get("YOUTUBE_CLIENT_ID", "")


def _client_secret() -> str:
    return os.environ.get("YOUTUBE_CLIENT_SECRET", "")


def is_configured() -> bool:
    return bool(_client_id() and _client_secret())


def _client_config(redirect_uri: str) -> dict:
    return {
        "web": {
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": [redirect_uri],
        }
    }


def build_auth_url(redirect_uri: str, state: str) -> tuple[str, str]:
    flow = Flow.from_client_config(
        _client_config(redirect_uri),
        scopes=YOUTUBE_SCOPES,
        state=state,
    )
    flow.redirect_uri = redirect_uri
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return url, flow.code_verifier


def exchange_code(redirect_uri: str, code: str, state: str, code_verifier: str | None = None) -> dict:
    flow = Flow.from_client_config(
        _client_config(redirect_uri),
        scopes=YOUTUBE_SCOPES,
        state=state,
    )
    flow.redirect_uri = redirect_uri
    if code_verifier:
        flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    c = flow.credentials
    return {
        "access_token": c.token,
        "refresh_token": c.refresh_token,
        "token_uri": c.token_uri,
        "client_id": c.client_id,
        "client_secret": c.client_secret,
        "scopes": list(c.scopes or YOUTUBE_SCOPES),
        "expires_at": c.expiry.timestamp() if c.expiry else None,
    }


def _credentials(token: dict) -> Credentials:
    creds = Credentials(
        token=token.get("access_token"),
        refresh_token=token.get("refresh_token"),
        token_uri=token.get("token_uri", TOKEN_URI),
        client_id=token.get("client_id") or _client_id(),
        client_secret=token.get("client_secret") or _client_secret(),
        scopes=token.get("scopes", YOUTUBE_SCOPES),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def upload_video(
    token: dict,
    video_path: str,
    title: str,
    description: str,
    tags: list[str] | None = None,
    privacy: str = "private",
    category_id: str = "22",
    made_for_kids: bool = False,
    publish_at: str | None = None,
) -> dict:
    """Upload ``video_path`` to YouTube. Returns ``{video_id, url, status}``.

    privacy: "private" | "unlisted" | "public"
    category_id: "22" = People & Blogs (default). See YouTube videoCategories.list.
    """
    creds = _credentials(token)
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    body = {
        "snippet": {
            "title": (title or "Untitled")[:100],
            "description": (description or "")[:5000],
            "tags": [t for t in (tags or []) if t][:50],
            "categoryId": str(category_id),
        },
        "status": {
            "privacyStatus": "private" if publish_at else (privacy if privacy in ("private", "unlisted", "public") else "private"),
            "selfDeclaredMadeForKids": bool(made_for_kids),
        },
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/*")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _, response = request.next_chunk()

    video_id = response["id"]
    return {
        "status": "posted",
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "privacy": body["status"]["privacyStatus"],
        "publish_at": publish_at,
    }
