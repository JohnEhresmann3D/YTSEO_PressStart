"""REST + WebSocket endpoints and job queue worker."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Request, UploadFile, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.websockets import WebSocketState

from ytseo.core.config import UPLOADS_DIR
from ytseo.core.pipeline import run_pipeline
from ytseo.web import oauth
from ytseo.web.claude_cli import generate_with_claude, regenerate_sections
from ytseo.web.models import JobState, JobStatus, STAGE_PCT

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
jobs: dict[str, JobState] = {}
job_queue: asyncio.Queue[str] = asyncio.Queue()
ws_clients: set[WebSocket] = set()
_worker_task: asyncio.Task | None = None


def get_or_start_worker() -> None:
    """Ensure the background worker is running."""
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker())


# ---------------------------------------------------------------------------
# WebSocket broadcast
# ---------------------------------------------------------------------------
async def _broadcast(msg: dict) -> None:
    dead: list[WebSocket] = []
    for ws in ws_clients:
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)


async def _send_progress(job: JobState) -> None:
    await _broadcast({
        "job_id": job.job_id,
        "event": "progress",
        "stage": job.status.value,
        "detail": job.detail,
        "pct": job.pct,
    })


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
async def _worker() -> None:
    """Single worker that processes jobs sequentially."""
    log.info("Job worker started")
    while True:
        job_id = await job_queue.get()
        job = jobs.get(job_id)
        if job is None or job.status == JobStatus.cancelled:
            job_queue.task_done()
            continue

        try:
            await _process_job(job)
        except Exception as e:
            log.exception("Job %s failed", job_id)
            job.status = JobStatus.error
            job.error = str(e)
            job.detail = f"Error: {e}"
            await _broadcast({
                "job_id": job.job_id,
                "event": "error",
                "detail": str(e),
            })
        finally:
            job_queue.task_done()


async def _process_job(job: JobState) -> None:
    """Run the full pipeline + Claude CLI for a single job."""
    loop = asyncio.get_event_loop()

    def on_progress(stage: str, detail: str) -> None:
        job.status = JobStatus(stage) if stage in JobStatus.__members__ else job.status
        job.detail = detail
        job.pct = STAGE_PCT.get(stage, job.pct)
        # Schedule broadcast from sync callback
        asyncio.run_coroutine_threadsafe(_send_progress(job), loop)

    # Run the blocking pipeline in a thread
    raw_result = await asyncio.to_thread(
        run_pipeline,
        video_path=job.video_path,
        platform=job.platform,
        language=None,
        num_title_suggestions=job.num_titles,
        tone=job.tone,
        on_progress=on_progress,
    )

    # Claude CLI stage
    job.status = JobStatus.generating
    job.detail = "Generating polished SEO content with Claude..."
    job.pct = STAGE_PCT["generating"]
    await _send_progress(job)

    claude_result = await asyncio.to_thread(
        generate_with_claude,
        seo_analysis=raw_result["seo_analysis"],
        platform=job.platform,
        tone=job.tone,
        num_titles=job.num_titles,
        model=job.model,
    )

    # Combine results
    job.result = {
        "transcription": raw_result["transcription"],
        "seo_analysis": raw_result["seo_analysis"],
        "claude": claude_result,
    }
    job.status = JobStatus.complete
    job.detail = "Complete"
    job.pct = 100

    await _broadcast({
        "job_id": job.job_id,
        "event": "complete",
        "result": job.result,
    })


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------
@router.post("/upload")
async def upload_videos(
    files: list[UploadFile],
    platform: str = Query("both"),
    tone: str = Query("engaging"),
    num_titles: int = Query(5),
    model: str = Query("gpt-4o"),
) -> dict:
    """Accept video file(s), save to UPLOADS_DIR, queue for processing."""
    get_or_start_worker()
    created = []

    for file in files:
        job_id = uuid.uuid4().hex[:12]
        # Save with unique prefix to avoid collisions
        safe_name = f"{job_id}_{file.filename}"
        dest = UPLOADS_DIR / safe_name
        content = await file.read()
        dest.write_bytes(content)

        job = JobState(
            job_id=job_id,
            filename=file.filename,
            video_path=str(dest),
            platform=platform,
            tone=tone,
            num_titles=num_titles,
            model=model,
        )
        jobs[job_id] = job
        await job_queue.put(job_id)
        created.append(job.to_dict())

    return {"jobs": created}


@router.get("/jobs")
async def list_jobs() -> dict:
    """List all jobs with their current status."""
    return {"jobs": [j.to_dict() for j in jobs.values()]}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        return {"error": "Job not found"}
    return job.to_dict()


@router.post("/jobs/{job_id}/regenerate")
async def regenerate_job_sections(job_id: str, payload: dict = Body(...)) -> dict:
    """Regenerate selected sections (description/hashtags/keywords) for one platform."""
    job = jobs.get(job_id)
    if job is None or not job.result:
        return JSONResponse({"error": "Job not found or not complete"}, status_code=404)

    platform = payload.get("platform")
    sections = payload.get("sections") or []
    feedback = payload.get("feedback") or ""
    if not platform or not sections:
        return JSONResponse({"error": "platform and sections are required"}, status_code=400)

    claude = job.result.get("claude") or {}
    blocks = claude.get("platforms") or []
    block = next((b for b in blocks if b.get("platform") == platform), None)
    if block is None:
        return JSONResponse({"error": f"No content for platform: {platform}"}, status_code=404)

    seo_analysis = job.result.get("seo_analysis") or {}
    try:
        updated = await asyncio.to_thread(
            regenerate_sections,
            seo_analysis=seo_analysis,
            platform_block=block,
            sections=sections,
            feedback=feedback,
            model=job.model,
        )
    except Exception as e:
        log.exception("Regenerate failed for job %s", job_id)
        return JSONResponse({"error": str(e)}, status_code=500)

    block.update(updated)
    return {"platform": platform, "updated": updated}


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        return {"error": "Job not found"}
    if job.status in (JobStatus.queued, JobStatus.extracting, JobStatus.transcribing,
                      JobStatus.analyzing, JobStatus.generating):
        job.status = JobStatus.cancelled
        job.detail = "Cancelled by user"
    del jobs[job_id]
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# OAuth — connect / disconnect / status
# ---------------------------------------------------------------------------
_SUPPORTED_PLATFORMS = ("youtube", "x")


def _redirect_uri(request: Request, platform: str) -> str:
    return f"{request.url.scheme}://{request.url.netloc}/api/auth/{platform}/callback"


@router.get("/auth/status")
async def auth_status() -> dict:
    """Return connection + configuration status for each posting platform."""
    tokens = oauth.load_tokens()
    return {
        "connected": {p: (p in tokens) for p in _SUPPORTED_PLATFORMS},
        "configured": {
            "youtube": bool(os.environ.get("YOUTUBE_CLIENT_ID") and os.environ.get("YOUTUBE_CLIENT_SECRET")),
            "x": bool(os.environ.get("X_CLIENT_ID")),
        },
    }


@router.get("/auth/{platform}")
async def auth_start(platform: str, request: Request):
    """Start an OAuth flow — redirects the browser to the platform's consent screen."""
    if platform not in _SUPPORTED_PLATFORMS:
        return JSONResponse({"error": f"unsupported platform: {platform}"}, status_code=404)

    redirect_uri = _redirect_uri(request, platform)
    state = uuid.uuid4().hex

    if platform == "youtube":
        from ytseo.platforms import youtube as yt
        if not yt.is_configured():
            return JSONResponse(
                {"error": "YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET not configured in .env"},
                status_code=400,
            )
        url, verifier = yt.build_auth_url(redirect_uri, state)
        oauth.store_pending(state, {"platform": "youtube", "redirect_uri": redirect_uri, "verifier": verifier})

    elif platform == "x":
        from ytseo.platforms import twitter as tw
        if not tw.is_configured():
            return JSONResponse(
                {"error": "X_CLIENT_ID not configured in .env"},
                status_code=400,
            )
        url, verifier = tw.build_auth_url(redirect_uri, state)
        oauth.store_pending(state, {"platform": "x", "redirect_uri": redirect_uri, "verifier": verifier})

    else:  # pragma: no cover — guarded above
        return JSONResponse({"error": "unsupported"}, status_code=404)

    return RedirectResponse(url, status_code=302)


