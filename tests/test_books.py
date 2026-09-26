import datetime as dt
import pytest
from exlibris.core import books


def test_editions_are_separate_copies():
    books.add({"title": "The Talented Mr. Ripley", "ol_key": "/works/W1", "isbn": "9780349006963", "format": "Hardcover"})
    books.add({"title": "The Talented Mr. Ripley", "ol_key": "/works/W1", "isbn": "9781850891840", "format": "Paperback"})
    with pytest.raises(books.Duplicate):
        books.add({"title": "again", "isbn": "9781850891840"})
    books.add({"title": "Dune", "ol_key": "/works/D"})
    with pytest.raises(books.Duplicate):                    # no ISBN: the edition is unknown, one per work
        books.add({"title": "Dune", "ol_key": "/works/D"})
    assert books.search()["total"] == 3


def test_update_validates_and_normalises():
    b = books.add({"title": "Dune"})
    with pytest.raises(ValueError):
        books.update(b["id"], {"year": "c. 1965"})
    with pytest.raises(ValueError):
        books.update(b["id"], {"title": " "})
    with pytest.raises(ValueError):
        books.update(b["id"], {"cover_url": "https://evil"})
    got = books.update(b["id"], {"year": "1965", "isbn": "0-3490-0696-2", "format": "paperback", "notes": "  signed "})
    assert (got["year"], got["isbn"], got["format"], got["notes"]) == (1965, "9780349006963", "Paperback", "signed")
    assert books.update(999, {"notes": "x"}) is None


def test_isbn_clash_names_the_other_book():
    books.add({"title": "Dune", "isbn": "9780441013593"})
    e = books.add({"title": "Emma"})
    with pytest.raises(books.Duplicate, match="Dune"):
        books.update(e["id"], {"isbn": "9780441013593"})


def test_genre_hand_set_is_marked_manual():
    b = books.add({"title": "Dune"})
    assert books.update(b["id"], {"genre": "Sci-fi & fantasy"})["genre_source"] == "manual"
    assert books.update(b["id"], {"genre": ""})["genre_source"] is None


def test_lending_dates():
    day = dt.date(2026, 9, 26)
    b = books.add({"title": "Dune"})
    assert books.update(b["id"], {"lent_to": "Sam"}, today=day)["lent_on"] == "2026-09-26"
    assert books.update(b["id"], {"lent_to": ""}, today=day)["lent_on"] is None


def test_search_prefix_order_and_public_mode():
    books.add({"title": "The Talented Mr. Ripley", "authors": "Patricia Highsmith", "notes": "signed first edition"})
    books.add({"title": "Emma", "authors": "Jane Austen"})
    assert [b["title"] for b in books.search()["books"]] == ["The Talented Mr. Ripley", "Emma"]       # order added
    assert books.search("tal rip")["books"][0]["title"] == "The Talented Mr. Ripley"
    assert books.search("signed")["books"] and books.search("signed", public=True)["books"] == []
    assert books.search('"; DROP TABLE books; --')["total"] == 2                            # no injection


def test_public_row_has_only_public_fields():
    b = books.add({"title": "Dune", "notes": "secret", "location": "Den", "cover_url": "/cover/42"})
    books.update(b["id"], {"lent_to": "Sam"})
    row = books.public_row(books.get(b["id"]))
    assert set(row) == set(books.PUBLIC_FIELDS) and row["cover_url"] == "/cover/42"


@pytest.mark.parametrize("text, expected", [
    ("Frank Herbert, Brian Herbert", ["Frank Herbert", "Brian Herbert"]),
    ("Walter M. Miller, Jr.", ["Walter M. Miller, Jr."]),
    ("Martin Luther King, Jr., Coretta Scott King", ["Martin Luther King, Jr.", "Coretta Scott King"]),
    (None, []), (" Solo ", ["Solo"]),
])
def test_authors_of(text, expected):
    assert books.authors_of({"authors": text}) == expected


def test_isbn_helpers():
    assert books.isbn13("0-3490-0696-0") is None or books.isbn13("0-3490-0696-0").startswith("978")
    assert books.isbn13("978-0-3490-0696-3") == "9780349006963"
    assert books.is_isbn13("9780349006963") and not books.is_isbn13("9780747532698")


def test_csv_round_trip_and_import_preview():
    books.add({"title": "Dune", "authors": "Frank Herbert", "isbn": "9780441013593"})
    text = books.to_csv()
    assert text.splitlines()[0].startswith("title,authors,year,isbn")
    incoming = text + "Emma,Jane Austen,1815,,,,,,,,,\nNo title row,,,,,,,,,,,\n,,,,,,,,,,,\n"
    preview = books.import_csv(incoming)
    assert [r["title"] for r in preview["new"]] == ["Emma", "No title row"]
    assert [r["title"] for r in preview["duplicates"]] == ["Dune"]
    assert books.search()["total"] == 1                                      # a preview writes nothing
    books.import_csv(incoming, commit=True)
    assert books.search()["total"] == 3


def test_title_only_books_everywhere():
    books.add({"title": "Mystery"})
    assert books.to_csv().count("Mystery") == 1 and books.search("myst")["total"] == 1
    assert books.public_row(books.search()["books"][0])["authors"] is None


def test_locations_and_overdue_loans():
    day = dt.date(2026, 9, 26)
    a = books.add({"title": "A", "location": "Lounge"})
    books.add({"title": "B", "location": "Lounge"})
    books.add({"title": "C", "location": " "})
    books.update(a["id"], {"lent_to": "Sam", "lent_on": "2026-07-01"})
    assert books.locations() == [{"name": "Lounge", "n": 2}]
    assert [r["title"] for r in books.overdue_loans(day)] == ["A"]


def test_edition_year_is_kept_editable_and_exported():
    b = books.add({"title": "The Talented Mr. Ripley", "year": 1955, "edition_year": 2015})
    assert (b["year"], b["edition_year"]) == (1955, 2015)
    assert books.update(b["id"], {"edition_year": "1999"})["edition_year"] == 1999
    assert "edition_year" in books.to_csv().splitlines()[0] and "edition_year" in books.PUBLIC_FIELDS
