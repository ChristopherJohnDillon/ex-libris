"""Book covers: resizing uploads and finding covers for books that have none.
Search order, best match first: Google Books by ISBN (usually the very edition),
the Open Library work's cover, Google Books by title + author, Open Library search.
Downloaded and uploaded images are kept in <data>/covers as u<book>-<hash>.jpg;
Open Library covers are served from their id and cached on first view."""
import hashlib
import io
import os
import tempfile
import threading
import time
import httpx
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError
from exlibris import config
from exlibris.core import books, db, openlibrary

MAX_PX = 600
MIN_PX = 60
MAX_PIXELS = 40_000_000        # a few hundred KB of PNG can decode to gigabytes; refuse before decoding
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
GOOGLE = "https://www.googleapis.com/books/v1/volumes"
_google_lock, _google_last = threading.Lock(), [float("-inf")]


def covers_dir():
    d = config.settings().data_dir / "covers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_image(book_id, data):
    """Image bytes -> a stored cover URL for the book, or None if it isn't a usable image."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            if img.width * img.height > MAX_PIXELS:
                return None
            img.draft("RGB", (MAX_PX * 2, MAX_PX * 2))    # JPEGs decode straight at a smaller size
            img.load()
            img = ImageOps.exif_transpose(img)           # phone photos: turn upright, then drop the tag
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None
    if img.width < MIN_PX:
        return None                                   # placeholders ("image not available") are tiny
    img = img.convert("RGB")
    img.thumbnail((MAX_PX, MAX_PX))                   # shrinks, never enlarges
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True)
    jpg = buf.getvalue()
    name = f"u{book_id}-{hashlib.sha256(jpg).hexdigest()[:8]}"
    (covers_dir() / f"{name}.jpg").write_bytes(jpg)
    return f"/cover/{name}"


def _google_json(url, params=None):
    with _google_lock:
        wait = _google_last[0] + 1.0 - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _google_last[0] = time.monotonic()
    r = httpx.get(url, params=params, headers={"User-Agent": openlibrary.user_agent()}, timeout=15.0)
    r.raise_for_status()
    return r.json()


def _default_json(url, params=None):
    if "googleapis.com" in url:
        return _google_json(url, params)
    c = openlibrary.client()
    if url.startswith("https://openlibrary.org/works/"):
        return c.work(url[len("https://openlibrary.org"):-len(".json")])
    return c._get(url, params)


def _default_bytes(url):
    r = httpx.get(url, headers={"User-Agent": openlibrary.user_agent()}, timeout=15.0, follow_redirects=True)
    r.raise_for_status()
    return r.content[:5_000_000]


def _google_thumb(data):
    for item in (data or {}).get("items") or []:
        links = (item.get("volumeInfo") or {}).get("imageLinks") or {}
        url = links.get("thumbnail") or links.get("smallThumbnail")
        if url:
            return url.replace("http://", "https://", 1).replace("&edge=curl", "")
    return None


def find(book, json_get, image_get):
    """-> (cover_url, where it came from) or (None, None)."""
    url, source, _ = _find(book, json_get, image_get)
    return url, source


def _find(book, json_get, image_get):
    """-> (cover_url, source, whether any source failed to answer)."""
    google = config.settings().google_books
    author = (books.authors_of(book) or [""])[0]

    def from_google(q, source):
        thumb = _google_thumb(json_get(GOOGLE, {"q": q, "maxResults": 3, "printType": "books"}))
        data = image_get(thumb) if thumb else None
        url = save_image(book["id"], data) if data else None
        return (url, source) if url else None

    def from_work():
        work = json_get(f"https://openlibrary.org{book['ol_key']}.json") or {}
        ids = [c for c in work.get("covers") or [] if isinstance(c, int) and c > 0]
        return (f"/cover/{ids[0]}", "Open Library (work)") if ids else None

    def from_search():
        params = {"title": book["title"], "fields": "cover_i", "limit": 5, **({"author": author} if author else {})}
        docs = json_get(openlibrary.SEARCH, params).get("docs") or []
        ids = [d["cover_i"] for d in docs if isinstance(d.get("cover_i"), int) and d["cover_i"] > 0]
        return (f"/cover/{ids[0]}", "Open Library (another edition)") if ids else None

    steps = []
    if book.get("isbn") and google:
        steps.append(lambda: from_google(f"isbn:{book['isbn']}", "Google Books (ISBN)"))
    if book.get("ol_key"):
        steps.append(from_work)
    if google:
        steps.append(lambda: from_google(f"intitle:{book['title']}" + (f" inauthor:{author}" if author else ""),
                                         "Google Books (title)"))
    steps.append(from_search)
    failed = False
    for step in steps:
        try:
            hit = step()
        except openlibrary.NotFound:
            hit = None
        except (httpx.HTTPError, OSError, openlibrary.Unavailable):
            hit, failed = None, True                       # no answer (network, outage): try again later
        except (ValueError, KeyError, TypeError):
            hit = None
        if hit:
            return hit[0], hit[1], False
    return None, None, failed


def fill_missing(json_get=None, image_get=None, limit=20):
    json_get, image_get = json_get or _default_json, image_get or _default_bytes
    with db.connect() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM books WHERE coalesce(cover_url, '') = '' AND cover_tried IS NULL "
                                           "ORDER BY id LIMIT ?", (limit,))]
    found = 0
    for b in rows:
        url, _, failed = _find(b, json_get, image_get)
        with db.connect() as c:
            if url:
                # only if nothing was set meanwhile (an upload while we searched wins)
                found += c.execute("UPDATE books SET cover_url = ?, cover_tried = 1 WHERE id = ? AND coalesce(cover_url, '') = ''",
                                   (url, b["id"])).rowcount
            elif not failed:
                c.execute("UPDATE books SET cover_tried = 1 WHERE id = ?", (b["id"],))
    return f"{found} cover{'s' if found != 1 else ''} found of {len(rows)} tried"


def download_missing_files(limit=50, client_=None):
    """Open Library covers are stored as ids; fetch the image files in the background
    (so the public view has them and nobody's page load waits on Open Library). A
    cover Open Library no longer has is cleared, so the finder can look elsewhere."""
    import re
    c = client_ or openlibrary.client()
    with db.connect() as conn:
        rows = conn.execute("SELECT id, cover_url FROM books WHERE cover_url GLOB '/cover/[0-9]*'").fetchall()
    todo = [(i, u) for i, u in rows if re.fullmatch(r"/cover/\d+", u) and not (covers_dir() / f"{u[7:]}.jpg").exists()][:limit]
    got = 0
    for book_id, url in todo:
        try:
            data = c.cover_bytes(int(url[7:]))
        except openlibrary.Unavailable:
            continue
        if data:
            store_open_library_cover(int(url[7:]), data)
            got += 1
        else:
            with db.connect() as conn:
                conn.execute("UPDATE books SET cover_url = NULL, cover_tried = NULL WHERE id = ? AND cover_url = ?", (book_id, url))
    return f"{got} cover file{'s' if got != 1 else ''} downloaded"


def store_open_library_cover(cover_id, data):
    path = covers_dir() / f"{int(cover_id)}.jpg"
    with tempfile.NamedTemporaryFile(dir=covers_dir(), suffix=".part", delete=False) as tmp:
        tmp.write(data)
    os.replace(tmp.name, path)
    return path
