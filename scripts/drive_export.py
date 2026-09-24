#!/usr/bin/env python3
"""
One-off export of specific Drive files as site images, listed in
scripts/drive_export.json:

  {"exports": [{"id": "<drive id>", "t": 4.5, "max": 1600, "maxw": 1200}]}

Images come from Drive's own rendition; videos give the frame at `t`
seconds. Each is written to assets/images/drive/<id>.jpg (the site's
localized-Drive convention; scripts/make_thumbs.py then builds the WebP
thumbnail). Files that already exist are skipped.

Environment:
  DRIVE_SA_KEY  service account JSON (same secret as the gallery build)
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_galleries import API_BASE, build_session  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = Path(__file__).resolve().parent / "drive_export.json"
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
           "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv")


def token(session) -> str:
    creds = session.credentials
    if not creds.valid or (creds.expiry and creds.expiry.timestamp() - time.time() < 600):
        creds.refresh(Request())
    return creds.token


def meta(session, file_id: str) -> dict:
    resp = session.get(f"{API_BASE}/{file_id}", params={
        "fields": "id,name,mimeType,thumbnailLink", "supportsAllDrives": "true"}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def video_frame(session, file_id: str, t: float, size: int) -> Image.Image | None:
    url = f"{API_BASE}/{file_id}?alt=media&supportsAllDrives=true"
    headers = f"Authorization: Bearer {token(session)}\r\n"
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-headers", headers, "-select_streams", "v:0",
         "-show_entries", "stream=color_transfer", "-of", "json", url],
        capture_output=True, text=True, timeout=180)
    stream = (json.loads(probe.stdout or "{}").get("streams") or [{}])[0]
    hdr = stream.get("color_transfer") in {"arib-std-b67", "smpte2084"}
    vf = (TONEMAP + "," if hdr else "") + (f"scale='min({size},iw)':'min({size},ih)'"
                                          ":force_original_aspect_ratio=decrease")
    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / "f.jpg"
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-headers", headers, "-ss", f"{t:.2f}", "-i", url,
             "-frames:v", "1", "-vf", vf, "-q:v", "2", str(frame)],
            capture_output=True, text=True, timeout=300)
        if proc.returncode == 0 and frame.exists():
            return Image.open(frame).convert("RGB")
        print(proc.stderr[-500:], flush=True)
    return None


def image_rendition(session, link: str | None, size: int) -> Image.Image | None:
    if not link:
        return None
    link = re.sub(r"=s\d+$", f"=s{size}", link)
    for attempt in range(3):
        headers = {"Authorization": f"Bearer {token(session)}"} if attempt else {}
        resp = requests.get(link, headers=headers, timeout=60)
        if resp.status_code == 200:
            return Image.open(io.BytesIO(resp.content)).convert("RGB")
        time.sleep(2 ** attempt)
    return None


def main() -> None:
    session = build_session()
    exports = json.loads(CONFIG.read_text()).get("exports", [])
    written = 0
    for e in exports:
        dest = REPO_ROOT / f"assets/images/drive/{e['id']}.jpg"
        if dest.exists():
            continue
        size, maxw = int(e.get("max", 1600)), int(e.get("maxw", 1200))
        try:
            m = meta(session, e["id"])
            if m["mimeType"].startswith("video/"):
                im = video_frame(session, e["id"], float(e.get("t", 0)), size)
            else:
                im = image_rendition(session, m.get("thumbnailLink"), size)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            print(f"  {e['id']}: {exc}", flush=True)
            continue
        if not im:
            print(f"  {e['id']}: no image", flush=True)
            continue
        im.thumbnail((size, size))
        if im.width > maxw:
            im = im.resize((maxw, round(im.height * maxw / im.width)), Image.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "JPEG", quality=85, optimize=True, progressive=True)
        written += 1
        print(f"  {m['name']} -> {dest.name} {im.size}", flush=True)
    print(f"exports: {written} written", flush=True)


if __name__ == "__main__":
    main()
