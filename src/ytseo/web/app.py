"""FastAPI application entry point for the YTSEO web UI."""

from __future__ import annotations

import argparse
import logging
import os
import secrets
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from ytseo.web.routes import router, ws_clients

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
LOGIN_PATH = "/login"
PUBLIC_PREFIXES = (LOGIN_PATH, "/logout", "/api/auth/")  # OAuth callbacks must stay public
PUBLIC_FILES = ("/favicon.ico",)


def _admin_user() -> str:
    return os.environ.get("YTSEO_ADMIN_USER", "admin")


def _admin_password() -> str:
    return os.environ.get("YTSEO_ADMIN_PASSWORD", "pressstart")


def _is_authed(request: Request) -> bool:
    return bool(request.session.get("user"))


def _is_public_path(path: str) -> bool:
    if path in PUBLIC_FILES:
        return True
    return any(path == p or path.startswith(p) for p in PUBLIC_PREFIXES)


app = FastAPI(title="YTSEO", version="0.1.0")


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
    if _is_public_path(path) or _is_authed(request):
        return await call_next(request)
    # API requests get JSON 401; pages get redirected
    if path.startswith("/api/") or path.startswith("/ws"):
        return HTMLResponse("Unauthorized", status_code=401)
    next_url = path + ("?" + request.url.query if request.url.query else "")
    return RedirectResponse(f"{LOGIN_PATH}?next={next_url}", status_code=302)


@app.get(LOGIN_PATH, response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/") -> HTMLResponse:
    if _is_authed(request):
        return RedirectResponse(next or "/", status_code=302)
    return _render_login(next=next, error=None)


@app.post(LOGIN_PATH)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    if secrets.compare_digest(username, _admin_user()) and secrets.compare_digest(password, _admin_password()):
        request.session["user"] = username
        return RedirectResponse(next or "/", status_code=302)
    return _render_login(next=next, error="Invalid username or password.")


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(LOGIN_PATH, status_code=302)


def _render_login(next: str, error: str | None) -> HTMLResponse:
    html = (STATIC_DIR / "login.html").read_text(encoding="utf-8")
    err_html = f'<div class="err">{error}</div>' if error else ""
    safe_next = (next or "/").replace('"', "&quot;").replace("<", "&lt;")
    html = html.replace("{{ERROR}}", err_html).replace("{{NEXT}}", safe_next)
    return HTMLResponse(html)


# Add SessionMiddleware LAST so it ends up outermost — auth_gate (added above)
# needs request.session populated before it runs.
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("YTSEO_SESSION_SECRET") or secrets.token_urlsafe(32),
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 24 * 14,  # 2 weeks
)


app.include_router(router)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    # Session is populated by SessionMiddleware on the WS scope
    if not ws.session.get("user"):
        await ws.close(code=4401)
        return
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
    parser.add_argument(
        "--host",
        default=os.environ.get("HOST", "127.0.0.1"),
        help="Bind host (default: 127.0.0.1, or $HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8000")),
        help="Bind port (default: 8000, or $PORT)",
    )
    parser.add_argument(
        "--github-token",
        metavar="TOKEN",
        help="GitHub personal access token for GitHub Models API (overrides .env / GITHUB_TOKEN)",
    )
    parser.add_argument(
        "--proxy-headers",
        action="store_true",
        default=os.environ.get("PROXY_HEADERS", "").lower() in ("1", "true", "yes"),
        help="Trust X-Forwarded-* headers (enable when running behind a reverse proxy / Railway / DO App Platform). Also enabled via PROXY_HEADERS=1.",
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

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        proxy_headers=args.proxy_headers,
        forwarded_allow_ips="*" if args.proxy_headers else None,
    )


if __name__ == "__main__":
    main()
