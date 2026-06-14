# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run web server (http://localhost:8000)
uv run ytseo-web

# Pass GitHub token at startup (overrides .env)
uv run ytseo-web --github-token ghp_xxx

# Custom host/port
uv run ytseo-web --host 0.0.0.0 --port 9000

# Run MCP server (stdio, for Claude Code integration)
uv run ytseo-mcp
```

Copy `.env.example` → `.env` and set `GITHUB_TOKEN` to use GitHub Models API. No test suite exists yet. Python 3.11 is required (enforced via `.python-version`).

## Architecture

**Dual-interface SEO tool**: processes video files through a pipeline (ffmpeg → Whisper → SEO generation) and exposes that pipeline two ways:

1. **MCP Server** (`src/ytseo/mcp_server.py`): stdio-based server registered in `.mcp.json`. Exposes 4 tools to Claude Code: `extract_audio`, `transcribe_audio`, `generate_seo`, `analyze_video`.

2. **Web Server** (`src/ytseo/web/`): FastAPI app with drag-and-drop UI at `localhost:8000`. Real-time progress via WebSocket. Jobs are queued sequentially — one video processes at a time.

### Processing Pipeline

```
Video → ffmpeg (16kHz mono WAV) → faster-whisper → keyword extraction + platform rules → Claude CLI (optional polish)
```

- `core/pipeline.py` — orchestrates the full flow
- `tools/extract_audio.py` — ffmpeg subprocess, 300s timeout, UUID suffix to prevent collision
- `tools/transcribe.py` — faster-whisper CPU int8, globally cached model, lazy-loaded on first use (~150MB download)
- `tools/generate_seo.py` — keyword frequency extraction + platform constraints; outputs structured instructions for Claude to use creatively
- `web/claude_cli.py` — optional: shells out to `claude` CLI to produce final JSON; gracefully falls back to raw analysis if unavailable

### Key Design Decisions

- **LLM priority in `web/claude_cli.py`**: GitHub Models API (if `GITHUB_TOKEN` set) → claude CLI (if on PATH) → raw analysis fallback. Token is read from `os.environ` at call time so `--github-token` CLI arg takes effect without restart.
- **Claude does creativity, tools do constraints**: `generate_seo` returns keyword lists and platform rules; it does not generate copy — that's the LLM's job.
- **Platform rules in `tools/platform_rules.py`**: TikTok captions max 4000 chars (150 visible on FYP, caption IS the title); YouTube titles max 100 chars (60 optimal), 5–8 tags, 3 hashtags at end of description.
- **Tone options**: engaging, humorous, educational, controversial, storytelling.
- **Job state is in-memory**: restarting the web server clears job history. The frontend recovers in-progress jobs on reload via `GET /api/jobs`.
- **Data dirs auto-created** by `core/config.py` at startup: `data/uploads/`, `data/audio/`, `data/models/`. All excluded from git.

### Web API Surface

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/upload` | Upload videos, enqueue jobs |
| GET | `/api/jobs` | List all jobs |
| GET | `/api/jobs/{job_id}` | Single job detail |
| DELETE | `/api/jobs/{job_id}` | Cancel or delete job |
| WebSocket | `/ws` | Broadcast progress to all clients |

### SEO Agent

`.claude/agents/seo-generator.md` defines a Claude sub-agent with rules for using the MCP tools. Core principle: **accuracy over virality** — no fabricated claims, no misleading clickbait, hashtags must be niche (never `#fyp`, `#viral`), only detected keywords allowed.

### Environment Variables

Loaded from `.env` (via python-dotenv) at startup. CLI flag `--github-token` takes precedence over `.env`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `GITHUB_TOKEN` | — | GitHub PAT for GitHub Models API (enables AI generation without claude CLI) |
| `GITHUB_MODEL` | `gpt-4o` | GitHub Models model name |
| `WHISPER_MODEL` | `base` | faster-whisper model size |
| `YTSEO_DATA_DIR` | `<project_root>/data` | Base path for uploads, audio, models |
