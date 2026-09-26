"""The SQLite database in the data folder: schema, versioned migrations, FTS."""
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from exlibris import config

SCHEMA_VERSION = 2
MIGRATIONS = {
    1: """
    BEGIN;
    CREATE TABLE books (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        authors TEXT,
        year INTEGER,
        isbn TEXT UNIQUE,
        publisher TEXT,
        format TEXT,
        pages INTEGER,
        cover_url TEXT,
        ol_key TEXT,
        edition_key TEXT,
        genre TEXT,
        genre_source TEXT,
        subjects TEXT,
        series TEXT,
        series_index REAL,
        series_checked INTEGER,
        cover_tried INTEGER,
        location TEXT,
        lent_to TEXT,
        lent_on TEXT,
        notes TEXT,
        added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX books_work ON books(ol_key);
    CREATE VIRTUAL TABLE books_fts USING fts5(
        title, authors, isbn, publisher, notes,
        content='books', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
    CREATE TRIGGER books_ai AFTER INSERT ON books BEGIN
        INSERT INTO books_fts(rowid, title, authors, isbn, publisher, notes)
        VALUES (new.id, new.title, new.authors, new.isbn, new.publisher, new.notes);
    END;
    CREATE TRIGGER books_ad AFTER DELETE ON books BEGIN
        INSERT INTO books_fts(books_fts, rowid, title, authors, isbn, publisher, notes)
        VALUES ('delete', old.id, old.title, old.authors, old.isbn, old.publisher, old.notes);
    END;
    CREATE TRIGGER books_au AFTER UPDATE ON books BEGIN
        INSERT INTO books_fts(books_fts, rowid, title, authors, isbn, publisher, notes)
        VALUES ('delete', old.id, old.title, old.authors, old.isbn, old.publisher, old.notes);
        INSERT INTO books_fts(rowid, title, authors, isbn, publisher, notes)
        VALUES (new.id, new.title, new.authors, new.isbn, new.publisher, new.notes);
    END;
    """,
    2: """
    BEGIN;
    ALTER TABLE books ADD COLUMN edition_year INTEGER;
    ALTER TABLE books ADD COLUMN year_checked INTEGER;
    """,
}


def path():
    return config.settings().data_dir / "library.db"


def folders():
    d = config.settings().data_dir
    try:
        for sub in ("", "covers", "cache", "backups"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=d, prefix=".write-test-"):
            pass
    except OSError:
        raise SystemExit(f"Ex Libris can't write to the data folder {d}. Make it writable by the user the app runs as "
                         f"(uid {os.getuid()}), or set PUID/PGID to your own user (see README → Data folder).")
    return d


def init():
    """Create the data folders and bring the schema up to date. Safe to call often."""
    folders()
    conn = sqlite3.connect(path())
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        current = row[0] if row else 0
        for v in range(current + 1, SCHEMA_VERSION + 1):
            # one transaction per step, version bump included: a crash leaves the old version intact
            conn.executescript(MIGRATIONS[v] + f"\nDELETE FROM schema_version; INSERT INTO schema_version VALUES ({v}); COMMIT;")
    finally:
        conn.close()


@contextmanager
def connect():
    if not path().exists():
        init()
    conn = sqlite3.connect(path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
