import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_clean  # noqa: E402

# fake "personal" values, assembled at runtime so the repo itself stays clean
FAKE_EMAIL = "real.person" + "@" + "gmail.com"
FAKE_WORK = "real" + "@" + "company.co.uk"
FAKE_IP = ".".join(["86", "12", "34", "56"])


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
    r = _repo(tmp_path, {"README.md": "Contact: someone@example.org, server 192.0.2.20, localhost 127.0.0.1"})
    assert check_clean.check(r, words=["secretplace"]) == []


def test_denylisted_word_email_and_ip_are_caught(tmp_path):
    r = _repo(tmp_path, {"a.txt": "runs on SecretPlace", "b.txt": f"mail me at {FAKE_EMAIL}", "c.txt": f"host {FAKE_IP}"})
    found = " ".join(check_clean.check(r, words=["secretplace"]))
    assert "a.txt: contains a denylisted word" in found and FAKE_EMAIL in found and FAKE_IP in found
    assert "secretplace" not in found.lower().replace("contains a denylisted word", "")      # the word itself isn't echoed


def test_commit_author_is_checked(tmp_path):
    r = _repo(tmp_path, {"a.txt": "fine"})
    subprocess.run(["git", "-c", "user.name=Real Name", "-c", f"user.email={FAKE_WORK}", "commit", "-q", "--allow-empty",
                    "-m", "y"], cwd=r, check=True)
    assert any(FAKE_WORK in p for p in check_clean.check(r, words=["zzz"]))


def test_missing_denylist_fails_closed(tmp_path):
    r = _repo(tmp_path, {"a.txt": "fine"})
    assert check_clean.check(r, words=[])


def test_home_lan_addresses_and_commit_messages_are_checked(tmp_path):
    lan = ".".join(["192", "168", "1", "20"])
    r = _repo(tmp_path, {"a.txt": f"my server is {lan}"})
    assert any(lan in p for p in check_clean.check(r, words=["zzz"]))
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "deploy to secretplace"], cwd=r, check=True)
    assert any("commit or tag messages" in p for p in check_clean.check(r, words=["secretplace"]))
