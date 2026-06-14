from __future__ import annotations
from pydantic import BaseModel


class TranscriptionSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscriptionResult(BaseModel):
    text: str
    language: str
    segments: list[TranscriptionSegment]


class PlatformResult(BaseModel):
    platform: str
    titles: list[str]
    description: str
    hashtags: list[str]
    keywords: list[str]


class SEOResult(BaseModel):
    transcription: TranscriptionResult
    platforms: list[PlatformResult]
