"""Settings, all from environment variables and all optional."""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    title: str
    public: bool
    ol_contact: str
    ai_url: str
    ai_model: str
    ai_key: str
    google_books: bool
    identity_header: str
    people: dict


def _on(name, default):
    return os.environ.get(name, default).strip().lower() not in ("off", "0", "false", "no")


def _people(text):
    """EXLIBRIS_PEOPLE="Alex=alex@example.com; Sam=sam@example.com,sam@example.org" -> {email: name}"""
    out = {}
    for part in (text or "").split(";"):
        name, _, emails = part.partition("=")
        for e in emails.split(","):
            if name.strip() and e.strip():
                out[e.strip().lower()] = name.strip()
    return out


def settings():
    env = os.environ.get
    return Settings(
        data_dir=Path(env("EXLIBRIS_DATA", "/data")),
        title=env("EXLIBRIS_TITLE", "").strip() or "Our books",
        public=_on("EXLIBRIS_PUBLIC", "on"),
        ol_contact=env("EXLIBRIS_OPENLIBRARY_CONTACT", "").strip(),
        ai_url=env("EXLIBRIS_AI_URL", "").strip().rstrip("/"),
        ai_model=env("EXLIBRIS_AI_MODEL", "").strip(),
        ai_key=env("EXLIBRIS_AI_KEY", "").strip(),
        google_books=_on("EXLIBRIS_GOOGLE_BOOKS", "on"),
        # who's using the library, for per-person wishlists: the email a login proxy in
        # front of it passes on (Cloudflare Access by default); "off" = one shared wishlist
        identity_header=env("EXLIBRIS_IDENTITY_HEADER", "Cf-Access-Authenticated-User-Email").strip(),
        people=_people(env("EXLIBRIS_PEOPLE", "")),
    )
