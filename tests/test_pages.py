import re
import shutil
import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from exlibris.core import books
from exlibris.web import library

STATIC = Path(__file__).resolve().parent.parent / "exlibris" / "web" / "static"


@pytest.fixture
def c():
    return TestClient(library.app)


def test_every_page_renders(c):
    books.add({"title": "Dune", "authors": "Frank Herbert", "year": 1965, "pages": 600})
    for path in ("/", "/scan", "/stats", "/author?name=Frank%20Herbert", "/import"):
        r = c.get(path)
        assert r.status_code == 200 and "<nav" in r.text, path


def test_no_scripts_or_fonts_from_other_sites(c):
    books.add({"title": "Dune"})
    for path in ("/", "/scan", "/stats", "/import"):
        t = c.get(path).text
        assert not re.search(r'<script[^>]+src="https?://', t) and "fonts.googleapis" not in t, path
        assert "<script>" not in t, path                          # CSP script-src 'self': no inline scripts


def test_scanner_has_fallbacks(c):
    t = c.get("/scan").text
    assert 'id="isbn"' in t and 'data-mode="check"' in t and 'data-mode="add"' in t
    assert "needs a secure (https) address" in t and 'id="loc"' in t


def test_welcome_on_an_empty_library_then_gone(c):
    t = c.get("/").text
    assert "Welcome" in t and "don't expose port 8080" in t.lower().replace("’", "'")
    books.add({"title": "Dune"})
    assert "Welcome" not in c.get("/").text


def test_overdue_loans_are_flagged(c):
    b = books.add({"title": "Dune"})
    books.update(b["id"], {"lent_to": "Sam", "lent_on": "2020-01-01"})
    assert "lent to Sam" in c.get("/").text


def test_hostile_text_is_escaped(c):
    books.add({"title": "<script>alert(1)</script>", "authors": "<img src=x onerror=alert(1)>", "format": "<b>x</b>"})
    for path in ("/", "/stats", "/author?name=%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E"):
        t = c.get(path).text
        assert "<img src=x onerror" not in t and "<script>alert" not in t, path
    assert "encodeHTML" in (STATIC / "stats.js").read_text()


def test_static_files_are_served_and_js_parses(c):
    for f in ("app.css", "app.js", "browse.js", "library.js", "scan.js", "stats.js", "import.js", "vendor/zxing.min.js"):
        assert c.get(f"/static/{f}").status_code == 200, f
    if shutil.which("node"):
        for f in ("app.js", "browse.js", "library.js", "scan.js", "stats.js", "import.js"):
            subprocess.run(["node", "--check", str(STATIC / f)], check=True)


def test_home_page_has_scan_buttons(c):
    t = c.get("/").text
    assert 'class="btn primary" href="/scan?mode=add"' in t and 'href="/scan?mode=check"' in t
