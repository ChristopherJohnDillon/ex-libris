import pytest


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    # every test gets its own empty data folder and no outside services
    monkeypatch.setenv("EXLIBRIS_DATA", str(tmp_path / "data"))
    for k in ("EXLIBRIS_AI_URL", "EXLIBRIS_AI_KEY", "EXLIBRIS_OPENLIBRARY_CONTACT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EXLIBRIS_GOOGLE_BOOKS", "off")
