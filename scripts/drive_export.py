#!/usr/bin/env python3
"""
Export specific Drive files as site images, driven by scripts/drive_export.json:

  {"exports": [
     {"id": "<drive id>", "t": 6.0, "max": 1600},          # video: the frame at t seconds
     {"id": "<drive id>", "max": 1600},                    # image: Drive's own rendition
     {"id": "<drive id>", "t": 2, "dest": "assets/images/covers/x-1600.jpg"},
     {"id": "<drive id>", "sheet": 12, "dest": "_scout/x.jpg"}   # 12-frame contact sheet with timestamps
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
import re
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
    token = _token(session)
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "frame.png"
        cmd = ["ffmpeg", "-loglevel", "error", "-y", "-headers", f"Authorization: Bearer {token}\r\n",
               "-ss", str(t), "-i", url, "-frames:v", "1", "-vf", f"scale='min({max_edge},iw)':-2", str(dest)]
        subprocess.run(cmd, check=True, timeout=600)
        return Image.open(dest).convert("RGB")


def _token(session) -> str:
    token = session.credentials.token
    if not token:
        from google.auth.transport.requests import Request
        session.credentials.refresh(Request())
        token = session.credentials.token
    return token


def video_duration(session, file_id: str) -> float:
    url = f"{API_BASE}/{file_id}?alt=media&supportsAllDrives=true"
    out = subprocess.run(["ffprobe", "-v", "error", "-headers", f"Authorization: Bearer {_token(session)}\r\n",
                          "-show_entries", "format=duration", "-of", "csv=p=0", url],
                         check=True, capture_output=True, text=True, timeout=300).stdout.strip()
    return float(out)


def contact_sheet(session, file_id: str, n: int, cell_w: int) -> Image.Image:
    """n frames spread over the video, tiled 4 across with their timestamps, for choosing a poster
    or checking an overlay without downloading the file."""
    from PIL import ImageDraw
    dur = video_duration(session, file_id)
    times = [dur * (i + 0.5) / n for i in range(n)]
    frames = [video_frame(session, file_id, t, cell_w) for t in times]
    cols = min(4, n)
    rows = (n + cols - 1) // cols
    ch = max(f.height for f in frames) + 22
    sheet = Image.new("RGB", (cols * cell_w, rows * ch), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    for i, (t, f) in enumerate(zip(times, frames)):
        x, y = (i % cols) * cell_w, (i // cols) * ch
        sheet.paste(f, (x + (cell_w - f.width) // 2, y))
        draw.text((x + 6, y + ch - 18), f"{i + 1}  {t:6.1f}s", fill=(255, 204, 0))
    return sheet


def image_rendition(session, file_id: str, max_edge: int, info: dict | None = None) -> Image.Image:
    """The original bytes, or, for formats Pillow cannot open (HEIC), Drive's own JPEG rendition
    at the requested size via the file's thumbnailLink."""
    info = info or {}
    if info.get("mimeType") in ("image/heic", "image/heif") and info.get("thumbnailLink"):
        link = re.sub(r"=s\d+(-c)?$", f"=s{max_edge}", info["thumbnailLink"])
        r = session.get(link, timeout=120)
    else:
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
        if item.get("sheet"):
            im = contact_sheet(session, fid, int(item["sheet"]), int(item.get("cell", 480)))
        elif info.get("mimeType", "").startswith("video/") or "t" in item:
            im = video_frame(session, fid, float(item.get("t", 1.0)), max_edge)
        else:
            im = image_rendition(session, fid, max_edge, info)
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "JPEG", quality=int(item.get("quality", 86)), optimize=True, progressive=True)
        print(f"wrote {dest.relative_to(REPO)} {im.size[0]}x{im.size[1]} from {info.get('name')!r}")
        done += 1
    print(f"{done} exported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
