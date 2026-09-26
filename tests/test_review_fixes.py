"""Regression tests for the v1.0.0 review findings."""
import io
import json
import threading
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from exlibris import config
from exlibris.core import ai, books, covers, db, openlibrary, tasks
from exlibris.web import common, library, public


def png(w, h, color=(255, 255, 255)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


# 1 ---- numbers must be finite ------------------------------------------------------
@pytest.mark.parametrize("value", ["inf", "Infinity", "-inf", "nan", "1e999", 10 ** 30, {"a": 1}])
def test_bad_numbers_are_refused(value):
    b = books.add({"title": "Ripley's Game"})
    with pytest.raises(ValueError):
        books.update(b["id"], {"series_index": value} if not isinstance(value, int) else {"year": value})


def test_csv_with_infinity_is_refused_and_browsing_keeps_working():
    books.import_csv("title,series,series_index\nBad,S,inf\nGood,S,2\n", commit=True)
    lib = TestClient(library.app)
    assert lib.get("/api/books").status_code == 200 and TestClient(public.app).get("/api/books").status_code == 200
    assert [b["title"] for b in books.search()["books"]] == ["Good"]


def test_patch_with_odd_values_is_422():
    b = books.add({"title": "Ripley's Game"})
    lib = TestClient(library.app)
    assert lib.patch(f"/api/books/{b['id']}", json={"notes": {"x": 1}}).status_code == 422
    assert lib.patch(f"/api/books/{b['id']}", json={"year": 10 ** 30}).status_code == 422


# 2 ---- the public home page doesn't write, and concurrent init is safe ---------------
def test_public_home_does_not_touch_the_data_folder(monkeypatch):
    db.init()
    calls = []
    monkeypatch.setattr(db, "init", lambda: calls.append(1))
    assert TestClient(public.app).get("/").status_code == 200 and calls == []


def test_concurrent_init_never_fails():
    errors = []
    def run():
        for _ in range(60):
            try:
                db.folders()
            except Exception as e:
                errors.append(e)
    threads = [threading.Thread(target=run) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors


# 3 ---- health checks don't wait for workers; covers are prefetched -------------------
def test_healthz_is_async_in_both_apps():
    import inspect
    for app in (library.app, public.app):
        route = next(r for r in app.routes if getattr(r, "path", "") == "/healthz")
        assert inspect.iscoroutinefunction(route.endpoint)


def test_open_library_cover_files_are_downloaded_in_the_background():
    a = books.add({"title": "Ripley's Game", "cover_url": "/cover/555"})
    b = books.add({"title": "Gone", "cover_url": "/cover/666"})

    class Fake:
        def cover_bytes(self, cover_id):
            return png(120, 180) if cover_id == 555 else None
    note = covers.download_missing_files(client_=Fake())
    assert (covers.covers_dir() / "555.jpg").exists() and "1 cover file" in note
    assert books.get(b["id"])["cover_url"] is None                    # Open Library has no such cover: find another


# 4, 5 ---- images: bombs refused, phone photos upright ---------------------------------
def test_huge_images_are_refused_without_decoding():
    b = books.add({"title": "Ripley's Game"})
    assert covers.save_image(b["id"], png(14000, 12000)) is None


def test_phone_photos_are_turned_upright():
    b = books.add({"title": "Ripley's Game"})
    img = Image.new("RGB", (300, 200), (10, 20, 30))                 # stored landscape…
    exif = img.getexif()
    exif[0x0112] = 6                                                  # …with "rotate 90° clockwise"
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    url = covers.save_image(b["id"], buf.getvalue())
    saved = Image.open(config.settings().data_dir / "covers" / f"{url.rsplit('/', 1)[1]}.jpg")
    assert saved.size == (200, 300)


# 6 ---- a network failure doesn't mark a book as tried --------------------------------
def test_network_errors_leave_the_book_for_next_time():
    b = books.add({"title": "Ripley's Game", "ol_key": "/works/W"})
    def down(url, params=None):
        raise OSError("no network yet")
    covers.fill_missing(json_get=down, image_get=lambda u: None)
    assert books.get(b["id"])["cover_tried"] is None


# 7 ---- background writes never replace a concurrent hand edit ------------------------
def test_year_backfill_does_not_overwrite_an_edit_made_meanwhile():
    b = books.add({"title": "Ripley's Game", "ol_key": "/works/W", "year": 2008, "isbn": "9780393066470"})

    class Slow:
        def first_published(self, key):
            books.update(b["id"], {"year": 1999})                     # the owner types a year mid-lookup
            return 1974
    openlibrary.backfill_years(client_=Slow())
    assert books.get(b["id"])["year"] == 1999


def test_cover_fill_does_not_overwrite_an_upload_made_meanwhile():
    b = books.add({"title": "Ripley's Game", "ol_key": "/works/W"})
    def json_get(url, params=None):
        books.set_fields(b["id"], cover_url="/cover/u1-abcdef12")     # an upload lands mid-search
        return {"covers": [777]}
    covers.fill_missing(json_get=json_get, image_get=lambda u: None)
    assert books.get(b["id"])["cover_url"] == "/cover/u1-abcdef12"


# 8 ---- the AI fun-facts card exists (weekly, cached, library only) -------------------
def test_fun_facts_are_made_weekly_and_shown_on_the_library_stats(monkeypatch):
    monkeypatch.setenv("EXLIBRIS_AI_URL", "http://localhost:11434")
    books.add({"title": "Ripley's Game", "authors": "Patricia Highsmith", "year": 1974})
    post = lambda payload: {"choices": [{"message": {"content": "**Ripley fan club:** 1 book."}}]}
    assert ai.refresh_fun_facts(post=post, now=1000.0) is True
    assert ai.refresh_fun_facts(post=post, now=1000.0 + 86400) is False          # not again within a week
    assert "Ripley fan club" in TestClient(library.app).get("/stats").text
    assert "Ripley fan club" not in TestClient(public.app).get("/stats").text
    assert any(j.name == "fun facts" for j in tasks.default_jobs())


# 9 ---- reverse proxies ---------------------------------------------------------------
def test_writes_work_behind_a_proxy_that_rewrites_host():
    r = TestClient(library.app).post("/api/books", json={"title": "Ripley's Game"},
                                     headers={"Host": "127.0.0.1:8080", "Origin": "https://books.example.org",
                                              "X-Forwarded-Host": "books.example.org"})
    assert r.status_code == 201


# 10 ---- a cleared genre stays cleared ------------------------------------------------
def test_clearing_a_genre_is_a_hand_edit(monkeypatch):
    monkeypatch.setenv("EXLIBRIS_AI_URL", "http://localhost:11434")
    b = books.add({"title": "Ripley's Game", "ol_key": "/works/W"})
    books.set_fields(b["id"], genre="Kids", genre_source="auto")
    books.update(b["id"], {"genre": ""})
    ai.fill_genres(post=lambda p: {"choices": [{"message": {"content": "Kids"}}]}, work=lambda k: {"subjects": []})
    assert books.get(b["id"])["genre"] is None


# minor ---- HEAD, link scans never auto-add, CSV oddities, atomic migration ------------
def test_public_app_answers_head():
    books.add({"title": "Ripley's Game"})
    c = TestClient(public.app)
    for path in ("/", "/stats", "/api/books", "/healthz"):
        assert c.head(path).status_code == 200, path


def test_csv_oddities():
    big = "x" * 200_000
    r = books.import_csv(f'title,notes\nRipley\'s Game,"{big}"\n')
    assert r["new"] == [] and r["errors"]
    r = books.import_csv("title,authors\nRipley's Game,Patricia Highsmith\nRipley's Game,Patricia Highsmith\n")
    assert len(r["new"]) == 1 and len(r["duplicates"]) == 1


def test_migrations_are_atomic():
    assert all("BEGIN" in script for script in db.MIGRATIONS.values())
