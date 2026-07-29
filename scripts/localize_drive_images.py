#!/usr/bin/env python3
"""
Download Google Drive-hotlinked gallery images into the repo and rewrite
<img> tags to serve them locally.

Why: ~190 images across the site are hotlinked from
drive.google.com/thumbnail. Those URLs redirect, carry no cache headers we
control, and Google can rate-limit or break them at any time. Serving the
files from the repo makes the galleries fast and reliable.

Usage (run from the repo root, needs normal internet access):

    python3 scripts/localize_drive_images.py          # download + rewrite
    python3 scripts/localize_drive_images.py --dry    # report only

Behavior:
  - Finds every <img src="https://drive.google.com/thumbnail?id=...&sz=wNNN">
    in the site's HTML files (admin/ excluded).
  - Downloads each unique file id once, at the largest size referenced
    (minimum w800), to assets/images/drive/<id>.jpg. Already-downloaded
    ids are skipped, so re-runs are cheap and idempotent.
  - Rewrites the <img> srcs to the local path (correct relative prefix per
    page depth). Video <iframe> previews are left on Drive — they need the
    Drive player.

Note: if you re-run scripts/build_galleries.py it will regenerate gallery
bodies with Drive thumbnail URLs — run this script again afterwards.
"""

from __future__ import annotations

import re
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "assets" / "images" / "drive"
THUMB_RE = re.compile(
    r'https://drive\.google\.com/thumbnail\?id=([\w-]+)(?:&(?:amp;)?sz=w(\d+))?'
)

def site_pages():
    for p in REPO.glob("**/*.html"):
        rel = p.relative_to(REPO)
        if rel.parts[0] in {"admin", ".git"}:
            continue
        yield p

def main() -> int:
    dry = "--dry" in sys.argv
    # 1. inventory: id -> max requested width
    wanted: dict[str, int] = {}
    for page in site_pages():
        for fid, w in THUMB_RE.findall(page.read_text()):
            width = int(w) if w else 800
            wanted[fid] = max(wanted.get(fid, 0), width, 800)
    print(f"{len(wanted)} unique Drive images referenced")
    if dry:
        return 0

    # 2. download
    OUT.mkdir(parents=True, exist_ok=True)
    failed: set[str] = set()
    for i, (fid, width) in enumerate(sorted(wanted.items()), 1):
        dest = OUT / f"{fid}.jpg"
        if dest.exists() and dest.stat().st_size > 0:
            continue
        url = f"https://drive.google.com/thumbnail?id={fid}&sz=w{width}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            if not data or data[:5] == b"<!DOC":
                raise ValueError("got HTML instead of image (file not public?)")
            dest.write_bytes(data)
            print(f"[{i}/{len(wanted)}] {fid} ({len(data)//1024}KB)")
            time.sleep(0.2)  # be polite; Drive rate-limits bursts
        except Exception as e:
            failed.add(fid)
            print(f"[{i}/{len(wanted)}] {fid} FAILED: {e}", file=sys.stderr)

    # 3. rewrite srcs (only for ids that downloaded successfully);
    #    img tags only — iframe video previews stay on Drive.
    img_re = re.compile(
        r'(<img[^>]*?src=")https://drive\.google\.com/thumbnail\?id=([\w-]+)[^"]*(")'
    )
    changed = 0
    for page in site_pages():
        html = page.read_text()
        depth = len(page.relative_to(REPO).parts) - 1
        prefix = "../" * depth

        def rewrite(m):
            fid = m.group(2)
            if fid in failed:
                return m.group(0)
            return f"{m.group(1)}{prefix}assets/images/drive/{fid}.jpg{m.group(3)}"

        new = img_re.sub(rewrite, html)
        if new != html:
            page.write_text(new)
            changed += 1
    print(f"rewrote srcs in {changed} pages; {len(failed)} downloads failed")
    if failed:
        print("failed ids left hotlinked:", ", ".join(sorted(failed)))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
