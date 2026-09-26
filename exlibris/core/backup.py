"""Backups inside the data folder: a dated, integrity-checked copy of the database
plus a CSV each night (30 days kept, the newest always kept), and a one-click zip
of everything for download."""
import datetime as dt
import io
import os
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path
from exlibris import config
from exlibris.core import books, db

KEEP_DAYS = 30


def backups_dir():
    d = config.settings().data_dir / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def copy_db(dest):
    """A consistent, self-contained copy of the live database (rollback journal, checked)."""
    dest = Path(dest)
    tmp = dest.with_name(f".{dest.name}.tmp")
    src, out = sqlite3.connect(f"file:{db.path()}?mode=ro", uri=True), sqlite3.connect(tmp)
    try:
        src.backup(out)
        out.execute("PRAGMA journal_mode=DELETE")
        verdict = out.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        out.close()
        src.close()
    if verdict != "ok":
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"backup failed its integrity check: {verdict}")
    os.replace(tmp, dest)
    return dest


def prune(d, keep_days=KEEP_DAYS, now=None):
    now = time.time() if now is None else now
    files = sorted((p for p in Path(d).glob("library-*") if p.is_file()), key=lambda p: p.stat().st_mtime)
    newest = {files[-1].stem} if files else set()      # the newest copy (its .db and .csv share a name)
    for p in files:
        if p.stem not in newest and p.stat().st_mtime < now - keep_days * 86400:
            p.unlink()


def snapshot(now=None):
    db.init()
    stamp = dt.datetime.fromtimestamp(time.time() if now is None else now).strftime("%Y%m%d")
    d = backups_dir()
    out = copy_db(d / f"library-{stamp}.db")
    out.with_suffix(".csv").write_text(books.to_csv())
    prune(d, now=now)
    return out


def zip_bytes():
    db.init()
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(copy_db(Path(tmp) / "library.db"), "library.db")
        z.writestr("books.csv", books.to_csv())
        for p in sorted((config.settings().data_dir / "covers").glob("*.jpg")):
            z.write(p, f"covers/{p.name}")
    return buf.getvalue()
