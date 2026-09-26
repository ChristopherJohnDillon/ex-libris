"""Book covers: resizing uploads and finding covers for books that have none.
Search order, best match first: Google Books by ISBN (usually the very edition),
the Open Library work's cover, Google Books by title + author, Open Library search.
Downloaded and uploaded images are kept in <data>/covers as u<book>-<hash>.jpg;
Open Library covers are served from their id and cached on first view."""
import hashlib
import io
import threading
import time
import httpx
from PIL import Image, UnidentifiedImageError
from exlibris import config
from exlibris.core import books, db, openlibrary

MAX_PX = 600
MIN_PX = 60
GOOGLE = "https://www.googleapis.com/books/v1/volumes"
_google_lock, _google_last = threading.Lock(), [float("-inf")]


def covers_dir():
    d = config.settings().data_dir / "covers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_image(book_id, data):
    """Image bytes -> a stored cover URL for the book, or None if it isn't a usable image."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError):
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
    for step in steps:
        try:
            hit = step()
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError, openlibrary.Unavailable, openlibrary.NotFound):
            hit = None
        if hit:
            return hit
    return None, None


def fill_missing(json_get=None, image_get=None, limit=20):
    json_get, image_get = json_get or _default_json, image_get or _default_bytes
    with db.connect() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM books WHERE coalesce(cover_url, '') = '' AND cover_tried IS NULL "
                                           "ORDER BY id LIMIT ?", (limit,))]
    found = 0
    for b in rows:
        url, _ = find(b, json_get, image_get)
        if url:
            books.set_fields(b["id"], cover_url=url)
            found += 1
        books.set_fields(b["id"], cover_tried=1)
    return f"{found} cover{'s' if found != 1 else ''} found of {len(rows)} tried"
