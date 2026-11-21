"""Download every book cover (img_url) into static/img/covers/ and report books still missing one.

Usage (from the project root):
    python scripts/download_covers.py            # download missing covers, then report
    python scripts/download_covers.py --check    # only report books without a local cover
"""
import mimetypes
import os
import re
import unicodedata
import sqlite3
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "instance", "books.db")
COVERS_DIR = os.path.join(ROOT, "static", "img", "covers")
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def slugify(text):
    # Keeps letters/digits of any script (e.g. Bengali) and combining marks; everything else
    # (spaces, punctuation, apostrophes, zero-width joiners) becomes a single "-".
    text = unicodedata.normalize('NFC', (text or '').lower()).replace("'", '').replace('’', '')
    kept = ''.join(ch if unicodedata.category(ch)[0] in 'LMN' else '-' for ch in text)
    return re.sub(r'-+', '-', kept).strip('-')


def local_covers():
    os.makedirs(COVERS_DIR, exist_ok=True)
    return {slugify(os.path.splitext(f)[0]) for f in os.listdir(COVERS_DIR)
            if os.path.splitext(f)[1].lower() in EXTS}


def main():
    check_only = "--check" in sys.argv
    con = sqlite3.connect(DB_PATH)
    books = con.execute("SELECT title, img_url FROM book ORDER BY id").fetchall()
    have = local_covers()

    if not check_only:
        for title, url in books:
            slug = slugify(title)
            if slug in have or not url:
                continue
            try:
                r = requests.get(url, timeout=20)
                r.raise_for_status()
                ext = os.path.splitext(url.split("?")[0])[1].lower()
                if ext not in EXTS:
                    ext = mimetypes.guess_extension(r.headers.get("content-type", "").split(";")[0]) or ".jpg"
                with open(os.path.join(COVERS_DIR, slug + ext), "wb") as f:
                    f.write(r.content)
                have.add(slug)
                print(f"downloaded: {title}")
            except Exception as e:
                print(f"FAILED:     {title} ({e})")

    missing = [t for t, _ in books if slugify(t) not in have]
    print(f"\n{len(books) - len(missing)}/{len(books)} books have a local cover.")
    if missing:
        print("Missing a cover (save the image as the title, e.g. 'Title.jpg', in static/img/covers/):")
        for t in missing:
            print(f"  - {t}")


if __name__ == "__main__":
    main()
