"""MCP server exposing video SEO analysis tools to Claude Code."""

from mcp.server.fastmcp import FastMCP

from ytseo.tools.extract_audio import extract_audio as _extract_audio
from ytseo.tools.transcribe import transcribe_audio as _transcribe_audio
from ytseo.tools.generate_seo import generate_seo as _generate_seo
from ytseo.core.pipeline import run_pipeline

mcp = FastMCP(
    "ytseo",
    instructions="Analyze video audio to generate SEO-friendly titles and hashtags for TikTok and YouTube",
)


@mcp.tool()
def extract_audio(video_path: str) -> str:
    """Extract audio from a video file using ffmpeg.

    Returns the path to the extracted WAV audio file (16kHz mono).
    Use this before transcribe_audio, or use analyze_video for the full pipeline.

    Args:
        video_path: Absolute path to a video file (mp4, mov, avi, mkv, webm, etc.)
    """
    path = _extract_audio(video_path)
    return f"Audio extracted to: {path}"


@mcp.tool()
def transcribe_audio(audio_path: str, language: str = "") -> dict:
    """Transcribe an audio file to text using Whisper.

    Returns the full transcription text, detected language, and timestamped segments.
    The first call may take a minute to download the Whisper model (~150MB).

    Args:
        audio_path: Path to an audio file (WAV, MP3, etc.)
        language: Language code like 'en', 'es', 'fr'. Leave empty for auto-detection.
    """
    lang = language if language else None
    result = _transcribe_audio(audio_path, language=lang)
    return result.model_dump()


@mcp.tool()
def generate_seo(
    transcription: str,
    platform: str = "both",
    num_title_suggestions: int = 5,
    tone: str = "engaging",
) -> dict:
    """Generate SEO-optimized titles, descriptions, and hashtags from a transcription.

    Analyzes the transcription text and returns platform-specific SEO rules,
    keyword analysis, and generation instructions. Use the returned data to
    craft optimized content for each platform.

    Args:
        transcription: The transcribed text from the video.
        platform: Target platform - 'tiktok', 'youtube', or 'both'.
        num_title_suggestions: Number of title suggestions to generate (default 5).
        tone: Desired tone - 'engaging', 'educational', 'humorous', 'professional', etc.
    """
    return _generate_seo(
        transcription=transcription,
        platform=platform,
        num_title_suggestions=num_title_suggestions,
        tone=tone,
    )


@mcp.tool()
def analyze_video(
    video_path: str,
    platform: str = "both",
    language: str = "",
    num_title_suggestions: int = 5,
    tone: str = "engaging",
) -> dict:
    """Full pipeline: extract audio, transcribe, and generate SEO analysis.

    This is the all-in-one tool. Give it a video file and it returns the
    transcription plus platform-specific SEO rules and keyword analysis
    for generating titles, descriptions, and hashtags.

    The first call may take longer as it downloads the Whisper model (~150MB).

    Args:
        video_path: Absolute path to a video file.
        platform: Target platform - 'tiktok', 'youtube', or 'both'.
        language: Language code like 'en'. Leave empty for auto-detection.
        num_title_suggestions: Number of title suggestions (default 5).
        tone: Desired tone - 'engaging', 'educational', 'humorous', etc.
    """
    lang = language if language else None
    return run_pipeline(
        video_path=video_path,
        platform=platform,
        language=lang,
        num_title_suggestions=num_title_suggestions,
        tone=tone,
    )


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
