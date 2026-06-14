"""Platform-specific SEO rules and constraints for TikTok and YouTube."""

TIKTOK_RULES = {
    "platform": "tiktok",
    "caption_max_chars": 4000,
    "caption_visible_chars": 150,  # visible on FYP before "more"
    "hashtag_count": {"min": 3, "max": 5},
    "hashtag_notes": (
        "Use niche-specific hashtags only. "
        "Avoid generic tags like #fyp, #viral, #foryou — they dilute reach. "
        "Keywords in caption text matter more than hashtags for TikTok search."
    ),
    "title_notes": (
        "TikTok has no separate title field — the caption IS the title. "
        "Front-load the hook in the first 150 characters. "
        "Use a conversational, attention-grabbing tone."
    ),
}

YOUTUBE_RULES = {
    "platform": "youtube",
    "title_max_chars": 100,
    "title_optimal_chars": 60,  # truncation on mobile
    "description_max_chars": 5000,
    "description_visible_chars": 157,  # before "Show more"
    "tags_max_total_chars": 500,
    "tags_count": {"min": 5, "max": 8},
    "tag_max_chars": 30,
    "title_notes": (
        "Place the primary keyword in the first 60 characters. "
        "Use power words and numbers when relevant. "
        "Avoid clickbait that doesn't deliver."
    ),
    "description_notes": (
        "First 157 characters are critical — include the main keyword and a compelling summary. "
        "Add timestamps, links, and secondary keywords below the fold. "
        "Description keywords matter more than tags for YouTube SEO."
    ),
    "hashtag_notes": (
        "YouTube allows up to 3 hashtags above the title (placed at end of description). "
        "Additional hashtags in description help discovery. "
        "Keep each hashtag under 30 characters."
    ),
}

PLATFORM_MAP = {
    "tiktok": TIKTOK_RULES,
    "youtube": YOUTUBE_RULES,
}


def get_rules(platform: str) -> dict:
    """Get rules for a platform. Use 'both' to get all platforms."""
    if platform == "both":
        return {"platforms": [TIKTOK_RULES, YOUTUBE_RULES]}
    if platform not in PLATFORM_MAP:
        raise ValueError(f"Unknown platform: {platform}. Use 'tiktok', 'youtube', or 'both'.")
    return {"platforms": [PLATFORM_MAP[platform]]}