_CALLBACK_HTML = """<!DOCTYPE html>
<html><head><title>YTSEO — {title}</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#090D18;color:#E4EAF8;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.box{{background:#111827;border:1px solid #2A3654;padding:2rem 2.5rem;border-radius:14px;text-align:center;max-width:420px}}
h1{{font-size:1.3rem;margin:0 0 .5rem;color:{color}}}
p{{color:#7A8DB5;font-size:.9rem;margin:0}}
</style></head>
<body><div class="box"><h1>{title}</h1><p>{msg}</p></div>
<script>
try {{
  if (window.opener) {{
    window.opener.postMessage({{type:'ytseo-auth',platform:'{platform}',ok:{ok_js}}}, '*');
    setTimeout(()=>window.close(), 900);
  }}
}} catch(e) {{}}
</script></body></html>"""


def _callback_page(platform: str, ok: bool, msg: str) -> HTMLResponse:
    return HTMLResponse(_CALLBACK_HTML.format(
        title="✓ Connected" if ok else "✗ Connection failed",
        color="#7AAE2A" if ok else "#C4422E",
        msg=msg,
        platform=platform,
        ok_js="true" if ok else "false",
    ))


@router.get("/auth/{platform}/callback")
async def auth_callback(platform: str, code: str = "", state: str = "", error: str = ""):
    if error:
        return _callback_page(platform, False, f"Provider returned error: {error}")
    if not code or not state:
        return _callback_page(platform, False, "Missing code or state in callback URL.")

    pending = oauth.pop_pending(state)
    if not pending or pending.get("platform") != platform:
        return _callback_page(platform, False, "State mismatch — the OAuth flow expired or was tampered with.")

    redirect_uri = pending["redirect_uri"]
    try:
        if platform == "youtube":
            from ytseo.platforms import youtube as yt
            token = yt.exchange_code(redirect_uri, code, state, pending.get("verifier"))
        elif platform == "x":
            from ytseo.platforms import twitter as tw
            token = tw.exchange_code(code, redirect_uri, pending["verifier"])
        else:
            return _callback_page(platform, False, "Unsupported platform.")
        oauth.set_token(platform, token)
    except Exception as e:
        log.exception("OAuth callback failed for %s", platform)
        return _callback_page(platform, False, f"Token exchange failed: {e}")

    return _callback_page(platform, True, f"Your {platform} account is connected. You can close this tab.")


