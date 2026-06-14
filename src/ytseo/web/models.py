"""Request/response models and job state for the web API."""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    queued = "queued"
    extracting = "extracting"
    transcribing = "transcribing"
    analyzing = "analyzing"
    generating = "generating"
    complete = "complete"
    error = "error"
    cancelled = "cancelled"


STAGE_PCT = {
    "queued": 0,
    "extracting": 10,
    "transcribing": 40,
    "analyzing": 70,
    "generating": 90,
    "complete": 100,
}


class JobState:
    """Mutable in-memory state for a single processing job."""

    def __init__(self, job_id: str, filename: str, video_path: str,
                 platform: str = "both", tone: str = "engaging",
                 num_titles: int = 5, model: str = "gpt-4o"):
        self.job_id = job_id
        self.filename = filename
        self.video_path = video_path
        self.platform = platform
        self.tone = tone
        self.num_titles = num_titles
        self.model = model
        self.status: JobStatus = JobStatus.queued
        self.detail: str = "Waiting in queue..."
        self.pct: int = 0
        self.result: dict | None = None
        self.error: str | None = None
        self.created_at: float = time.time()

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "filename": self.filename,
            "status": self.status.value,
            "detail": self.detail,
            "pct": self.pct,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "platform": self.platform,
            "tone": self.tone,
            "num_titles": self.num_titles,
            "model": self.model,
        }


class UploadResponse(BaseModel):
    jobs: list[dict] = Field(description="List of created job summaries")


class WSMessage(BaseModel):
    job_id: str
    event: str
    stage: str | None = None
    detail: str | None = None
    pct: int | None = None
    result: dict | None = None
