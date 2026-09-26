"""Open Library (openlibrary.org): book search, editions by ISBN, works, authors.
Their guidance: identify yourself, keep to 1 request/s (3/s with a contact),
cache what you can. Editions and works are cached for good, author lists for a week."""
import json
import os
import re
import threading
import time
import httpx
from exlibris import __version__, config
from exlibris.core import books, series

SEARCH = "https://openlibrary.org/search.json"
EDITION = "https://openlibrary.org/isbn/{}.json"
COVER = "https://covers.openlibrary.org/b/id/{}-M.jpg?default=false"
FIELDS = "key,title,author_name,first_publish_year,isbn,cover_i,publisher"
GAP_ANON, GAP_CONTACT = 1.1, 0.4
AUTHOR_TTL = 7 * 86400
REPO = "https://github.com/ChristopherJohnDillon/ex-libris"


class NotFound(Exception):
    pass


class Unavailable(Exception):
    pass


def user_agent():
    contact = config.settings().ol_contact
    return f"ex-libris/{__version__} (+{REPO}{'; ' + contact if contact else ''})"


def gap():
    return GAP_CONTACT if config.settings().ol_contact else GAP_ANON


def http_json(url, params=None):
    r = httpx.get(url, params=params, headers={"User-Agent": user_agent()}, timeout=15.0, follow_redirects=True)
    if r.status_code == 404:
        raise NotFound(url)
    r.raise_for_status()
    return r.json()


def http_bytes(url):
    r = httpx.get(url, headers={"User-Agent": user_agent()}, timeout=15.0, follow_redirects=True)
    if r.status_code == 404:
        raise NotFound(url)
    r.raise_for_status()
    return r.content[:5_000_000]


def _cache_path(kind, key):
    d = config.settings().data_dir / "cache" / kind
    d.mkdir(parents=True, exist_ok=True)
    return d / (re.sub(r"[^A-Za-z0-9_-]", "_", key)[:120] + ".json")


def cache_get(kind, key, ttl=None):
    p = _cache_path(kind, key)
    try:
        if ttl is not None and time.time() - p.stat().st_mtime > ttl:
            return None
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def cache_put(kind, key, value):
    p = _cache_path(kind, key)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(value))
    os.replace(tmp, p)
    return value


def cover_path(cover_id):
    return f"/cover/{int(cover_id)}" if isinstance(cover_id, int) and cover_id > 0 else None


def year_of(s):
    m = re.search(r"\b(1[5-9]|20)\d\d\b", s or "")
    return int(m.group()) if m else None


def edition_row(ed, work=None, isbn=None):
    """One edition (/isbn/<isbn>.json), topped up from its work's search row."""
    work = work or {}
    works = [w.get("key") for w in ed.get("works") or [] if w.get("key")]
    title = ed.get("title") or work.get("title") or "Untitled"
    if ed.get("subtitle"):
        title = f"{title}: {ed['subtitle']}"
    covers = [c for c in ed.get("covers") or [] if isinstance(c, int) and c > 0]
    name, idx = series.parse(ed.get("series"))
    pages = ed.get("number_of_pages")
    return {"title": title, "authors": work.get("authors"), "year": year_of(ed.get("publish_date")) or work.get("year"),
            "isbn": isbn, "publisher": (ed.get("publishers") or [None])[0] or work.get("publisher"),
            "cover_url": cover_path(covers[0]) if covers else work.get("cover_url"),
            "ol_key": works[0] if works else work.get("ol_key"), "edition_key": ed.get("key"),
            "format": books.norm_format(ed.get("physical_format")), "pages": pages if isinstance(pages, int) else None,
            "series": name, "series_index": idx}


def search_row(d, isbn=None, owned_works=frozenset()):
    return {"title": d.get("title", "Untitled"), "authors": ", ".join(d.get("author_name") or []) or None,
            "year": d.get("first_publish_year"), "isbn": isbn, "publisher": (d.get("publisher") or [None])[0],
            "cover_url": cover_path(d.get("cover_i")), "ol_key": d.get("key"), "owned": d.get("key") in owned_works}


_lock = threading.Lock()
_last = [float("-inf")]                                  # shared by every client in the process


class Client:
    def __init__(self, http_get=None, clock=time.monotonic, sleep=time.sleep):
        self.http_get, self.clock, self.sleep = http_get or http_json, clock, sleep
        self._last = _last if http_get is None else [float("-inf")]

    def pace(self):
        with _lock:
            wait = self._last[0] + gap() - self.clock()
            if wait > 0:
                self.sleep(wait)
            self._last[0] = self.clock()

    def _get(self, url, params=None):
        self.pace()
        try:
            return self.http_get(url, params)
        except NotFound:
            raise
        except (httpx.HTTPError, OSError, ValueError) as e:
            raise Unavailable(str(e)) from e

    def search(self, q):
        isbn = books.isbn13(q)
        params = {"q": f"isbn:{isbn}" if isbn else q, "fields": FIELDS, "limit": 12}
        try:
            docs = self._get(SEARCH, params).get("docs") or []
        except NotFound:
            docs = []
        _, works = books.owned()
        return [search_row(d, isbn, works) for d in docs]

    def edition(self, isbn):
        cached = cache_get("editions", isbn)
        if cached is not None:
            return cached
        try:
            ed = self._get(EDITION.format(isbn))
        except NotFound:
            return None
        return cache_put("editions", isbn, ed) if isinstance(ed, dict) else None

    def work(self, key):
        cached = cache_get("works", key)
        if cached is not None:
            return cached
        try:
            return cache_put("works", key, self._get(f"https://openlibrary.org{key}.json"))
        except NotFound:
            return cache_put("works", key, {})

    def author_works(self, name):
        cached = cache_get("authors", name.casefold(), ttl=AUTHOR_TTL)
        if cached is None:
            params = {"author": name, "fields": "key,title,first_publish_year,cover_i", "limit": 60, "sort": "old"}
            docs = self._get(SEARCH, params).get("docs") or []
            cached = cache_put("authors", name.casefold(), [
                {"title": d.get("title", "Untitled"), "year": d.get("first_publish_year"), "ol_key": d.get("key"),
                 "cover_url": cover_path(d.get("cover_i"))} for d in docs])
        _, works = books.owned()
        return [{**w, "owned": w["ol_key"] in works} for w in cached]

    def cover_bytes(self, cover_id):
        self.pace()
        try:
            return http_bytes(COVER.format(int(cover_id)))
        except NotFound:
            return None
        except (httpx.HTTPError, OSError) as e:
            raise Unavailable(str(e)) from e


def client():
    return Client()
