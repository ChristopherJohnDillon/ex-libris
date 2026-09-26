"""The library app (port 8080): browse, add, scan, edit, stats, import/export,
backups. It has no login of its own: put it behind Cloudflare Access, a VPN or
keep it on the home network (see README)."""
import re
from contextlib import asynccontextmanager
from fastapi import Body, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from exlibris import config
from exlibris.core import backup, books, covers, db, openlibrary, stats
from exlibris.web.common import HERE, add_security_headers, render, same_origin

@asynccontextmanager
async def lifespan(app):
    db.init()
    yield


app = FastAPI(title="Ex Libris", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
add_security_headers(app)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
WRITE = [Depends(same_origin)]
COVER_NAME = re.compile(r"\d{1,12}|u\d{1,12}-[0-9a-f]{8}")
MAX_UPLOAD = 8 * 1024 * 1024


def ol():
    return openlibrary.client()


# ---- pages ----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return render(request, "library.html", {"total": books.search(limit=1)["total"],
                                            "overdue": books.overdue_loans(), "page": "books"})


@app.get("/scan", response_class=HTMLResponse)
def scan(request: Request):
    return render(request, "scan.html", {"page": "scan"},
                  headers={"Permissions-Policy": "camera=(self), microphone=(), geolocation=(), payment=(), usb=()"})


@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request):
    st = stats.stats()
    return render(request, "stats.html", {"st": st, "hl": stats.highlights(st), "private": True, "page": "stats",
                                          "author_base": "/author?name="})


@app.get("/author", response_class=HTMLResponse)
def author(request: Request, name: str = ""):
    return render(request, "author.html", {"name": name.strip(), "books": books.by_author(name) if name.strip() else [],
                                           "private": True, "page": "books"})


@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    return render(request, "import.html", {"page": "books"})


# ---- books API ------------------------------------------------------------------------
@app.get("/api/books")
def list_books(q: str = ""):
    return books.search(q)


@app.get("/api/books/{book_id}")
def one(book_id: int):
    b = books.get(book_id)
    if b is None:
        raise HTTPException(404, "No such book")
    return b


@app.post("/api/books", status_code=201, dependencies=WRITE)
def add(book: dict = Body(...)):
    if book.get("cover_url") and not re.fullmatch(r"/cover/" + COVER_NAME.pattern, book["cover_url"]):
        book = {**book, "cover_url": None}                   # only covers this app serves
    try:
        return books.add(book)
    except books.Duplicate as e:
        raise HTTPException(409, f"Already on the shelf as “{e}”.")
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.patch("/api/books/{book_id}", dependencies=WRITE)
def edit(book_id: int, changes: dict = Body(...)):
    try:
        b = books.update(book_id, changes)
    except books.Duplicate as e:
        raise HTTPException(409, f"That ISBN is already on the shelf as “{e}”.")
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))
    if b is None:
        raise HTTPException(404, "No such book")
    return b


@app.delete("/api/books/{book_id}", status_code=204, dependencies=WRITE)
def remove(book_id: int):
    if not books.delete(book_id):
        raise HTTPException(404, "No such book")
    return Response(status_code=204)


@app.post("/api/books/{book_id}/refresh", dependencies=WRITE)
def refresh(book_id: int):
    b = books.get(book_id)
    if b is None:
        raise HTTPException(404, "No such book")
    if not b.get("isbn"):
        raise HTTPException(422, "Add an ISBN first, then refresh.")
    try:
        ed = ol().edition(b["isbn"])
    except openlibrary.Unavailable:
        raise HTTPException(502, "Open Library didn't answer. Try again in a moment.")
    if not ed:
        raise HTTPException(404, "Open Library doesn't know that ISBN.")
    return books.fill_blanks(book_id, openlibrary.edition_row(ed, None, b["isbn"]))


@app.post("/api/books/{book_id}/cover", dependencies=WRITE)
async def upload_cover(book_id: int, file: UploadFile = File(...)):
    if books.get(book_id) is None:
        raise HTTPException(404, "No such book")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "That image is over 8 MB.")
    url = covers.save_image(book_id, data)
    if not url:
        raise HTTPException(415, "That file isn't an image (or it's tiny).")
    books.set_fields(book_id, cover_url=url)
    return books.get(book_id)


# ---- looking things up ----------------------------------------------------------------
@app.get("/api/lookup")
def lookup(q: str):
    """Title/author search lists works; an ISBN returns that one edition."""
    q = q.strip()
    isbn = books.isbn13(q)
    try:
        client = ol()
        if isbn:
            ed = client.edition(isbn)
            rows = client.search(q)
            isbns, works = books.owned()
            if ed:
                row = openlibrary.edition_row(ed, rows[0] if rows else None, isbn)
                return [{**row, "owned": isbn in isbns, "other_edition": isbn not in isbns and row["ol_key"] in works}]
            return [{**r, "owned": isbn in isbns, "other_edition": isbn not in isbns and r["owned"]} for r in rows[:1]]
        return client.search(q)
    except openlibrary.Unavailable:
        raise HTTPException(502, "Open Library didn't answer — try again, or add the book by title.")


@app.get("/api/own/{raw}")
def own(raw: str):
    """Do I own this? An exact ISBN answers straight from the database (instant in a
    shop); otherwise the edition's work says whether another edition is on the shelf."""
    isbn = books.isbn13(raw)
    if not isbn:
        raise HTTPException(422, "That isn't a book ISBN.")
    this = books.where("isbn", isbn)
    if this:
        return {"answer": "yes", "isbn": isbn, "this": this, "others": [], "found": None}
    try:
        ed = ol().edition(isbn)
    except openlibrary.Unavailable:
        ed = None
    if not ed:
        return {"answer": "no", "isbn": isbn, "this": [], "others": [], "found": None, "unsure": True}
    found = openlibrary.edition_row(ed, None, isbn)
    others = books.where("ol_key", found["ol_key"]) if found["ol_key"] else []
    return {"answer": "other" if others else "no", "isbn": isbn, "this": [], "others": others, "found": found}


@app.get("/api/author_works")
def author_works(name: str):
    try:
        return ol().author_works(name.strip())
    except openlibrary.Unavailable:
        raise HTTPException(502, "Couldn't reach Open Library.")


@app.get("/api/locations")
def rooms():
    return books.locations()


# ---- import / export / backup ---------------------------------------------------------
@app.get("/export.csv")
def export():
    return Response(books.to_csv(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="ex-libris-books.csv"'})


@app.post("/api/import", dependencies=WRITE)
def import_books(payload: dict = Body(...)):
    text = payload.get("csv") or ""
    if len(text) > 5_000_000:
        raise HTTPException(413, "That file is too big.")
    return books.import_csv(text, commit=bool(payload.get("commit")))


@app.get("/backup.zip")
def backup_zip():
    return Response(backup.zip_bytes(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="ex-libris-backup.zip"'})


# ---- covers + health ------------------------------------------------------------------
@app.get("/cover/{name}")
def cover(name: str):
    if not COVER_NAME.fullmatch(name):
        raise HTTPException(404, "no cover")
    path = covers.covers_dir() / f"{name}.jpg"
    if not path.exists() and name.isdigit():
        try:
            data = ol().cover_bytes(int(name))
        except (openlibrary.Unavailable, AttributeError):
            data = None
        if not data:
            raise HTTPException(404, "no cover")
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    if not path.exists():
        raise HTTPException(404, "no cover")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=31536000"})


@app.get("/healthz")
def healthz():
    return {"ok": True}
