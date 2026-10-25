#!/usr/bin/env python3
"""
Export specific Drive files as site images, driven by scripts/drive_export.json:

  {"exports": [
     {"id": "<drive id>", "t": 6.0, "max": 1600},          # video: the frame at t seconds
     {"id": "<drive id>", "max": 1600},                    # image: Drive's own rendition
     {"id": "<drive id>", "t": 2, "dest": "assets/images/covers/x-1600.jpg"},
     {"id": "<drive id>", "sheet": 12, "dest": "_scout/x.jpg"},  # 12-frame contact sheet with timestamps
     {"id": "<drive id>", "sheet": 8, "from": -8, "dest": "_scout/end.jpg"},  # ...over the last 8 s only
     {"id": "<drive id>", "clip": {"from": 9, "to": -4.5}, "dest": "assets/video/x.mp4"},
     {"id": "<drive id>", "scenes": {"from": -6, "threshold": 0.3}}  # log cut times, write nothing
  ]}

`from` and `to` are seconds into the video; a negative value counts back from the
end. A `clip` item cuts that span out of a Drive video and encodes it as an H.264
MP4 for self-hosting: short side `height` (default 720), `crf` (default 24),
audio kept as AAC when the source has it, and an optional `fade` (seconds) that
fades picture and sound out at the new end so a trimmed cut does not stop dead.
Use it only for trims and resizes; it does not alter the picture otherwise.
A negative `t` on a frame export counts back from the end. A `scenes` item prints
the timestamps of hard cuts in a span to the log, for placing a trim exactly.

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


def _span(dur: float, start, end) -> tuple[float, float]:
    """Resolve a from/to pair (seconds; negative counts back from the end) against a duration."""
    a = 0.0 if start is None else float(start)
    b = dur if end is None else float(end)
    a = dur + a if a < 0 else a
    b = dur + b if b < 0 else b
    a, b = max(0.0, min(a, dur)), max(0.0, min(b, dur))
    if b <= a:
        raise ValueError(f"empty span {start!r}..{end!r} for a {dur:.2f}s video")
    return a, b


def contact_sheet(session, file_id: str, n: int, cell_w: int, start=None, end=None) -> Image.Image:
    """n frames spread over the video (or over from..to), tiled 4 across with their timestamps,
    for choosing a poster or checking an overlay without downloading the file."""
    from PIL import ImageDraw
    dur = video_duration(session, file_id)
    a, b = _span(dur, start, end)
    times = [a + (b - a) * (i + 0.5) / n for i in range(n)]
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


def video_clip(session, file_id: str, dest: Path, spec: dict) -> str:
    """Cut spec['from']..spec['to'] out of a Drive video and encode it for the site: H.264 (yuv420p,
    faststart) with the short side scaled to spec['height'], AAC audio when the source has any."""
    url = f"{API_BASE}/{file_id}?alt=media&supportsAllDrives=true"
    auth = f"Authorization: Bearer {_token(session)}\r\n"
    dur = video_duration(session, file_id)
    a, b = _span(dur, spec.get("from"), spec.get("to"))
    h = int(spec.get("height", 720))
    vf = f"scale='if(gt(iw,ih),-2,{h})':'if(gt(iw,ih),{h},-2)'"
    af = []
    fade = float(spec.get("fade", 0) or 0)
    if fade > 0:
        st = max(0.0, (b - a) - fade)
        vf += f",fade=t=out:st={st:.3f}:d={fade:.3f}"
        af = ["-af", f"afade=t=out:st={st:.3f}:d={fade:.3f}"]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "clip.mp4"
        cmd = ["ffmpeg", "-loglevel", "error", "-y", "-headers", auth, "-ss", f"{a:.3f}", "-i", url,
               "-t", f"{b - a:.3f}", "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf, *af,
               "-c:v", "libx264", "-preset", "slow", "-crf", str(int(spec.get("crf", 24))),
               "-pix_fmt", "yuv420p", "-profile:v", "high", "-c:a", "aac", "-b:a", "128k",
               "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True, timeout=1800)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(out.read_bytes())
    return f"{a:.2f}s..{b:.2f}s of {dur:.2f}s"


def scene_cuts(session, file_id: str, spec: dict) -> list[float]:
    """Timestamps (seconds from the start of the file) of hard cuts inside spec['from']..spec['to'],
    from ffmpeg's scene score, for placing a trim on the exact frame."""
    url = f"{API_BASE}/{file_id}?alt=media&supportsAllDrives=true"
    dur = video_duration(session, file_id)
    a, b = _span(dur, spec.get("from"), spec.get("to"))
    thr = float(spec.get("threshold", 0.3))
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-headers", f"Authorization: Bearer {_token(session)}\r\n",
           "-ss", f"{a:.3f}", "-i", url, "-t", f"{b - a:.3f}", "-an",
           "-vf", f"select='gt(scene,{thr})',showinfo", "-f", "null", "-"]
    err = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=900).stderr
    cuts = [a + float(m) for m in re.findall(r"pts_time:([0-9.]+)", err)]
    print(f"scenes {file_id}: duration {dur:.3f}s, cuts in {a:.2f}..{b:.2f}: " + ", ".join(f"{c:.3f}" for c in cuts))
    return cuts


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
        if item.get("scenes"):
            scene_cuts(session, fid, item["scenes"])
            continue
        if dest.exists() and not item.get("force"):
            print(f"skip {dest.relative_to(REPO)} (exists)")
            continue
        info = meta(session, fid)
        max_edge = int(item.get("max", 1600))
        if item.get("clip"):
            span = video_clip(session, fid, dest, item["clip"])
            print(f"wrote {dest.relative_to(REPO)} ({dest.stat().st_size / 1e6:.1f} MB, {span}) from {info.get('name')!r}")
            done += 1
            continue
        if item.get("sheet"):
            im = contact_sheet(session, fid, int(item["sheet"]), int(item.get("cell", 480)), item.get("from"), item.get("to"))
        elif info.get("mimeType", "").startswith("video/") or "t" in item:
            t = float(item.get("t", 1.0))
            if t < 0:
                t = max(0.0, video_duration(session, fid) + t)
            im = video_frame(session, fid, t, max_edge)
        else:
            im = image_rendition(session, fid, max_edge, info)
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "JPEG", quality=int(item.get("quality", 86)), optimize=True, progressive=True)
        print(f"wrote {dest.relative_to(REPO)} {im.size[0]}x{im.size[1]} from {info.get('name')!r}")
        done += 1
    done += export_urls()
    print(f"{done} exported")
    return 0


