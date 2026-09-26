"""Books: one row per copy you own. Editions of the same work are separate rows
told apart by ISBN (unique); ol_key is the Open Library work."""
import csv
import datetime as dt
import io
import re
import sqlite3
from exlibris.core import db

PUBLIC_FIELDS = ("id", "title", "authors", "year", "edition_year", "format", "publisher", "isbn", "cover_url", "genre", "series",
                 "series_index", "pages")
ADD_FIELDS = ("title", "authors", "year", "edition_year", "isbn", "publisher", "format", "pages", "cover_url", "ol_key", "edition_key",
              "genre", "series", "series_index", "location", "notes")
EDITABLE = ("title", "authors", "year", "edition_year", "isbn", "publisher", "format", "pages", "genre", "series", "series_index",
            "location", "lent_to", "lent_on", "notes")
NUMBERS = {"year": (int, "Year"), "edition_year": (int, "Edition year"), "pages": (int, "Pages"), "series_index": (float, "Number in series")}
CSV_COLUMNS = ("title", "authors", "year", "isbn", "format", "publisher", "pages", "genre", "series", "series_index",
               "location", "notes", "edition_year", "lent_to", "lent_on", "added_at")
IMPORT_COLUMNS = CSV_COLUMNS[:13]
GENRES = ("Fiction", "Sci-fi & fantasy", "Crime & thriller", "Kids", "Young adult", "History", "Biography & memoir",
          "Science & nature", "Business & money", "Self-help", "Food & drink", "Travel", "Art & design", "Reference",
          "Other")
SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}
LOAN_DAYS = 60


class Duplicate(Exception):
    """Raised with the title of the book that's already on the shelf."""


# ---- identifiers and text -----------------------------------------------------------

def is_isbn13(s):
    if not re.fullmatch(r"97[89]\d{10}", s or ""):
        return False
    return sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(s)) % 10 == 0


def isbn13(text):
    """A typed ISBN-10 or ISBN-13 -> ISBN-13, or None if it isn't a valid one."""
    d = re.sub(r"[\s-]", "", text or "").upper()
    if is_isbn13(d):
        return d
    if re.fullmatch(r"\d{9}[\dX]", d) and sum((10 if c == "X" else int(c)) * (10 - i) for i, c in enumerate(d)) % 11 == 0:
        b = "978" + d[:9]
        return b + str((10 - sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(b)) % 10) % 10)
    return None


def norm_format(s):
    s = (s or "").strip()
    return (s.title() if s.islower() else s) or None


def authors_of(row):
    """'A, B' -> ['A', 'B'], keeping 'Jr.' and friends with the name before them."""
    out = []
    for part in (a.strip() for a in (row.get("authors") or "").split(",")):
        if not part:
            continue
        if part.lower() in SUFFIXES and out:
            out[-1] = f"{out[-1]}, {part}"
        else:
            out.append(part)
    return out


def public_row(row):
    return {k: row.get(k) for k in PUBLIC_FIELDS}


# ---- reading --------------------------------------------------------------------------

def fts_query(q):
    q = re.sub(r"(?<=\d)-(?=\d)", "", q or "")
    return " ".join(f'"{t}"*' for t in re.findall(r"\w+", q))


