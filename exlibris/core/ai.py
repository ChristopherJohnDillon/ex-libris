"""Optional AI, off unless EXLIBRIS_AI_URL points at an OpenAI-compatible server
(Ollama, LM Studio, llama.cpp, OpenAI, ...). It picks genres from Open Library
subjects and writes playful "fun facts" from numbers worked out in code."""
import json
import re
import httpx
from exlibris import config
from exlibris.core import books, db, openlibrary

GENRE_PROMPT = (
    "You sort books into genres. Choose exactly one genre from this list and reply with it exactly as written, "
    "nothing else: {genres}.\nRules: children's books (subjects such as 'Juvenile fiction') are Kids. Teen books are "
    "Young adult. Mystery, detective, suspense, psychological thrillers and crime novels are Crime & thriller. Science "
    "fiction and fantasy are Sci-fi & fantasy. Fiction is for novels that fit none of those.")
FUN_PROMPT = (
    "You are the witty librarian of a household's book collection. Using only the facts given (JSON), write 4 short, "
    "surprising or playful observations, each a single line starting with a bold phrase. Every number you state must "
    "appear in the facts. Then one line suggesting a book to look out for from a series gap. Plain markdown, warm, "
    "never snarky, no preamble.")
_THINK = re.compile(r"<think>.*?</think>", re.S)
_THINK_OPEN = re.compile(r"<think>.*", re.S)


def enabled():
    return bool(config.settings().ai_url)


def _endpoint():
    url = config.settings().ai_url
    return url + ("/chat/completions" if url.endswith("/v1") else "/v1/chat/completions")


def _post(payload):
    s = config.settings()
    headers = {"Authorization": f"Bearer {s.ai_key}"} if s.ai_key else {}
    r = httpx.post(_endpoint(), json={"model": s.ai_model or "default", **payload}, headers=headers, timeout=120)
    r.raise_for_status()
    return r.json()


def _text(msg):
    text = msg["choices"][0]["message"].get("content") or ""
    return _THINK_OPEN.sub("", _THINK.sub("", text)).strip()


def choose_genre(title, authors, subjects, post=None):
    """One of books.GENRES; 'Other' for a clear answer off the list; None if nothing usable."""
    try:
        user = f"Title: {title}\nAuthors: {authors or 'unknown'}\nSubjects: {'; '.join(subjects[:40]) or 'none listed'}\n/no_think"
        text = _text((post or _post)({"max_tokens": 600, "temperature": 0, "messages": [
            {"role": "system", "content": GENRE_PROMPT.format(genres=", ".join(books.GENRES))},
            {"role": "user", "content": user}]}))
    except Exception:
        return None
    text = text.strip("\"'`*.").strip()
    if not text:
        return None
    fold = {g.casefold(): g for g in books.GENRES}
    if text.casefold() in fold:
        return fold[text.casefold()]
    inside = [g for g in books.GENRES if g.casefold() in text.casefold()]
    return max(inside, key=len) if inside else "Other"


def fill_genres(limit=40, post=None, work=None):
    if not enabled() and post is None:
        return "AI not configured"
    work = work or openlibrary.client().work
    with db.connect() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT id, title, authors, ol_key, subjects FROM books WHERE genre IS NULL AND ol_key IS NOT NULL "
            "AND coalesce(genre_source, 'auto') = 'auto' ORDER BY id LIMIT ?", (limit,))]
    done = 0
    for r in rows:
        try:
            subjects = json.loads(r["subjects"]) if r["subjects"] else [s for s in (work(r["ol_key"]) or {}).get("subjects") or []
                                                                        if isinstance(s, str)]
        except (openlibrary.Unavailable, ValueError):
            continue
        genre = choose_genre(r["title"], r["authors"], subjects, post=post)
        books.set_fields(r["id"], subjects=json.dumps(subjects))
        if genre:
            with db.connect() as c:
                c.execute("UPDATE books SET genre = ?, genre_source = 'auto' WHERE id = ? AND genre IS NULL "
                          "AND coalesce(genre_source, 'auto') = 'auto'", (genre, r["id"]))
            done += 1
    return f"{done} genre{'s' if done != 1 else ''} set"


def fun_facts(facts, post=None):
    try:
        text = _text((post or _post)({"max_tokens": 500, "temperature": 0.4, "messages": [
            {"role": "system", "content": FUN_PROMPT}, {"role": "user", "content": json.dumps(facts, default=str)}]}))
    except Exception:
        return None
    return text or None
