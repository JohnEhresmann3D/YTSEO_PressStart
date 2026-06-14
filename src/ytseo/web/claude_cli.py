"""SEO content generation — GitHub Models API (preferred) or Claude CLI fallback."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a specialized SEO content generator for short-form and long-form video platforms.

Rules:
1. Accuracy over virality — every title/description/hashtag must be grounded in the actual transcription.
2. No misleading clickbait — compelling but honest.
3. Respect all platform character limits strictly.
4. Prefer niche-specific hashtags. Never use #fyp, #viral, #foryou, #trending.
5. Match the requested tone to the natural tone of the video content.
6. Keywords must actually appear in or be implied by the transcription.
7. No harmful content.
8. Flag poor transcription quality rather than guessing.

Return your response as a JSON array of objects matching this schema exactly:
[
  {
    "platform": "tiktok" or "youtube",
    "titles": ["..."],
    "description": "...",
    "hashtags": ["#...", ...],
    "keywords": ["...", ...]
  }
]

Return ONLY the JSON array — no markdown fences, no commentary.\
"""


def _github_token() -> str | None:
    return os.environ.get("GITHUB_TOKEN")


def _default_github_model() -> str:
    return os.environ.get("GITHUB_MODEL", "gpt-4o")


def _build_user_prompt(seo_analysis: dict, platform: str, tone: str, num_titles: int) -> str:
    transcription = seo_analysis.get("transcription_text", "")
    keywords = seo_analysis.get("detected_keywords", [])
    rules = seo_analysis.get("platform_rules", [])
    keyword_str = ", ".join(k["word"] for k in keywords[:10])
    return (
        f"--- VIDEO TRANSCRIPTION ---\n{transcription}\n\n"
        f"--- DETECTED KEYWORDS ---\n{keyword_str}\n\n"
        f"--- PLATFORM RULES ---\n{json.dumps(rules, indent=2)}\n\n"
        f"--- TASK ---\n"
        f"Generate {num_titles} title suggestions with a '{tone}' tone for platform: {platform}.\n"
        f"Also generate a description, hashtags, and keywords for each platform.\n"
        f"If platform is \"both\", produce one object for \"tiktok\" and one for \"youtube\"."
    )


# ---------------------------------------------------------------------------
# GitHub Models (primary path when GITHUB_TOKEN is set)
# ---------------------------------------------------------------------------

def _generate_with_github_models(
    seo_analysis: dict,
    platform: str,
    tone: str,
    num_titles: int,
    timeout: int,
    model: str | None = None,
) -> dict:
    token = _github_token()
    model = model or _default_github_model()

    try:
        from openai import OpenAI
    except ImportError:
        return _fallback(seo_analysis, "openai package not installed — run: uv sync")

    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=token,
        timeout=timeout,
    )

    user_prompt = _build_user_prompt(seo_analysis, platform, tone, num_titles)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content or ""
        log.info("GitHub Models (%s) responded with %d chars", model, len(content))
        return _parse_response(content, seo_analysis)
    except Exception as e:
        log.error("GitHub Models API error: %s", e)
        return _fallback(seo_analysis, f"GitHub Models error: {e}")


# ---------------------------------------------------------------------------
# Claude CLI (fallback)
# ---------------------------------------------------------------------------

def _claude_available() -> bool:
    return shutil.which("claude") is not None


def _generate_with_claude_cli(
    seo_analysis: dict,
    platform: str,
    tone: str,
    num_titles: int,
    timeout: int,
) -> dict:
    if not _claude_available():
        return _fallback(seo_analysis, "claude CLI not found on PATH")

    user_prompt = _build_user_prompt(seo_analysis, platform, tone, num_titles)
    full_prompt = f"{_SYSTEM_PROMPT}\n\n{user_prompt}"

    try:
        result = subprocess.run(
            ["claude", "--print", "-p", full_prompt],
            capture_output=True,
            timeout=timeout,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")

        if result.returncode != 0:
            log.error("claude CLI failed (rc=%d): %s", result.returncode, stderr)
            return _fallback(seo_analysis, f"claude CLI error: {stderr[:200]}")

        return _parse_response(stdout, seo_analysis)
    except subprocess.TimeoutExpired:
        return _fallback(seo_analysis, f"claude CLI timed out after {timeout}s")
    except Exception as e:
        return _fallback(seo_analysis, str(e))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_with_claude(
    seo_analysis: dict,
    platform: str = "both",
    tone: str = "engaging",
    num_titles: int = 5,
    timeout: int = 120,
    model: str | None = None,
) -> dict:
    """Generate polished SEO content.

    Priority:
      1. GitHub Models API (if GITHUB_TOKEN is set)
      2. Claude CLI (if on PATH)
      3. Raw analysis fallback
    """
    if _github_token():
        resolved = model or _default_github_model()
        log.info("Using GitHub Models API (model: %s)", resolved)
        return _generate_with_github_models(seo_analysis, platform, tone, num_titles, timeout, model=resolved)

    log.info("Using claude CLI")
    return _generate_with_claude_cli(seo_analysis, platform, tone, num_titles, timeout)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _parse_response(text: str, seo_analysis: dict) -> dict:
    if not text:
        return _fallback(seo_analysis, "empty response from LLM")
    text = text.strip()

    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        platforms = json.loads(text)
        if isinstance(platforms, dict):
            platforms = [platforms]
        return {"platforms": platforms, "claude_generated": True}
    except json.JSONDecodeError:
        log.warning("LLM response was not valid JSON — returning raw text")
        return {
            "platforms": [],
            "claude_generated": True,
            "raw_response": text,
            "warning": "LLM response was not valid JSON — raw text included",
        }


def _fallback(seo_analysis: dict, reason: str) -> dict:
    return {
        "platforms": [],
        "claude_generated": False,
        "warning": reason,
        "raw_analysis": {
            "detected_keywords": seo_analysis.get("detected_keywords", []),
            "platform_rules": seo_analysis.get("platform_rules", []),
            "instructions": seo_analysis.get("instructions", ""),
        },
    }