def search(q="", limit=100000, public=False):
    match = fts_query(q)
    with db.connect() as c:
        if match:
            if public:
                match = f"{{title authors isbn publisher}} : ({match})"
            rows = c.execute("SELECT books.* FROM books_fts JOIN books ON books.id = books_fts.rowid "
                             "WHERE books_fts MATCH ? ORDER BY bm25(books_fts, 10.0, 5.0, 1.0, 2.0, 1.0) LIMIT ?",
                             (match, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM books ORDER BY added_at, id LIMIT ?", (limit,)).fetchall()
        total = c.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    return {"total": total, "books": [dict(r) for r in rows]}


def get(book_id):
    with db.connect() as c:
        r = c.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    return dict(r) if r else None


def where(column, value):
    assert column in ("isbn", "ol_key")
    with db.connect() as c:
        return [dict(r) for r in c.execute(f"SELECT * FROM books WHERE {column} = ? ORDER BY year, id", (value,))]


def owned():
    """(ISBNs on the shelf, work keys on the shelf)"""
    with db.connect() as c:
        rows = c.execute("SELECT isbn, ol_key FROM books").fetchall()
    return {r[0] for r in rows if r[0]}, {r[1] for r in rows if r[1]}


def by_author(name):
    key = name.strip().casefold()
    hits = [r for r in search()["books"] if key in (a.casefold() for a in authors_of(r))]
    return sorted(hits, key=lambda r: (r["year"] is None, r["year"] or 0, r["series"] or "", r["series_index"] or 0, r["title"]))


def locations():
    with db.connect() as c:
        rows = c.execute("SELECT trim(location) AS name, COUNT(*) AS n FROM books WHERE trim(coalesce(location, '')) != '' "
                         "GROUP BY trim(location) ORDER BY n DESC, name").fetchall()
    return [dict(r) for r in rows]


def overdue_loans(today=None, days=LOAN_DAYS):
    today = today or dt.date.today()
    out = []
    with db.connect() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM books WHERE lent_to IS NOT NULL AND lent_on IS NOT NULL")]
    for r in rows:
        try:
            since = dt.date.fromisoformat(r["lent_on"][:10])
        except ValueError:
            continue
        if (today - since).days > days:
            out.append({**r, "days": (today - since).days})
    return sorted(out, key=lambda r: r["lent_on"])


# ---- writing --------------------------------------------------------------------------

def _clean(changes, allowed, today=None):
    today = today or dt.date.today()
    out = {}
    for k, v in changes.items():
        if k not in allowed:
            raise ValueError(f"{k} can't be set here")
        out[k] = (v.strip() or None) if isinstance(v, str) else v
    if "title" in out and not out["title"]:
        raise ValueError("A book needs a title")
    for k, (kind, label) in NUMBERS.items():
        if out.get(k) is not None:
            try:
                out[k] = kind(out[k])
            except (TypeError, ValueError):
                raise ValueError(f"{label} should be a number")
    if out.get("isbn"):
        out["isbn"] = isbn13(out["isbn"]) or re.sub(r"[\s-]", "", out["isbn"]).upper()
    if "format" in out:
        out["format"] = norm_format(out["format"])
    if "genre" in out and "genre_source" not in out:
        out["genre_source"] = "manual" if out["genre"] else None
    if out.get("lent_to") and "lent_on" not in out:
        out["lent_on"] = today.isoformat()
    if "lent_to" in out and not out["lent_to"]:
        out["lent_on"] = None
    return out


def add(book):
    row = _clean({k: book.get(k) for k in ADD_FIELDS if book.get(k) not in (None, "")}, ADD_FIELDS + ("genre_source",))
    if not row.get("title"):
        raise ValueError("A book needs a title")
    with db.connect() as c:
        if not row.get("isbn") and row.get("ol_key") and c.execute("SELECT 1 FROM books WHERE ol_key = ?", (row["ol_key"],)).fetchone():
            raise Duplicate(row["title"])
        try:
            cur = c.execute(f"INSERT INTO books ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
        except sqlite3.IntegrityError:
            other = c.execute("SELECT title FROM books WHERE isbn = ?", (row.get("isbn"),)).fetchone()
            raise Duplicate(other[0] if other else row["title"])
        return dict(c.execute("SELECT * FROM books WHERE id = ?", (cur.lastrowid,)).fetchone())


def update(book_id, changes, today=None):
    vals = _clean(changes, EDITABLE, today)
    if "year" in vals:
        vals["year_checked"] = 1                  # a hand-set year is never "corrected" by the background task
    with db.connect() as c:
        if not c.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone():
            return None
        if vals.get("isbn"):
            other = c.execute("SELECT title FROM books WHERE isbn = ? AND id != ?", (vals["isbn"], book_id)).fetchone()
            if other:
                raise Duplicate(other[0])
        if vals:
            c.execute(f"UPDATE books SET {', '.join(f'{k} = ?' for k in vals)} WHERE id = ?", (*vals.values(), book_id))
        return dict(c.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone())


def set_fields(book_id, **fields):
    """Internal updates (covers, genres, series) that bypass the edit rules."""
    with db.connect() as c:
        c.execute(f"UPDATE books SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), book_id))


def fill_blanks(book_id, found):
    """Copy fields the book doesn't have yet; never overwrite (hand edits stay)."""
    book = get(book_id)
    if book is None:
        return None
    keys = ("title", "authors", "year", "edition_year", "publisher", "format", "pages", "cover_url", "ol_key", "edition_key", "series",
            "series_index")
    fill = {k: found[k] for k in keys if found.get(k) not in (None, "") and book.get(k) in (None, "")}
    if fill:
        set_fields(book_id, **fill)
    return get(book_id)


def delete(book_id):
    with db.connect() as c:
        return c.execute("DELETE FROM books WHERE id = ?", (book_id,)).rowcount > 0


# ---- CSV ------------------------------------------------------------------------------

def to_csv():
    buf = io.StringIO()
    w = csv.DictWriter(buf, CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    w.writerows(search()["books"])
    return buf.getvalue()


def import_csv(text, commit=False):
    """Preview (or, with commit=True, add) the books in a CSV with a header row."""
    isbns, works = owned()
    existing = {(r["title"].casefold(), (r["authors"] or "").casefold()) for r in search()["books"]}
    result = {"new": [], "duplicates": [], "errors": []}
    for n, raw in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        row = {k: (raw.get(k) or "").strip() for k in IMPORT_COLUMNS}
        if not any(row.values()):
            continue
        if not row["title"]:
            result["errors"].append({"line": n, "why": "no title"})
            continue
        isbn = isbn13(row["isbn"]) if row["isbn"] else None
        if (isbn and isbn in isbns) or (row["title"].casefold(), row["authors"].casefold()) in existing:
            result["duplicates"].append(row)
            continue
        result["new"].append(row)
    if commit:
        for row in result["new"]:
            try:
                add({k: v for k, v in row.items() if v})
            except (Duplicate, ValueError) as e:
                result["errors"].append({"line": None, "why": f"{row['title']}: {e}"})
    return result
