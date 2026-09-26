import datetime as dt
import pytest
from exlibris.core import books, openlibrary, series, stats

PAPERBACK = {"title": "The Talented Mr. Ripley", "publishers": ["Virago"], "publish_date": "2014-09-01",
             "covers": [15159585, -1], "works": [{"key": "/works/OL59434W"}], "physical_format": "paperback",
             "number_of_pages": 352, "series": ["Ripliad -- 1"], "key": "/books/OL59004869M"}


def test_edition_row_uses_the_editions_own_details():
    row = openlibrary.edition_row(PAPERBACK, {"authors": "Patricia Highsmith", "title": "The Talented Mr. Ripley", "year": 1955}, "9781850891840")
    assert row == {"title": "The Talented Mr. Ripley", "authors": "Patricia Highsmith", "year": 1955, "edition_year": 2014,
                   "isbn": "9781850891840", "publisher": "Virago", "cover_url": "/cover/15159585",
                   "ol_key": "/works/OL59434W", "edition_key": "/books/OL59004869M", "format": "Paperback",
                   "pages": 352, "series": "Ripliad", "series_index": 1}


class FakeHTTP:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, url, params=None):
        self.calls.append(url)
        for k, v in self.answers.items():
            if k in url:
                if isinstance(v, Exception):
                    raise v
                return v
        raise openlibrary.NotFound(url)


def test_year_is_first_published_edition_year_is_the_printing():
    row = openlibrary.edition_row(PAPERBACK, {"year": 1955}, "x")
    assert (row["year"], row["edition_year"]) == (1955, 2014)
    alone = openlibrary.edition_row(PAPERBACK, None, "x")          # no work details: fall back to the printing
    assert (alone["year"], alone["edition_year"]) == (2014, 2014)


def test_edition_is_cached():
    http = FakeHTTP({"/isbn/9781850891840": PAPERBACK})
    c = openlibrary.Client(http_get=http, sleep=lambda s: None)
    assert c.edition("9781850891840")["physical_format"] == "paperback"
    c.edition("9781850891840")
    assert len(http.calls) == 1


def test_unknown_isbn_is_none_and_errors_raise_unavailable():
    c = openlibrary.Client(http_get=FakeHTTP({}), sleep=lambda s: None)
    assert c.edition("9780000000002") is None
    down = openlibrary.Client(http_get=FakeHTTP({"/isbn/": OSError("down")}), sleep=lambda s: None)
    with pytest.raises(openlibrary.Unavailable):
        down.edition("9781850891840")


def test_requests_are_paced():
    t = [100.0]
    slept = []
    c = openlibrary.Client(http_get=FakeHTTP({"search.json": {"docs": []}}), clock=lambda: t[0],
                           sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)))
    c.search("a")
    c.search("b")
    assert slept and slept[-1] == pytest.approx(openlibrary.GAP_ANON, abs=0.01)


def test_search_rows_and_owned_marks():
    docs = {"docs": [{"key": "/works/A", "title": "A", "author_name": ["X", "Y"], "cover_i": 12, "first_publish_year": 1950}]}
    c = openlibrary.Client(http_get=FakeHTTP({"search.json": docs}), sleep=lambda s: None)
    books.add({"title": "A", "ol_key": "/works/A"})
    row = c.search("a")[0]
    assert row["authors"] == "X, Y" and row["cover_url"] == "/cover/12" and row["owned"] and row["isbn"] is None


def test_user_agent_names_the_project(monkeypatch):
    assert openlibrary.user_agent().startswith("ex-libris/")
    monkeypatch.setenv("EXLIBRIS_OPENLIBRARY_CONTACT", "me@example.org")
    assert "me@example.org" in openlibrary.user_agent() and openlibrary.gap() < openlibrary.GAP_ANON


@pytest.mark.parametrize("value, expected", [
    (["Series of Unfortunate Events (8)"], ("Series of Unfortunate Events", 8)),
    (["Court of Thorns and Roses #2"], ("Court of Thorns and Roses", 2)),
    (["A Court of Thorns and Roses Series 1"], ("A Court of Thorns and Roses", 1)),
    (["Discworld ; 3"], ("Discworld", 3)), (["(Discworld, #3)"], ("Discworld", 3)),
    (["Ripliad -- 1"], ("Ripliad", 1)), (["Maximum Ride"], ("Maximum Ride", None)),
    ("Discworld #2.5", ("Discworld", 2.5)),
    (["Collins Classics"], (None, None)), (["Virago modern classics -- 4"], (None, None)),
    (["The Penguin classics L210"], (None, None)), (["Collection Folio -- 3181"], (None, None)),
    ([], (None, None)), (None, (None, None)),
])
def test_series_parse(value, expected):
    assert series.parse(value) == expected


