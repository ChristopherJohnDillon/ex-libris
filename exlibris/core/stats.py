"""Numbers for the stats page. Worked out here; the optional AI may only quote them."""
import datetime as dt
from collections import Counter
from exlibris.core import books, series

UNKNOWN = ("No genre yet", "Format unknown")
PAGES_PER_HOUR = 40
MM_PER_PAGE, MM_PER_COVER, ASSUMED_PAGES = 0.05, 3, 300


def _ranked(counter, unknown=None):
    rows = sorted(([k, n] for k, n in counter.items() if k != unknown), key=lambda r: (-r[1], r[0]))
    return rows + ([[unknown, counter[unknown]]] if unknown in counter else [])


def _months(dates, today, span=24):
    c = Counter(d[:7] for d in dates if d)
    if not c:
        return []
    y, m, months = today.year, today.month, []
    for _ in range(span):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return [[k, c.get(k, 0)] for k in reversed(months) if k >= min(c)]


def stats(today=None, public=False):
    today = today or dt.date.today()
    rows = books.search()["books"]
    authors = Counter(a for r in rows for a in books.authors_of(r))
    tiles = {"books": len(rows), "authors": len(authors), "pages": sum(r.get("pages") or 0 for r in rows)}
    if not public:
        tiles["lent_out"] = sum(bool(r.get("lent_to")) for r in rows)
    works = Counter(r["ol_key"] for r in rows if r.get("ol_key"))
    top_work = works.most_common(1)[0] if works and works.most_common(1)[0][1] > 1 else None
    paged = [r for r in rows if r.get("pages")]
    dated = [r for r in rows if r.get("year")]
    pick = (lambda r: books.public_row(r)) if public else (lambda r: r)
    out = {
        "tiles": tiles,
        "by_genre": _ranked(Counter(r.get("genre") or "No genre yet" for r in rows), "No genre yet") if rows else [],
        "top_authors": _ranked(authors)[:10],
        "by_decade": sorted([[f"{d}s", n] for d, n in Counter(r["year"] // 10 * 10 for r in dated).items()]),
        "by_format": _ranked(Counter(r.get("format") or "Format unknown" for r in rows), "Format unknown") if rows else [],
        "oddities": {
            "longest": pick(max(paged, key=lambda r: r["pages"])) if paged else None,
            "oldest": pick(min(dated, key=lambda r: r["year"])) if dated else None,
            "most_editions": {"title": next(r["title"] for r in rows if r.get("ol_key") == top_work[0]), "n": top_work[1]}
            if top_work else None,
            "single_book_authors": sum(1 for n in authors.values() if n == 1),
        },
        "shelf_mm": round(sum((r.get("pages") or ASSUMED_PAGES) * MM_PER_PAGE + MM_PER_COVER for r in rows)),
        "series": [{"name": k, "have": v, "missing": series.gaps(v)} for k, v in _series(rows).items()],
    }
    if not public:
        out["added_per_month"] = _months([r.get("added_at") for r in rows], today)
    return out


def _series(rows):
    groups = {}
    for r in rows:
        if r.get("series"):
            groups.setdefault(r["series"], []).append(r.get("series_index"))
    return groups


def highlights(st, today=None):
    """The orange cards at the top of the stats page: [{key, label, value, detail}]."""
    today = today or dt.date.today()
    if not st["tiles"]["books"]:
        return []
    out = []
    add = lambda key, label, value, detail: out.append({"key": key, "label": label, "value": value, "detail": detail})
    plural = lambda n, word: f"{n:,} {word}{'s' if n != 1 else ''}"
    pages = st["tiles"]["pages"]
    if pages:
        add("pages", "Pages on the shelf", f"{pages:,}", f"about {round(pages / PAGES_PER_HOUR):,} hours of reading")
    mm = st["shelf_mm"]
    add("length", "Shelf length", f"{mm / 1000:.1f} m" if mm >= 1000 else f"{mm / 10:.0f} cm", "every book side by side")
    if st["top_authors"]:
        name, n = st["top_authors"][0]
        add("author", "Most collected", name, f"{plural(n, 'book')} on the shelf")
    genres = [g for g in st["by_genre"] if g[0] not in UNKNOWN]
    if genres:
        add("genre", "Top genre", genres[0][0], plural(genres[0][1], "book"))
    if st["by_decade"]:
        dec, n = max(st["by_decade"], key=lambda d: (d[1], d[0]))
        add("decade", "Favourite decade", dec, f"{plural(n, 'book')} first published then")
    o = st["oddities"]
    if o["oldest"]:
        add("oldest", "Oldest book", o["oldest"]["title"],
            f"first published {o['oldest']['year']} · {today.year - o['oldest']['year']} years ago")
    if o["longest"]:
        add("longest", "Longest", o["longest"]["title"], f"{o['longest']['pages']:,} pages")
    near = sorted((s for s in st["series"] if s["missing"]), key=lambda s: (len(s["missing"]), -len(s["have"])))
    if near:
        s = near[0]
        have = sorted({int(i) for i in s["have"] if isinstance(i, (int, float)) and float(i).is_integer()})
        add("series", "Nearly complete", s["name"], f"have {', '.join(map(str, have[:8]))} · missing "
            f"{', '.join(map(str, s['missing'][:6]))}")
    if o["single_book_authors"]:
        add("single", "One-book authors", f"{o['single_book_authors']:,}", "authors you have just one book by")
    return out
