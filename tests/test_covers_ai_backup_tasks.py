import io
import sqlite3
import threading
import time
import zipfile
import pytest
from PIL import Image
from exlibris import config
from exlibris.core import ai, backup, books, covers, tasks


def jpeg(w=100, h=150, color=(40, 80, 200)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


# ---- covers --------------------------------------------------------------------------
def test_upload_is_resized_and_stored():
    b = books.add({"title": "Dune"})
    url = covers.save_image(b["id"], jpeg(1200, 1800))
    assert url.startswith(f"/cover/u{b['id']}-")
    img = Image.open(config.settings().data_dir / "covers" / f"{url.rsplit('/', 1)[1]}.jpg")
    assert max(img.size) == covers.MAX_PX


def test_small_or_non_images_are_refused():
    b = books.add({"title": "Dune"})
    assert covers.save_image(b["id"], jpeg(20, 20)) is None
    assert covers.save_image(b["id"], b"<html>nope</html>") is None
    small_ok = covers.save_image(b["id"], jpeg(100, 150))
    img = Image.open(config.settings().data_dir / "covers" / f"{small_ok.rsplit('/', 1)[1]}.jpg")
    assert img.size == (100, 150)                                    # never enlarged


GOOGLE_HIT = {"items": [{"volumeInfo": {"imageLinks": {"thumbnail": "http://books.google.com/x?id=1&zoom=1"}}}]}


class Fake:
    def __init__(self, json_by=None, image=None):
        self.json_by, self.image, self.calls = json_by or {}, image, []

    def json(self, url, params=None):
        self.calls.append(url + str(params or ""))
        for k, v in self.json_by.items():
            if k in url + str(params or ""):
                return v
        return {}

    def bytes(self, url):
        self.calls.append(url)
        return self.image


def test_cover_search_order_and_single_try(monkeypatch):
    monkeypatch.setenv("EXLIBRIS_GOOGLE_BOOKS", "on")
    a = books.add({"title": "Skin Deep", "isbn": "9781844883936", "ol_key": "/works/W"})
    f = Fake({"isbn:9781844883936": GOOGLE_HIT, "/works/W": {"covers": [555]}}, image=jpeg())
    url, source = covers.find(books.get(a["id"]), f.json, f.bytes)
    assert source == "Google Books (ISBN)" and "https://books.google.com" in f.calls[-1]
    b = books.add({"title": "Moustache", "ol_key": "/works/M"})
    f2 = Fake({"/works/M": {"covers": [-1, 777]}})
    assert covers.find(books.get(b["id"]), f2.json, f2.bytes) == ("/cover/777", "Open Library (work)")


def test_google_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("EXLIBRIS_GOOGLE_BOOKS", "off")
    a = books.add({"title": "Skin Deep", "isbn": "9781844883936"})
    f = Fake({"isbn:": GOOGLE_HIT}, image=jpeg())
    covers.find(books.get(a["id"]), f.json, f.bytes)
    assert not any("googleapis" in c for c in f.calls)


def test_fill_missing_tries_each_book_once():
    books.add({"title": "Has one", "cover_url": "/cover/1"})
    b = books.add({"title": "Moustache", "ol_key": "/works/M"})
    books.add({"title": "Nothing"})
    f = Fake({"/works/M": {"covers": [777]}})
    assert "1 cover" in covers.fill_missing(json_get=f.json, image_get=f.bytes)
    assert books.get(b["id"])["cover_url"] == "/cover/777"
    n = len(f.calls)
    covers.fill_missing(json_get=f.json, image_get=f.bytes)
    assert len(f.calls) == n


# ---- AI ------------------------------------------------------------------------------
def reply(text):
    return lambda payload: {"choices": [{"message": {"content": text}}]}


@pytest.mark.parametrize("answer, expected", [
    ("Crime & thriller", "Crime & thriller"), ("crime & thriller", "Crime & thriller"), ('"Kids".', "Kids"),
    ("<think>juvenile</think>\nKids", "Kids"), ("It is Sci-fi & fantasy.", "Sci-fi & fantasy"),
    ("Young adult fiction", "Young adult"), ("Romance", "Other"), ("", None), ("<think>never ends", None),
])
def test_genre_answers(answer, expected):
    assert ai.choose_genre("T", "A", ["x"], post=reply(answer)) == expected


def test_ai_off_by_default_and_errors_are_none(monkeypatch):
    assert ai.enabled() is False
    monkeypatch.setenv("EXLIBRIS_AI_URL", "http://localhost:11434")
    assert ai.enabled() is True
    def boom(payload):
        raise OSError("down")
    assert ai.choose_genre("T", "A", [], post=boom) is None


def test_fill_genres_never_touches_hand_set(monkeypatch):
    monkeypatch.setenv("EXLIBRIS_AI_URL", "http://localhost:11434")
    a = books.add({"title": "Dune", "ol_key": "/works/D"})
    m = books.add({"title": "Mine", "ol_key": "/works/M"})
    books.update(m["id"], {"genre": "History"})
    ai.fill_genres(post=reply("Sci-fi & fantasy"), work=lambda key: {"subjects": ["Science fiction"]})
    assert books.get(a["id"])["genre"] == "Sci-fi & fantasy" and books.get(a["id"])["genre_source"] == "auto"
    assert books.get(m["id"])["genre"] == "History"


# ---- backups -------------------------------------------------------------------------
def test_snapshot_writes_checked_standalone_copies():
    books.add({"title": "Dune"})
    db_copy = backup.snapshot()
    d = config.settings().data_dir / "backups"
    assert db_copy.exists() and db_copy.with_suffix(".csv").exists()
    c = sqlite3.connect(db_copy)
    assert c.execute("pragma journal_mode").fetchone()[0] == "delete" and c.execute("select count(*) from books").fetchone()[0] == 1
    assert not [p for p in d.iterdir() if p.name.startswith(".")]


def test_prune_keeps_recent_and_the_newest(tmp_path):
    import os
    now = time.time()
    for age, name in ((100, "library-a.db"), (5, "library-b.db"), (200, "library-c.db")):
        p = tmp_path / name
        p.write_text("x")
        os.utime(p, (now - age * 86400, now - age * 86400))
    backup.prune(tmp_path, keep_days=30, now=now)
    assert [p.name for p in tmp_path.iterdir()] == ["library-b.db"]
    os.utime(tmp_path / "library-b.db", (now - 400 * 86400, now - 400 * 86400))
    backup.prune(tmp_path, keep_days=30, now=now)
    assert [p.name for p in tmp_path.iterdir()] == ["library-b.db"]


def test_zip_download_has_everything():
    b = books.add({"title": "Dune"})
    covers.save_image(b["id"], jpeg())
    z = zipfile.ZipFile(io.BytesIO(backup.zip_bytes()))
    names = z.namelist()
    assert "library.db" in names and "books.csv" in names and any(n.startswith("covers/") for n in names)


# ---- tasks ---------------------------------------------------------------------------
def test_a_failing_task_does_not_stop_the_loop():
    ran = []
    jobs = [tasks.Job("boom", 0, lambda: 1 / 0), tasks.Job("ok", 0, lambda: ran.append(1))]
    stop = threading.Event()
    t = threading.Thread(target=tasks.run_forever, args=(stop, jobs, 0.01), daemon=True)
    t.start()
    time.sleep(0.1)
    stop.set()
    t.join(1)
    assert len(ran) >= 2
