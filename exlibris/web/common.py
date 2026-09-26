"""Pieces both web apps share: templates, security headers, the same-origin rule."""
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates
from exlibris import __version__, config
from exlibris.core import books

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / "templates"))
templates.env.globals.update(version=__version__, genres=books.GENRES, settings=config.settings)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")
HEADERS = {"Content-Security-Policy": CSP, "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff",
           "Referrer-Policy": "no-referrer", "Cross-Origin-Opener-Policy": "same-origin",
           "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()"}


def add_security_headers(app):
    @app.middleware("http")
    async def _headers(request, call_next):
        resp = await call_next(request)
        for k, v in HEADERS.items():
            resp.headers.setdefault(k, v)
        return resp


def same_origin(request: Request):
    """Writes must be JSON or carry HX-Request (a cross-site form can send neither
    without a CORS preflight), and a request from another Origin is refused."""
    ctype = request.headers.get("content-type", "")
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and not (
            "application/json" in ctype or request.headers.get("hx-request") == "true"):
        raise HTTPException(415, "JSON requests only")
    origin = request.headers.get("origin")
    if origin and origin.split("://", 1)[-1] != request.headers.get("host", ""):
        raise HTTPException(403, "cross-origin request refused")


def render(request, name, ctx=None, headers=None):
    resp = templates.TemplateResponse(request, name, {"title": config.settings().title, **(ctx or {})})
    for k, v in (headers or {}).items():
        resp.headers[k] = v
    return resp
