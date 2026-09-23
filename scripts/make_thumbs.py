#!/usr/bin/env python3
"""
Build small WebP thumbnails for the localized Drive images and point gallery
tiles at them.

Why: gallery tiles render at roughly 200-400 CSS px wide but were loading the
full 1200px JPEG, which made service and case study pages 5-7 MB. Tiles now
show an 800px-wide WebP; the tile's href (what the lightbox opens) still points
at the full JPEG.

Usage (run from anywhere, after scripts/localize_drive_images.py):

    python3 scripts/make_thumbs.py

Behavior:
  - For every assets/images/drive/<id>.jpg, writes
    assets/images/drive/thumbs/<id>.webp if it is missing or older than the JPEG.
  - Rewrites the <img src> inside <a class="cs-tile"> links and
    <div class="cs-video-frame"> posters from drive/<id>.jpg to
    drive/thumbs/<id>.webp. Other uses (hero covers) keep the full JPEG.
  - Idempotent: re-running changes nothing once thumbnails and srcs are current.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageOps

REPO = Path(__file__).resolve().parent.parent
SRC_DIR = REPO / "assets" / "images" / "drive"
THUMB_DIR = SRC_DIR / "thumbs"
MAX_WIDTH = 800
QUALITY = 78

# An <img> directly inside a gallery tile link or a video poster frame, whose
# src points at a full-size localized Drive JPEG.
CONTAINER_IMG_RE = re.compile(
    r'(<(?:a class="cs-tile[^"]*"[^>]*|div class="cs-video-frame")>\s*<img\b[^>]*?\bsrc=")'
    r'((?:\.\./)*assets/images/drive/)([\w-]+)\.jpg(")'
)


def build_thumbs() -> int:
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    made = 0
    for src in sorted(SRC_DIR.glob("*.jpg")):
        dest = THUMB_DIR / f"{src.stem}.webp"
        if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
            continue
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            if im.width > MAX_WIDTH:
                im = im.resize((MAX_WIDTH, round(im.height * MAX_WIDTH / im.width)), Image.LANCZOS)
            im.save(dest, "WEBP", quality=QUALITY, method=6)
        made += 1
    return made


def rewrite_pages() -> int:
    changed = 0
    for page in REPO.glob("**/*.html"):
        if ".git" in page.parts:
            continue
        html = page.read_text(encoding="utf-8")

        def swap(m: re.Match) -> str:
            if not (THUMB_DIR / f"{m.group(3)}.webp").exists():
                return m.group(0)
            return f"{m.group(1)}{m.group(2)}thumbs/{m.group(3)}.webp{m.group(4)}"

        new = CONTAINER_IMG_RE.sub(swap, html)
        if new != html:
            page.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def main() -> int:
    made = build_thumbs()
    changed = rewrite_pages()
    print(f"made {made} thumbnails; rewrote tile srcs in {changed} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
