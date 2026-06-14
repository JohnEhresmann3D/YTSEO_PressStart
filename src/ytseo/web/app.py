"""FastAPI application entry point for the YTSEO web UI."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from ytseo.web.routes import router, ws_clients

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="YTSEO", version="0.1.0")
app.include_router(router)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def main() -> None:
    parser = argparse.ArgumentParser(description="YTSEO web server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument(
        "--github-token",
        metavar="TOKEN",
        help="GitHub personal access token for GitHub Models API (overrides .env / GITHUB_TOKEN)",
    )
    args = parser.parse_args()

    if args.github_token:
        os.environ["GITHUB_TOKEN"] = args.github_token

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
    log.info("Starting YTSEO web server at http://%s:%d", args.host, args.port)

    if os.environ.get("GITHUB_TOKEN"):
        model = os.environ.get("GITHUB_MODEL", "gpt-4o")
        log.info("GitHub Models API enabled (model: %s)", model)
    else:
        log.info("GitHub Models API not configured — will use claude CLI if available")

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
