import pytest
from fastapi.testclient import TestClient
from exlibris.core import books, stats, wishlist
from exlibris.web import library, public

J = {"Content-Type": "application/json"}
WHO = "Cf-Access-Authenticated-User-Email"
PIRANESI = "9781526622242"


@pytest.fixture
def c():
    return TestClient(library.app)


def as_(email):
    return {WHO: email}


class FakeClient:
    def __init__(self, ol_key="/works/OL2W"):
        self.ol_key = ol_key

    def edition(self, isbn):
        return {"title": "Piranesi", "works": [{"key": self.ol_key}]}

    def search(self, q):
        return [{"title": "Piranesi", "authors": "Susanna Clarke", "isbn": None, "ol_key": self.ol_key, "owned": False},
                {"title": "Jonathan Strange", "authors": "Susanna Clarke", "isbn": None, "ol_key": "/works/OL3W", "owned": False}]

    def first_published(self, key):
        return 2020

    def author_works(self, name):
        return [{"title": "Piranesi", "year": 2020, "ol_key": self.ol_key, "owned": False}]


def test_shared_list_without_a_login_proxy(c):
    r = c.post("/api/wishlist", json={"title": "Piranesi", "isbn": "1-5266-2224-6", "notes": "from Alex", "cover_url": "https://cdn.example.com/a.jpg"})
    assert r.status_code == 201
    w = r.json()
    assert (w["isbn"], w["owner"], w["cover_url"], w["notes"]) == (PIRANESI, "", None, "from Alex")
    assert c.post("/api/wishlist", json={"title": "again", "isbn": PIRANESI}).status_code == 409
    assert c.patch(f"/api/wishlist/{w['id']}", json={"notes": " £9.99 at the market "}).json()["notes"] == "£9.99 at the market"
    assert c.patch(f"/api/wishlist/{w['id']}", json={"location": "x"}).status_code == 422
    assert [x["title"] for x in c.get("/api/wishlist").json()] == ["Piranesi"]
    assert c.delete(f"/api/wishlist/{w['id']}", headers=J).status_code == 204
    assert c.delete(f"/api/wishlist/{w['id']}", headers=J).status_code == 404
    page = c.get("/wishlist").text
    assert "Everyone shares this list" in page and 'id="people"' not in page


