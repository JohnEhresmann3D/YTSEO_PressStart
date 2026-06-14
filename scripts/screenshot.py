"""Capture README screenshots via Playwright. Run: uvx --from playwright[chromium] python scripts/screenshot.py"""

from __future__ import annotations

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8000"

FAKE_JOB = {
    "job_id": "demo123",
    "filename": "skydive-edit-final.mp4",
    "status": "complete",
    "detail": "Complete",
    "pct": 100,
    "platform": "both",
    "tone": "engaging",
    "num_titles": 5,
    "model": "gpt-4o",
    "post_results": {},
    "result": {
        "transcription": {"text": "Today I'm taking you on the wildest skydive of my life — 14,000 feet over the desert..."},
        "seo_analysis": {
            "detected_keywords": [{"word": "skydive"}, {"word": "freefall"}, {"word": "desert"}],
            "platform_rules": [],
        },
        "claude": {
            "claude_generated": True,
            "platforms": [
                {
                    "platform": "youtube",
                    "titles": [
                        "I Jumped Out of a Plane at 14,000 Feet (Raw Footage)",
                        "My First Skydive — 60 Seconds of Pure Freefall",
                        "Skydiving Over the Desert: What It Actually Feels Like",
                        "I Conquered My Fear of Heights — Here's What Happened",
                        "Skydive POV: Strapping a GoPro to My Helmet at 14k ft",
                    ],
                    "description": "Strapped a GoPro to my helmet and jumped out of a plane at 14,000 feet over the Mojave Desert. Raw, uncut footage of the climb, the door opening, freefall, and the canopy ride down. No music, no edits during the jump — just the real thing.\n\nGear: GoPro Hero 12, chest mount + helmet mount\nDrop zone: Skydive Perris\n\n#skydiving #freefall #gopro",
                    "hashtags": ["#skydiving", "#freefall", "#gopro", "#mojave", "#adventure"],
                    "keywords": ["skydive", "freefall", "gopro footage", "desert skydive", "first jump", "tandem skydive", "14000 feet"],
                },
                {
                    "platform": "tiktok",
                    "titles": [
                        "POV: jumping out of a plane at 14,000ft 😵‍💫",
                        "i was NOT ready for this freefall…",
                        "skydiving for the first time — raw reaction",
                        "this is why i'll never do this again 😅",
                        "imagine looking down from 14,000 ft 👀",
                    ],
                    "description": "POV: jumping out of a plane at 14,000ft 😵‍💫 raw reaction, no edits #skydiving #freefall #adventure",
                    "hashtags": ["#skydiving", "#freefall", "#adventure", "#gopro"],
                    "keywords": ["skydive", "freefall", "adventure", "extreme sports"],
                },
            ],
        },
    },
}


def inject_fake_job(page):
    page.evaluate(f"""
        (() => {{
            const j = {json.dumps(FAKE_JOB)};
            createCard(j);
        }})();
    """)
    page.wait_for_timeout(400)


def shot(page, name, clip=None, full_page=False):
    out = OUT / f"{name}.png"
    kwargs = {"path": str(out)}
    if clip: kwargs["clip"] = clip
    if full_page: kwargs["full_page"] = True
    page.screenshot(**kwargs)
    print(f"  -> {out.name}")


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 1700}, device_scale_factor=2)
        page = ctx.new_page()
        page.goto(URL)
        page.wait_for_selector(".dropzone")
        page.wait_for_timeout(400)

        # 1. Hero — empty state, settings + accounts + dropzone visible
        shot(page, "app-overview", clip={"x": 0, "y": 0, "width": 1280, "height": 720})

        # 2. Settings panel close-up
        sp = page.query_selector(".settings-panel")
        box = sp.bounding_box()
        shot(page, "settings-panel", clip={"x": box["x"]-12, "y": box["y"]-12, "width": box["width"]+24, "height": box["height"]+24})

        # 3. Dropzone close-up
        dz = page.query_selector(".dropzone")
        box = dz.bounding_box()
        shot(page, "dropzone", clip={"x": box["x"]-12, "y": box["y"]-12, "width": box["width"]+24, "height": box["height"]+24})

        # Inject fake completed job + render results
        inject_fake_job(page)
        page.wait_for_selector(".platform-block")
        page.wait_for_timeout(400)

        # 4. Results — full job card with platform blocks
        card = page.query_selector(".job-card")
        box = card.bounding_box()
        shot(page, "results-view", clip={"x": box["x"]-12, "y": box["y"]-12, "width": box["width"]+24, "height": min(box["height"]+24, 1600)})

        # 5. Post-to-social panel with schedule picker
        post = page.query_selector(".post-panel")
        if post:
            post.scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            box = post.bounding_box()
            shot(page, "post-panel", clip={"x": box["x"]-12, "y": box["y"]-12, "width": box["width"]+24, "height": box["height"]+24})
        else:
            print("  (no post panel — no accounts connected?)")

        # 6. Regenerate panel close-up (first platform block)
        regen = page.query_selector(".regen-panel")
        if regen:
            regen.scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            box = regen.bounding_box()
            shot(page, "regenerate-panel", clip={"x": box["x"]-12, "y": box["y"]-12, "width": box["width"]+24, "height": box["height"]+24})

        browser.close()


if __name__ == "__main__":
    main()