def export_urls() -> int:
    """Plain-URL exports (Canva download links, for example), passed through the
    EXPORT_URLS environment variable as a JSON list of {"url", "dest", "max"?} so
    the signed links never land in the repository. Each is saved to `dest`
    (JPEG, or PNG when dest ends in .png) with an 800 px WebP beside it under
    thumbs/, the same shape make_thumbs.py gives the Drive images."""
    raw = os.environ.get("EXPORT_URLS", "").strip()
    if not raw:
        return 0
    import requests
    done = 0
    for item in json.loads(raw):
        dest = REPO / item["dest"]
        if dest.exists() and not item.get("force"):
            print(f"skip {dest.relative_to(REPO)} (exists)")
            continue
        r = requests.get(item["url"], timeout=180)
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content))
        max_edge = int(item.get("max", 1600))
        im.thumbnail((max_edge, max_edge))
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.suffix.lower() == ".png":
            im.save(dest, "PNG", optimize=True)
        else:
            im.convert("RGB").save(dest, "JPEG", quality=int(item.get("quality", 86)), optimize=True, progressive=True)
        thumb = dest.parent / "thumbs" / (dest.stem + ".webp")
        thumb.parent.mkdir(parents=True, exist_ok=True)
        t = im.convert("RGB")
        t.thumbnail((800, 800))
        t.save(thumb, "WEBP", quality=82, method=6)
        print(f"wrote {dest.relative_to(REPO)} {im.size[0]}x{im.size[1]} from a url")
        done += 1
    return done


if __name__ == "__main__":
    sys.exit(main())