def test_series_gaps():
    assert series.gaps([1, 2, 5, 2.5, None]) == [3, 4] and series.gaps([]) == []


def _shelf():
    day = dt.date(2026, 9, 26)
    a = books.add({"title": "Dune", "authors": "Frank Herbert", "format": "Paperback", "year": 1965, "pages": 600,
                   "ol_key": "/works/D", "isbn": "9780441013593"})
    books.update(a["id"], {"genre": "Sci-fi & fantasy"})
    books.add({"title": "Dune", "authors": "Frank Herbert", "format": "Hardcover", "year": 1966, "pages": 620,
               "ol_key": "/works/D", "isbn": "9780399128967"})
    c = books.add({"title": "House Atreides", "authors": "Frank Herbert, Brian Herbert", "year": 1999, "pages": 400})
    books.update(c["id"], {"genre": "Sci-fi & fantasy"})
    e = books.add({"title": "Emma", "authors": "Jane Austen", "year": 1815, "pages": 474})
    books.update(e["id"], {"genre": "Fiction", "lent_to": "Sam"}, today=day)
    books.add({"title": "Mystery"})
    return day


def test_stats_on_a_mixed_shelf():
    day = _shelf()
    st = stats.stats(today=day)
    assert st["tiles"] == {"books": 5, "authors": 3, "pages": 2094, "lent_out": 1}
    assert st["by_genre"] == [["Sci-fi & fantasy", 2], ["Fiction", 1], ["No genre yet", 2]]
    assert st["top_authors"] == [["Frank Herbert", 3], ["Brian Herbert", 1], ["Jane Austen", 1]]
    assert st["by_decade"] == [["1810s", 1], ["1960s", 2], ["1990s", 1]]
    assert st["by_format"] == [["Hardcover", 1], ["Paperback", 1], ["Format unknown", 3]]
    assert st["added_per_month"][-1][1] == 5
    assert st["oddities"]["most_editions"] == {"title": "Dune", "n": 2}


def test_public_stats_and_highlights():
    day = _shelf()
    pub = stats.stats(today=day, public=True)
    assert set(pub["tiles"]) == {"books", "authors", "pages"} and "added_per_month" not in pub
    h = {x["key"]: x for x in stats.highlights(pub, today=day)}
    assert h["author"]["value"] == "Frank Herbert" and h["oldest"]["value"] == "Emma" and "211 years" in h["oldest"]["detail"]
    assert h["pages"]["value"] == "2,094"
    assert h["length"]["value"] == "14 cm"          # (2,094 pages + 300 assumed) x 0.05 mm + 5 covers x 3 mm = 135 mm


def test_empty_shelf_stats():
    st = stats.stats()
    assert st["tiles"]["books"] == 0 and st["by_genre"] == [] and stats.highlights(st) == []


def test_first_published_and_backfill():
    http = FakeHTTP({"search.json": {"docs": [{"key": "/works/OL59434W", "first_publish_year": 1955}]}})
    c = openlibrary.Client(http_get=http, sleep=lambda s: None)
    assert c.first_published("/works/OL59434W") == 1955
    c.first_published("/works/OL59434W")
    assert len(http.calls) == 1                                           # cached
    printed = books.add({"title": "The Talented Mr. Ripley", "ol_key": "/works/OL59434W", "year": 2015, "isbn": "9780349006963"})
    mine = books.add({"title": "Mine", "ol_key": "/works/OL59434W", "isbn": "9781850891840"})
    books.update(mine["id"], {"year": 1950})                              # typed by hand: left alone
    assert "1 first-published" in openlibrary.backfill_years(client_=c)
    got = books.get(printed["id"])
    assert (got["year"], got["edition_year"]) == (1955, 2015)
    assert books.get(mine["id"])["year"] == 1950


def test_implausible_first_published_years_are_ignored():
    http = FakeHTTP({"search.json": {"docs": [{"key": "/works/BBQ", "first_publish_year": 1600}]}})
    c = openlibrary.Client(http_get=http, sleep=lambda s: None)
    b = books.add({"title": "Smoke and Flames", "ol_key": "/works/BBQ", "year": 2019, "isbn": "9780441013593"})
    openlibrary.backfill_years(client_=c)
    assert books.get(b["id"])["year"] == 2019                   # 1600 for a 2019 cookbook is Open Library noise


def test_series_names_differing_by_a_leading_article_are_one_series():
    for n, name in ((1, "The Ripliad"), (2, "The Ripliad"), (3, "Ripliad"), (5, "ripliad")):
        b = books.add({"title": f"R{n}"})
        books.update(b["id"], {"series": name, "series_index": n})
    st = stats.stats()
    assert len(st["series"]) == 1 and st["series"][0]["missing"] == [4]
    assert {h["key"]: h for h in stats.highlights(st)}["series"]["value"] == "The Ripliad"
