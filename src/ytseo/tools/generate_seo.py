"""Generate SEO analysis and structured constraints for title/hashtag generation."""

from ytseo.tools.platform_rules import get_rules


def generate_seo(
    transcription: str,
    platform: str = "both",
    num_title_suggestions: int = 5,
    tone: str = "engaging",
) -> dict:
    """Generate SEO analysis with platform rules and transcription context.

    This returns structured data that Claude uses to craft optimized
    titles, descriptions, and hashtags. The tool provides constraints
    and context; Claude provides the creativity.

    Args:
        transcription: The transcribed text from the video.
        platform: 'tiktok', 'youtube', or 'both'.
        num_title_suggestions: How many title options to generate.
        tone: Desired tone (e.g. 'engaging', 'educational', 'humorous').

    Returns:
        Structured dict with transcription, rules, and generation instructions.
    """
    rules = get_rules(platform)

    # Extract key topics from transcription for keyword hints
    words = transcription.lower().split()
    # Simple word frequency for keyword candidates (2+ occurrences, 4+ chars)
    freq = {}
    for w in words:
        cleaned = "".join(c for c in w if c.isalnum())
        if len(cleaned) >= 4:
            freq[cleaned] = freq.get(cleaned, 0) + 1
    top_keywords = sorted(
        [(w, c) for w, c in freq.items() if c >= 2],
        key=lambda x: x[1],
        reverse=True,
    )[:15]

    return {
        "transcription_text": transcription,
        "transcription_length": len(transcription),
        "detected_keywords": [{"word": w, "count": c} for w, c in top_keywords],
        "platform_rules": rules["platforms"],
        "generation_params": {
            "num_title_suggestions": num_title_suggestions,
            "tone": tone,
        },
        "instructions": (
            f"Using the transcription and platform rules above, generate {num_title_suggestions} "
            f"title suggestions with a '{tone}' tone for each platform. "
            "Also generate a description and relevant hashtags per platform, "
            "respecting all character limits and best practices in the rules. "
            "Return results as structured JSON matching the PlatformResult schema: "
            "{platform, titles[], description, hashtags[], keywords[]}."
        ),
    }
