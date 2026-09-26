import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_clean  # noqa: E402


def _repo(tmp_path, files):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Ex Libris contributors"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "ex-libris@users.noreply.github.com"], cwd=tmp_path, check=True)
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=tmp_path, check=True)
    return tmp_path


def test_clean_repo_passes(tmp_path):
    r = _repo(tmp_path, {"README.md": "Contact: someone@example.org, server 192.168.1.20, localhost 127.0.0.1"})
    assert check_clean.check(r, words=["secretplace"]) == []


def test_denylisted_word_email_and_ip_are_caught(tmp_path):
    r = _repo(tmp_path, {"a.txt": "runs on SecretPlace", "b.txt": "mail me at real.person@gmail.com", "c.txt": "host 86.12.34.56"})
    found = " ".join(check_clean.check(r, words=["secretplace"]))
    assert "a.txt: contains a denylisted word" in found and "real.person@gmail.com" in found and "86.12.34.56" in found
    assert "secretplace" not in found.lower().replace("contains a denylisted word", "")      # the word itself isn't echoed


def test_commit_author_is_checked(tmp_path):
    r = _repo(tmp_path, {"a.txt": "fine"})
    subprocess.run(["git", "-c", "user.name=Real Name", "-c", "user.email=real@company.co.uk", "commit", "-q", "--allow-empty",
                    "-m", "y"], cwd=r, check=True)
    assert any("real@company.co.uk" in p for p in check_clean.check(r, words=["zzz"]))


def test_missing_denylist_fails_closed(tmp_path):
    r = _repo(tmp_path, {"a.txt": "fine"})
    assert check_clean.check(r, words=[])
