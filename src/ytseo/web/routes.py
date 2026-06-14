"""REST + WebSocket endpoints and job queue worker."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, UploadFile, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from ytseo.core.config import UPLOADS_DIR
from ytseo.core.pipeline import run_pipeline
from ytseo.web.claude_cli import generate_with_claude
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
