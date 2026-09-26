from exlibris import config
from exlibris.core import db


def test_init_creates_folders_and_database():
    db.init()
    d = config.settings().data_dir
    for name in ("library.db", "covers", "cache", "backups"):
        assert (d / name).exists(), name


def test_init_is_idempotent_and_versioned():
    db.init()
    db.init()
    with db.connect() as c:
        assert c.execute("SELECT version FROM schema_version").fetchone()[0] == db.SCHEMA_VERSION == 1


def test_full_text_search_follows_changes():
    db.init()
    with db.connect() as c:
        c.execute("INSERT INTO books (title, authors) VALUES ('Harry Potter', 'J. K. Rowling')")
        find = lambda q: [r[0] for r in c.execute(
            "SELECT books.title FROM books_fts JOIN books ON books.id = books_fts.rowid WHERE books_fts MATCH ?", (q,))]
        assert find('"harr"*') == ["Harry Potter"]
        c.execute("UPDATE books SET title = 'Dune'")
        assert find('"harr"*') == [] and find('"dune"*') == ["Dune"]
        c.execute("DELETE FROM books")
        assert find('"dune"*') == []


def test_settings_defaults(monkeypatch):
    s = config.settings()
    assert s.title == "Our books" and s.public is True and s.ai_url == ""
    monkeypatch.setenv("EXLIBRIS_PUBLIC", "off")
    monkeypatch.setenv("EXLIBRIS_TITLE", "The Smiths' books")
    s = config.settings()
    assert s.public is False and s.title == "The Smiths' books"
