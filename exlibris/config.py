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


def _on(name, default):
    return os.environ.get(name, default).strip().lower() not in ("off", "0", "false", "no")


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
    )
