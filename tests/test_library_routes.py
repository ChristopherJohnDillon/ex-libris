import io
import zipfile
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from exlibris.core import books, openlibrary
from exlibris.web import library

J = {"Content-Type": "application/json"}


@pytest.fixture
def c():
    return TestClient(library.app)


def jpeg(w=120, h=180):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (30, 60, 90)).save(buf, "JPEG")
    return buf.getvalue()


def test_add_edit_delete(c):
    r = c.post("/api/books", json={"title": "Dune", "isbn": "9780441013593"})
    assert r.status_code == 201
    bid = r.json()["id"]
    assert c.post("/api/books", json={"title": "x", "isbn": "9780441013593"}).status_code == 409
    got = c.patch(f"/api/books/{bid}", json={"genre": "Sci-fi & fantasy", "pages": "612"}).json()
    assert got["genre"] == "Sci-fi & fantasy" and got["pages"] == 612
    assert c.patch(f"/api/books/{bid}", json={"year": "c. 1965"}).status_code == 422
    assert c.get("/api/books", params={"q": "dune"}).json()["books"][0]["id"] == bid
    assert c.delete(f"/api/books/{bid}", headers=J).status_code == 204
    assert c.get(f"/api/books/{bid}").status_code == 404


def test_writes_need_json_or_htmx_and_same_origin(c):
    assert c.post("/api/books", data={"title": "x"}).status_code == 415
    assert c.post("/api/books", json={"title": "x"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.delete("/api/books/1").status_code == 415


def test_security_headers_everywhere(c):
    for path in ("/healthz", "/api/books"):
        h = c.get(path).headers
        assert "script-src 'self'" in h["content-security-policy"] and h["x-frame-options"] == "DENY"
        assert "camera=()" in h["permissions-policy"]


def _fake_client(monkeypatch, edition=None, fail=False):
    class FakeClient:
        def edition(self, isbn):
            if fail:
                raise openlibrary.Unavailable("down")
            return edition
        def search(self, q):
            if fail:
                raise openlibrary.Unavailable("down")
            return []
    monkeypatch.setattr(library, "ol", lambda: FakeClient())


def test_do_i_own_this(c, monkeypatch):
    c.post("/api/books", json={"title": "HP", "isbn": "9780747532699", "ol_key": "/works/HP", "format": "Hardcover",
                               "location": "Lounge"})
    _fake_client(monkeypatch, fail=True)                                   # an exact match needs no network
    r = c.get("/api/own/978-0747532699").json()
    assert r["answer"] == "yes" and r["this"][0]["location"] == "Lounge"
    _fake_client(monkeypatch, edition={"title": "HP", "works": [{"key": "/works/HP"}], "physical_format": "paperback"})
    r = c.get("/api/own/9781408855652").json()
    assert r["answer"] == "other" and r["others"][0]["format"] == "Hardcover" and r["found"]["format"] == "Paperback"
    _fake_client(monkeypatch, fail=True)
    assert c.get("/api/own/9780141439587").json() == {"answer": "no", "isbn": "9780141439587", "this": [], "others": [],
                                                       "found": None, "unsure": True}
    assert c.get("/api/own/hello").status_code == 422


def test_lookup_when_open_library_is_down(c, monkeypatch):
    _fake_client(monkeypatch, fail=True)
    r = c.get("/api/lookup", params={"q": "dune"})
    assert r.status_code == 502 and "Open Library" in r.json()["detail"]


def test_cover_upload_and_serving(c):
    b = c.post("/api/books", json={"title": "Dune"}).json()
    r = c.post(f"/api/books/{b['id']}/cover", files={"file": ("c.jpg", jpeg(), "image/jpeg")}, headers={"HX-Request": "true"})
    assert r.status_code == 200
    img = c.get(r.json()["cover_url"])
    assert img.status_code == 200 and img.content[:2] == b"\xff\xd8"
    bad = c.post(f"/api/books/{b['id']}/cover", files={"file": ("x.jpg", b"nope", "image/jpeg")}, headers={"HX-Request": "true"})
    assert bad.status_code == 415
    assert c.get("/cover/u1-deadbeef").status_code == 404 and c.get("/cover/..%2Fsecret").status_code == 404


def test_csv_export_import_and_backup_zip(c):
    c.post("/api/books", json={"title": "Dune", "isbn": "9780441013593"})
    csv_text = c.get("/export.csv").text
    assert "Dune" in csv_text
    preview = c.post("/api/import", json={"csv": csv_text + "Emma,Jane Austen\n", "commit": False}).json()
    assert [r["title"] for r in preview["new"]] == ["Emma"] and books.search()["total"] == 1
    c.post("/api/import", json={"csv": csv_text + "Emma,Jane Austen\n", "commit": True})
    assert books.search()["total"] == 2
    z = zipfile.ZipFile(io.BytesIO(c.get("/backup.zip").content))
    assert "library.db" in z.namelist()


def test_rooms_and_camera_only_on_scan(c):
    c.post("/api/books", json={"title": "A", "location": "Lounge"})
    assert c.get("/api/locations").json() == [{"name": "Lounge", "n": 1}]
    assert "camera=(self)" in c.get("/scan").headers["permissions-policy"]
