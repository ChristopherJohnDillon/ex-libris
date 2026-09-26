"""The public view (port 8081): browse, search, book and author pages, stats.
Read-only by construction: this app registers GET routes only, sends public
fields only, serves only covers a book uses (never fetching for a visitor), and
links nowhere near the library app. Safe to share."""
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from exlibris.core import books, covers, db, stats
from exlibris.web.common import HERE, add_security_headers, render

@asynccontextmanager
async def lifespan(app):
    db.init()                                    # once at start; visitors' requests never write
    yield


app = FastAPI(title="Ex Libris (public)", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
add_security_headers(app)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
NOINDEX = {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "public, max-age=60"}
COVER_NAME = re.compile(r"\d{1,12}|u\d{1,12}-[0-9a-f]{8}")
MAX_Q = 200


def page(request, name, ctx):
    return render(request, name, {"public": True, "private": False, **ctx}, headers=NOINDEX)


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def home(request: Request):
    return page(request, "public_home.html", {"page": "books", "total": books.search(limit=1)["total"]})


@app.api_route("/api/books", methods=["GET", "HEAD"])
def api_books(q: str = Query("", max_length=MAX_Q)):
    data = books.search(q, public=True)
    return JSONResponse({"total": data["total"], "books": [books.public_row(b) for b in data["books"]]}, headers=NOINDEX)


@app.api_route("/book/{book_id}", methods=["GET", "HEAD"], response_class=HTMLResponse)
def book(request: Request, book_id: int):
    try:
        b = books.get(book_id)
    except OverflowError:
        b = None
    if b is None:
        raise HTTPException(404, "No such book")
    return page(request, "public_book.html", {"page": "books", "b": books.public_row(b), "authors": books.authors_of(b)})


@app.api_route("/author", methods=["GET", "HEAD"], response_class=HTMLResponse)
def author(request: Request, name: str = Query("", max_length=MAX_Q)):
    if not name.strip():
        return RedirectResponse("/", status_code=307)
    rows = [books.public_row(b) for b in books.by_author(name)]
    return page(request, "author.html", {"page": "books", "name": name.strip(), "books": rows, "book_href": "/book/"})


@app.api_route("/stats", methods=["GET", "HEAD"], response_class=HTMLResponse)
def stats_page(request: Request):
    st = stats.stats(public=True)
    return page(request, "stats.html", {"page": "stats", "st": st, "hl": stats.highlights(st), "author_base": "/author?name="})


@app.api_route("/cover/{name}", methods=["GET", "HEAD"])
def cover(name: str):
    path = covers.covers_dir() / f"{name}.jpg"
    if not COVER_NAME.fullmatch(name) or not path.exists():
        raise HTTPException(404, "no cover")
    with db.connect() as c:
        used = c.execute("SELECT 1 FROM books WHERE cover_url = ?", (f"/cover/{name}",)).fetchone()
    if not used:
        raise HTTPException(404, "no cover")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400", **NOINDEX})


@app.api_route("/healthz", methods=["GET", "HEAD"])
async def healthz():
    return {"ok": True}
