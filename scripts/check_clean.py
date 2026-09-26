#!/usr/bin/env python3
"""Fail if anything identifying the maintainer's own setup is in the repo.

Checks every tracked file and every commit's author/committer against:
  * a private denylist (never committed): the file named by EXLIBRIS_DENYLIST,
    or the text in EXLIBRIS_DENYLIST_TEXT (how CI gets it, from a secret);
  * generic patterns: email addresses other than allowed no-reply/example ones,
    and IPv4 addresses other than loopback and the documentation ranges.
Commit authors, commit messages and tag messages are checked as well as files.
Exit 0 when clean, 1 with a report otherwise.
"""
import os
import re
import subprocess
import sys

ALLOWED_EMAILS = re.compile(r"(@users\.noreply\.github\.com|@example\.(com|org|net))$", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# loopback, "all interfaces" and the documentation ranges only (RFC 5737): a real home LAN address is flagged
ALLOWED_IP = re.compile(r"^(127\.0\.0\.1|0\.0\.0\.0|192\.0\.2\.\d+|198\.51\.100\.\d+|203\.0\.113\.\d+)$")


def denylist():
    text = os.environ.get("EXLIBRIS_DENYLIST_TEXT", "")
    path = os.environ.get("EXLIBRIS_DENYLIST", os.path.expanduser("~/.config/ex-libris/denylist.txt"))
    if not text and os.path.exists(path):
        text = open(path, encoding="utf-8").read()
    return [w.strip().lower() for w in text.splitlines() if w.strip() and not w.lstrip().startswith("#")]


def tracked_files(root):
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    return [f for f in out.decode().split("\0") if f]


def authors(root):
    out = subprocess.run(["git", "log", "--all", "--format=%an <%ae>%n%cn <%ce>"], cwd=root,
                         capture_output=True, text=True).stdout
    return sorted(set(out.splitlines()))


def messages(root):
    commits = subprocess.run(["git", "log", "--all", "--format=%B"], cwd=root, capture_output=True, text=True).stdout
    tags = subprocess.run(["git", "tag", "-l", "--format=%(contents)"], cwd=root, capture_output=True, text=True).stdout
    return commits + "\n" + tags


def scan_text(label, text, words):
    problems = []
    low = text.lower()
    for w in words:
        if w in low:
            problems.append(f"{label}: contains a denylisted word")
    for m in EMAIL.finditer(text):
        if not ALLOWED_EMAILS.search(m.group(0)):
            problems.append(f"{label}: email address {m.group(0)!r}")
    for m in IPV4.finditer(text):
        if not ALLOWED_IP.match(m.group(0)) and all(0 <= int(p) <= 255 for p in m.group(0).split(".")):
            problems.append(f"{label}: IP address {m.group(0)!r}")
    return problems


def check(root, words=None):
    words = denylist() if words is None else words
    problems = []
    if not words:
        problems.append("no denylist found: set EXLIBRIS_DENYLIST or EXLIBRIS_DENYLIST_TEXT")
    for f in tracked_files(root):
        try:
            text = open(os.path.join(root, f), encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue                                   # binary files (images, fonts)
        problems += scan_text(f, text, words)
        problems += scan_text(f"(file name) {f}", f, words)
    for a in authors(root):
        problems += scan_text(f"(commit author) {a.split('<')[0].strip()}", a, words)
    problems += scan_text("(commit or tag messages)", messages(root), words)
    return problems


if __name__ == "__main__":
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip() or "."
    found = check(root)
    if found:
        print("NOT CLEAN:\n  " + "\n  ".join(sorted(set(found))))   # denylisted words are never echoed
        sys.exit(1)
    print("clean")