def test_writes_need_json_and_same_origin(c):
    assert c.post("/api/wishlist", data={"title": "x"}).status_code == 415
    assert c.post("/api/wishlist", json={"title": "x"}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_per_person_when_cloudflare_access_says_who(c, monkeypatch):
    monkeypatch.setenv("EXLIBRIS_PEOPLE", "Alex=Alex@Example.com; Robin=robin@example.com,robin@example.org")
    assert c.post("/api/wishlist", json={"title": "Piranesi", "isbn": PIRANESI}, headers=as_("alex@example.com")).json()["owner"] == "Alex"
    # the same book on another person's list is fine; a second email is the same person
    assert c.post("/api/wishlist", json={"title": "Piranesi", "isbn": PIRANESI}, headers=as_("robin@example.org")).json()["owner"] == "Robin"
    assert c.post("/api/wishlist", json={"title": "Piranesi", "isbn": PIRANESI}, headers=as_("robin@example.com")).status_code == 409
    # unnamed emails get their own list, under the email
    assert c.post("/api/wishlist", json={"title": "Dune"}, headers=as_("sam@example.com")).json()["owner"] == "sam@example.com"
    assert [w["owner"] for w in c.get("/api/wishlist", headers=as_("alex@example.com")).json()] == ["Alex"]
    assert [w["owner"] for w in c.get("/api/wishlist?who=Robin", headers=as_("alex@example.com")).json()] == ["Robin"]
    assert len(c.get("/api/wishlist?who=*", headers=as_("alex@example.com")).json()) == 3
    # a present idea for someone else
    assert c.post("/api/wishlist", json={"title": "Scarf book", "owner": "Robin"}, headers=as_("alex@example.com")).json()["owner"] == "Robin"
    page = c.get("/wishlist", headers=as_("alex@example.com")).text
    assert 'id="people"' in page and "Everyone shares" not in page


def test_identity_header_can_be_changed_or_turned_off(c, monkeypatch):
    monkeypatch.setenv("EXLIBRIS_IDENTITY_HEADER", "X-Forwarded-Email")
    assert c.post("/api/wishlist", json={"title": "A"}, headers={"X-Forwarded-Email": "a@example.net"}).json()["owner"] == "a@example.net"
    monkeypatch.setenv("EXLIBRIS_IDENTITY_HEADER", "off")
    assert c.post("/api/wishlist", json={"title": "B", "owner": "Someone"}, headers=as_("a@example.net")).json()["owner"] == ""


def test_an_owned_edition_cant_be_wished_for(c):
    books.add({"title": "Piranesi", "isbn": PIRANESI})
    r = c.post("/api/wishlist", json={"title": "Piranesi", "isbn": PIRANESI})
    assert r.status_code == 409 and "shelf" in r.json()["detail"]


def test_got_it_moves_it_onto_the_shelf(c):
    w = wishlist.add({"title": "Piranesi", "isbn": PIRANESI, "notes": "from Alex", "ol_key": "/works/OL2W", "cover_url": "/cover/7"})
    r = c.post(f"/api/wishlist/{w['id']}/got", json={"location": "Lounge"})
    b = r.json()["book"]
    assert r.json()["already"] is False
    assert (b["title"], b["isbn"], b["notes"], b["location"], b["cover_url"]) == ("Piranesi", PIRANESI, "from Alex", "Lounge", "/cover/7")
    assert wishlist.list_wishes() == []
    assert c.post(f"/api/wishlist/{w['id']}/got", json={}).status_code == 404


def test_got_it_when_its_already_there(c):
    w = wishlist.add({"title": "Dune", "ol_key": "/works/OL1W"})
    have = books.add({"title": "Dune", "ol_key": "/works/OL1W"})
    r = c.post(f"/api/wishlist/{w['id']}/got", json={}).json()
    assert r["already"] is True and r["book"]["id"] == have["id"]
    assert wishlist.list_wishes() == []


def test_adding_a_wished_book_ticks_it_off_for_everyone(c):
    wishlist.add({"title": "Piranesi", "isbn": PIRANESI, "notes": "from Alex"}, "Robin")
    wishlist.add({"title": "Piranesi", "isbn": PIRANESI, "notes": "from Alex"}, "Alex")
    wishlist.add({"title": "Dune, any edition", "ol_key": "/works/OL1W"})
    wishlist.add({"title": "Dune hardback", "ol_key": "/works/OL1W", "isbn": "9780399128967"})
    r = c.post("/api/books", json={"title": "Piranesi", "isbn": PIRANESI}).json()
    assert r["wish_done"] == ["Piranesi", "Piranesi"] and books.get(r["id"])["notes"] == "from Alex"
    r = c.post("/api/books", json={"title": "Dune", "isbn": "9780441013593", "ol_key": "/works/OL1W"}).json()
    assert r["wish_done"] == ["Dune, any edition"]
    assert [w["title"] for w in wishlist.list_wishes()] == ["Dune hardback"]


def test_lookups_and_scans_know_about_wishes(c, monkeypatch):
    monkeypatch.setattr(library, "ol", lambda: FakeClient())
    wishlist.add({"title": "Piranesi", "ol_key": "/works/OL2W", "notes": "from Alex"}, "alex@example.com")
    me = as_("alex@example.com")
    assert [r["wished"] for r in c.get("/api/lookup?q=clarke", headers=me).json()] == [True, False]
    assert [r["wished"] for r in c.get("/api/lookup?q=clarke", headers=as_("sam@example.com")).json()] == [False, False]
    assert c.get("/api/author_works?name=Susanna Clarke", headers=me).json()[0]["wished"] is True
    w = c.get(f"/api/own/{PIRANESI}", headers=as_("sam@example.com")).json()["wish"]
    assert (w["notes"], w["owner"], w["mine"]) == ("from Alex", "alex@example.com", False)
    assert c.get(f"/api/own/{PIRANESI}", headers=me).json()["wish"]["mine"] is True


def test_wishes_stay_off_the_shelf_stats_csv_and_public_view(c):
    wishlist.add({"title": "Secret present", "isbn": PIRANESI, "notes": "for Sam's birthday", "cover_url": "/cover/9"})
    assert c.get("/api/books").json()["total"] == 0
    assert stats.stats()["tiles"]["books"] == 0
    assert "Secret present" not in books.to_csv()
    pub = TestClient(public.app)
    assert "Secret present" not in pub.get("/api/books").text
    assert pub.get("/wishlist").status_code == 404
    assert pub.get("/api/wishlist").status_code == 404
    assert pub.get("/cover/9").status_code == 404


def test_wishlist_covers_are_served_to_the_library(c, monkeypatch):
    wishlist.add({"title": "Piranesi", "cover_url": "/cover/9"})
    monkeypatch.setattr(library, "_fetch_cover", lambda cid: None)
    calls = []
    monkeypatch.setattr(library, "_fetch_cover", lambda cid: calls.append(cid))
    c.get("/cover/9")
    c.get("/cover/10")
    assert calls == [9]                     # asked for the wished book's cover, not for any id


def test_pages_have_the_wishlist(c):
    assert 'href="/wishlist"' in c.get("/").text
    assert 'data-mode="wish"' in c.get("/scan").text
