#!/usr/bin/env python3
"""
Export specific Drive files as site images, driven by scripts/drive_export.json:

  {"exports": [
     {"id": "<drive id>", "t": 6.0, "max": 1600},          # video: the frame at t seconds
     {"id": "<drive id>", "max": 1600},                    # image: Drive's own rendition
     {"id": "<drive id>", "t": 2, "dest": "assets/images/covers/x-1600.jpg"}
  ]}

Each export is written to assets/images/drive/<id>.jpg unless `dest` is given
(the site's localized-Drive convention; scripts/make_thumbs.py then builds the
WebP tile). `max` caps the long edge (default 1600). Existing files are
overwritten only when `force` is true on the item, so re-runs are cheap.

Videos are read straight from Drive with ffmpeg over HTTP (range requests),
so nothing is downloaded in full.

Environment:
  DRIVE_SA_KEY  service account JSON (same secret as the gallery build)
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_galleries import API_BASE, build_session  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "assets" / "images" / "drive"
CONFIG = REPO / "scripts" / "drive_export.json"


def meta(session, file_id: str) -> dict:
    r = session.get(f"{API_BASE}/{file_id}", params={"fields": "id,name,mimeType,size,thumbnailLink", "supportsAllDrives": "true"}, timeout=30)
    r.raise_for_status()
    return r.json()


def video_frame(session, file_id: str, t: float, max_edge: int) -> Image.Image:
    url = f"{API_BASE}/{file_id}?alt=media&supportsAllDrives=true"
    token = session.credentials.token
    if not token:
        from google.auth.transport.requests import Request
        session.credentials.refresh(Request())
        token = session.credentials.token
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "frame.png"
        cmd = ["ffmpeg", "-loglevel", "error", "-y", "-headers", f"Authorization: Bearer {token}\r\n",
               "-ss", str(t), "-i", url, "-frames:v", "1", "-vf", f"scale='min({max_edge},iw)':-2", str(dest)]
        subprocess.run(cmd, check=True, timeout=600)
        return Image.open(dest).convert("RGB")


def image_rendition(session, file_id: str, max_edge: int) -> Image.Image:
    r = session.get(f"{API_BASE}/{file_id}?alt=media&supportsAllDrives=true", timeout=120)
    r.raise_for_status()
    im = Image.open(io.BytesIO(r.content))
    try:
        from PIL import ImageOps
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass
    im = im.convert("RGB")
    im.thumbnail((max_edge, max_edge))
    return im


def main() -> int:
    cfg = json.loads(CONFIG.read_text())
    session = build_session()
    done = 0
    for item in cfg.get("exports", []):
        fid = item["id"]
        dest = REPO / item["dest"] if item.get("dest") else OUT / f"{fid}.jpg"
        if dest.exists() and not item.get("force"):
            print(f"skip {dest.relative_to(REPO)} (exists)")
            continue
        info = meta(session, fid)
        max_edge = int(item.get("max", 1600))
        if info.get("mimeType", "").startswith("video/") or "t" in item:
            im = video_frame(session, fid, float(item.get("t", 1.0)), max_edge)
        else:
            im = image_rendition(session, fid, max_edge)
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "JPEG", quality=int(item.get("quality", 86)), optimize=True, progressive=True)
        print(f"wrote {dest.relative_to(REPO)} {im.size[0]}x{im.size[1]} from {info.get('name')!r}")
        done += 1
    print(f"{done} exported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