@router.delete("/auth/{platform}")
async def auth_disconnect(platform: str) -> dict:
    if platform not in _SUPPORTED_PLATFORMS:
        return {"error": "unsupported platform"}
    oauth.remove_token(platform)
    return {"status": "disconnected", "platform": platform}


# ---------------------------------------------------------------------------
# Post job to social platforms
# ---------------------------------------------------------------------------
def _seo_for(job: JobState, key: str) -> dict:
    """Pick the SEO output that best matches a target platform.

    YouTube uses the youtube block. X has no dedicated block — fall back to
    tiktok (short captions, hashtag-friendly), then youtube, then empty.
    """
    cl = (job.result or {}).get("claude") or {}
    blocks = cl.get("platforms") or []
    if key == "youtube":
        match = next((b for b in blocks if b.get("platform") == "youtube"), None)
        return match or (blocks[0] if blocks else {})
    # X / tiktok-like
    match = next((b for b in blocks if b.get("platform") == "tiktok"), None)
    if match:
        return match
    return next((b for b in blocks if b.get("platform") == "youtube"), {}) or (blocks[0] if blocks else {})


def _post_youtube(job: JobState, override: dict) -> dict:
    from ytseo.platforms import youtube as yt
    token = oauth.get_token("youtube")
    if not token:
        raise RuntimeError("YouTube account not connected")
    src = _seo_for(job, "youtube")
    titles = src.get("titles") or []
    title = override.get("title") or (titles[0] if titles else job.filename)
    description = override.get("description") or src.get("description") or ""
    hashtags = override.get("hashtags") or src.get("hashtags") or []
    if hashtags and "#" not in description:
        description = (description.rstrip() + "\n\n" + " ".join(hashtags)).strip()
    keywords = src.get("keywords") or []
    tags = override.get("tags") or list({*(k.lower() for k in keywords), *(h.lstrip("#").lower() for h in hashtags)})
    privacy = override.get("privacy") or "private"
    publish_at = (override.get("publish_at") or "").strip() or None
    return yt.upload_video(
        token,
        video_path=job.video_path,
        title=title,
        description=description,
        tags=tags,
        privacy=privacy,
        publish_at=publish_at,
    )


