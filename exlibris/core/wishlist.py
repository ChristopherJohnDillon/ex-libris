"""Wishlist: books you want but don't own, kept apart from the shelf. Its own table,
never in the shelf's search, stats, CSV or the public view. "Got it" moves a wish
onto the shelf (notes and all); adding a wished book any other way ticks it off:
same ISBN, or the same work when the wish didn't name an edition.

Per person when the library knows who's using it (see web.people): each wish has
an owner; without that, everyone shares one list (owner '')."""
import sqlite3
from exlibris.core import books, db

FIELDS = ("title", "authors", "year", "edition_year", "isbn", "publisher", "format", "pages", "cover_url", "ol_key",
          "edition_key", "series", "series_index", "notes")
EDITABLE = ("title", "authors", "year", "edition_year", "isbn", "publisher", "format", "pages", "notes")


class Owned(Exception):
    """That exact edition is already on the shelf."""


def list_wishes(owner=None):
    """Newest first. owner=None: everyone's."""
    with db.connect() as c:
        if owner is None:
            rows = c.execute("SELECT * FROM wishlist ORDER BY added_at DESC, id DESC")
        else:
            rows = c.execute("SELECT * FROM wishlist WHERE owner = ? ORDER BY added_at DESC, id DESC", (owner,))
        return [dict(r) for r in rows]


def owners():
    with db.connect() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT owner FROM wishlist WHERE owner != '' ORDER BY owner")]


def get(wish_id):
    with db.connect() as c:
        r = c.execute("SELECT * FROM wishlist WHERE id = ?", (wish_id,)).fetchone()
    return dict(r) if r else None


def add(book, owner=""):
    """books.Duplicate if it's already on this person's list, Owned if on the shelf."""
    row = books._clean({k: book.get(k) for k in FIELDS if book.get(k) not in (None, "")}, FIELDS)
    if not row.get("title"):
        raise ValueError("A book needs a title")
    row["owner"] = owner or ""
    with db.connect() as c:
        if row.get("isbn") and c.execute("SELECT 1 FROM books WHERE isbn = ?", (row["isbn"],)).fetchone():
            raise Owned(row["title"])
        if not row.get("isbn") and row.get("ol_key") and c.execute(
                "SELECT 1 FROM wishlist WHERE ol_key = ? AND isbn IS NULL AND owner = ?", (row["ol_key"], row["owner"])).fetchone():
            raise books.Duplicate(row["title"])
        try:
            cur = c.execute(f"INSERT INTO wishlist ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
        except sqlite3.IntegrityError:
            raise books.Duplicate(row["title"])
        return dict(c.execute("SELECT * FROM wishlist WHERE id = ?", (cur.lastrowid,)).fetchone())


def update(wish_id, changes):
    vals = books._clean(changes, EDITABLE)
    with db.connect() as c:
        w = c.execute("SELECT owner FROM wishlist WHERE id = ?", (wish_id,)).fetchone()
        if not w:
            return None
        if vals.get("isbn"):
            other = c.execute("SELECT title FROM wishlist WHERE isbn = ? AND owner = ? AND id != ?",
                              (vals["isbn"], w[0], wish_id)).fetchone()
            if other:
                raise books.Duplicate(other[0])
        if vals:
            c.execute(f"UPDATE wishlist SET {', '.join(f'{k} = ?' for k in vals)} WHERE id = ?", (*vals.values(), wish_id))
        return dict(c.execute("SELECT * FROM wishlist WHERE id = ?", (wish_id,)).fetchone())


def delete(wish_id):
    with db.connect() as c:
        return c.execute("DELETE FROM wishlist WHERE id = ?", (wish_id,)).rowcount > 0


def got_it(wish_id, location=None):
    """The wish becomes a book on the shelf and leaves the list. If that copy is
    already there, the wish just goes. -> (book, already_there), or None."""
    w = get(wish_id)
    if w is None:
        return None
    book = {k: w[k] for k in books.ADD_FIELDS if k in w}
    book["location"] = location
    try:
        b, already = books.add(book), False
    except books.Duplicate:
        col, val = ("isbn", w["isbn"]) if w["isbn"] else ("ol_key", w["ol_key"])
        hits = books.where(col, val) if val else []
        if not hits:
            raise
        b, already = hits[0], True
    fulfil(b)
    delete(wish_id)
    return b, already


def fulfil(book):
    """A book just went on the shelf: everyone's wishes it answers are ticked off, and
    their notes go on the book if it has none. -> titles ticked off"""
    with db.connect() as c:
        rows = c.execute("SELECT * FROM wishlist WHERE (isbn IS NOT NULL AND isbn = ?) "
                         "OR (isbn IS NULL AND ol_key IS NOT NULL AND ol_key = ?)", (book.get("isbn"), book.get("ol_key"))).fetchall()
        notes = "\n".join(dict.fromkeys(r["notes"] for r in rows if r["notes"]))
        if notes and not book.get("notes"):
            c.execute("UPDATE books SET notes = ? WHERE id = ?", (notes, book["id"]))
        c.executemany("DELETE FROM wishlist WHERE id = ?", [(r["id"],) for r in rows])
    return [r["title"] for r in rows]


def wished(owner=None):
    """(ISBNs, works) on one person's list (None: anyone's)"""
    with db.connect() as c:
        rows = c.execute("SELECT isbn, ol_key FROM wishlist WHERE ? IS NULL OR owner = ?", (owner, owner)).fetchall()
    return {r[0] for r in rows if r[0]}, {r[1] for r in rows if r[1]}


def match(isbn=None, ol_key=None, me=""):
    """The wish for this ISBN, else one for the same work; yours first. None if neither."""
    with db.connect() as c:
        r = None
        if isbn:
            r = c.execute("SELECT * FROM wishlist WHERE isbn = ? ORDER BY owner != ?, id LIMIT 1", (isbn, me)).fetchone()
        if r is None and ol_key:
            r = c.execute("SELECT * FROM wishlist WHERE ol_key = ? ORDER BY owner != ?, isbn IS NOT NULL, id LIMIT 1",
                          (ol_key, me)).fetchone()
    return {**dict(r), "mine": r["owner"] == me} if r else None
