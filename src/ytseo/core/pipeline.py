"""Shared processing pipeline used by both MCP server and web API."""

from ytseo.tools.extract_audio import extract_audio
from ytseo.tools.transcribe import transcribe_audio
from ytseo.tools.generate_seo import generate_seo


def run_pipeline(
    video_path: str,
    platform: str = "both",
    language: str | None = None,
    num_title_suggestions: int = 5,
    tone: str = "engaging",
    on_progress: callable = None,
) -> dict:
    """Run the full analysis pipeline: extract → transcribe → generate SEO.

    Args:
        video_path: Path to the video file.
        platform: 'tiktok', 'youtube', or 'both'.
        language: Language code or None for auto-detect.
        num_title_suggestions: Number of title options per platform.
        tone: Desired tone for generated content.
        on_progress: Optional callback(stage: str, detail: str).

    Returns:
        Dict with audio_path, transcription, and seo_analysis.
    """
    if on_progress:
        on_progress("extracting", "Extracting audio from video...")

    audio_path = extract_audio(video_path)

    if on_progress:
        on_progress("transcribing", "Transcribing audio with Whisper...")

    transcription = transcribe_audio(audio_path, language=language)

    if on_progress:
        on_progress("analyzing", "Generating SEO analysis...")

    seo = generate_seo(
        transcription=transcription.text,
        platform=platform,
        num_title_suggestions=num_title_suggestions,
        tone=tone,
    )

    if on_progress:
        on_progress("complete", "Analysis complete.")

    return {
        "audio_path": audio_path,
        "transcription": transcription.model_dump(),
        "seo_analysis": seo,
    }