def _post_x(job: JobState, override: dict) -> dict:
    from ytseo.platforms import twitter as tw
    token = oauth.get_token("x")
    if not token:
        raise RuntimeError("X account not connected")
    src = _seo_for(job, "x")
    titles = src.get("titles") or []
    hashtags = src.get("hashtags") or []
    base = override.get("text")
    if not base:
        title = titles[0] if titles else job.filename
        # Fit within 280 chars when adding hashtags
        budget = 280
        tag_str = " ".join(hashtags)
        if tag_str:
            budget -= len(tag_str) + 1
        if budget < 20:
            base = title[:280]
        else:
            base = (title[:budget].rstrip() + " " + tag_str).strip()
    result = tw.upload_video(token, job.video_path, base)
    updated = result.pop("updated_token", None)
    if updated:
        oauth.set_token("x", updated)
    return result


async def _run_post(job: JobState, platform: str, override: dict) -> dict:
    fn = {"youtube": _post_youtube, "x": _post_x}.get(platform)
    if fn is None:
        return {"status": "error", "error": f"unsupported platform: {platform}"}
    try:
        out = await asyncio.to_thread(fn, job, override)
        return out
    except Exception as e:
        log.exception("Posting to %s failed", platform)
        return {"status": "error", "error": str(e)}


@router.post("/jobs/{job_id}/post")
async def post_job(job_id: str, payload: dict = Body(...)):
    """Post a completed job's video to one or more connected platforms.

    Body shape::

        {
          "platforms": ["youtube", "x"],
          "overrides": {
            "youtube": {"title": "...", "description": "...", "hashtags": ["#..."], "privacy": "private"},
            "x": {"text": "..."}
          }
        }
    """
    job = jobs.get(job_id)
    if job is None:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    if job.status != JobStatus.complete and job.status != JobStatus.posting:
        return JSONResponse(
            {"error": f"Job not complete (status: {job.status.value})"},
            status_code=400,
        )

    platforms = [p for p in (payload.get("platforms") or []) if p in _SUPPORTED_PLATFORMS]
    if not platforms:
        return JSONResponse({"error": "no valid platforms requested"}, status_code=400)

    overrides = payload.get("overrides") or {}

    prev_status = job.status
    job.status = JobStatus.posting
    job.detail = f"Posting to {', '.join(platforms)}…"
    await _send_progress(job)

    results: dict[str, dict] = {}
    for p in platforms:
        job.detail = f"Posting to {p}…"
        await _send_progress(job)
        results[p] = await _run_post(job, p, overrides.get(p, {}))
        job.post_results[p] = results[p]
        await _broadcast({
            "job_id": job.job_id,
            "event": "post_result",
            "platform": p,
            "result": results[p],
        })

    job.status = JobStatus.complete if prev_status != JobStatus.posting else prev_status
    failed = [p for p, r in results.items() if r.get("status") != "posted"]
    job.detail = "Posted" if not failed else f"Posted with errors: {', '.join(failed)}"
    job.pct = 100
    await _send_progress(job)

    return {"results": results, "post_results": job.post_results}
