import re
import pytest
from fastapi.testclient import TestClient
from starlette.routing import Mount, Route
from exlibris.core import books, covers
from exlibris.web import public

PRIVATE = {"notes", "location", "lent_to", "lent_on", "added_at", "subjects", "genre_source", "ol_key", "edition_key",
           "series_checked", "cover_tried"}


@pytest.fixture
def c():
    return TestClient(public.app)


@pytest.fixture
def book():
    b = books.add({"title": "Dune", "authors": "Frank Herbert", "isbn": "9780441013593", "location": "Den",
                   "notes": "signed by the author", "cover_url": "/cover/42"})
    books.update(b["id"], {"lent_to": "Sam", "genre": "Sci-fi & fantasy"})
    (covers.covers_dir() / "42.jpg").write_bytes(b"\xff\xd8x")
    (covers.covers_dir() / "43.jpg").write_bytes(b"\xff\xd8y")
    return b


def test_only_read_routes_exist():
    for r in public.app.routes:
        if isinstance(r, Route):
            assert r.methods <= {"GET", "HEAD"}, r.path
        elif isinstance(r, Mount):
            assert r.path == "/static", r.path


def test_every_write_is_refused(c, book):
    paths = [re.sub(r"{[^}]+}", str(book["id"]), r.path) for r in public.app.routes if isinstance(r, Route)]
    paths += ["/api/books", f"/api/books/{book['id']}", f"/api/books/{book['id']}/cover", "/api/import", "/"]
    for p in paths:
        for m in ("POST", "PUT", "PATCH", "DELETE"):
            res = c.request(m, p, json={"title": "hacked"}, headers={"HX-Request": "true"})
            assert res.status_code in (404, 405), (m, p, res.status_code)
    assert books.get(book["id"])["title"] == "Dune" and books.search()["total"] == 1


def test_no_private_field_anywhere(c, book):
    rows = c.get("/api/books").json()["books"]
    assert rows and not (PRIVATE & set(rows[0]))
    for path in ("/", f"/book/{book['id']}", "/stats", "/author?name=Frank%20Herbert"):
        t = c.get(path).text
        for secret in ("signed by the author", ">Den<", "Sam", "Lent out", "Books added per month"):
            assert secret not in t, (path, secret)


def test_search_ignores_notes(c, book):
    assert c.get("/api/books", params={"q": "signed"}).json()["books"] == []
    assert c.get("/api/books", params={"q": "herb"}).json()["books"][0]["title"] == "Dune"
    assert c.get("/api/books", params={"q": "x" * 5000}).status_code == 422


def test_covers_only_when_a_book_uses_them(c, book):
    assert c.get("/cover/42").status_code == 200
    assert c.get("/cover/43").status_code == 404 and c.get("/cover/999").status_code == 404


def test_nothing_links_to_the_library_app_or_editing(c, book):
    for path in ("/", f"/book/{book['id']}", "/stats", "/author?name=Frank%20Herbert"):
        t = c.get(path).text
        assert "/scan" not in t and "/api/books/" not in t and "Edit" not in t and "8080" not in t, path
        assert "/export.csv" not in t and "/backup.zip" not in t and "/import" not in t, path


def test_noindex_and_headers(c, book):
    r = c.get("/")
    assert "noindex" in r.headers["x-robots-tag"] and "script-src 'self'" in r.headers["content-security-policy"]


def test_unknown_book_and_odd_input(c):
    assert c.get("/book/999").status_code == 404
    assert c.get("/book/99999999999999999999").status_code == 404
    assert c.get("/author", follow_redirects=False).status_code in (302, 307)
