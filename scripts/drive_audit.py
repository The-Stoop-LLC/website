#!/usr/bin/env python3
"""
Map everything the site's Drive service account can see, then make contact
sheets so the footage can be reviewed without downloading it.

Stage 1 (always): inventory
  Lists every non-trashed file shared with the service account, walks every
  folder (and folder shortcut) so nothing inside a shared folder is missed,
  resolves each file's folder path, and marks what the site already uses
  (any Drive ID found in the repo, files inside a DRIVE_GALLERY folder, and
  the hero loop sources). Writes:
    _inventory/files.json    one row per file or folder
    _inventory/folders.json  per-folder counts, sizes and video minutes
    _inventory/summary.md    the folder tree with counts, for reading

Stage 2 (optional): sheets, driven by scripts/drive_audit.json
  "videos":  file IDs -> an 8-frame contact sheet each, read straight from
             Drive with HTTP range requests (nothing is fully downloaded)
  "mosaics": folder IDs -> numbered thumbnail grids of the images and
             videos directly inside each folder
  Written to _inventory/sheets/ with an index.json that maps every sheet
  cell back to its Drive file.

Environment:
  DRIVE_SA_KEY  service account JSON (same secret as the gallery build)
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_galleries import API_BASE, MARKER_RE, build_session, parse_attrs  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "_inventory"
CONFIG = Path(__file__).resolve().parent / "drive_audit.json"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
FIELDS = ("id,name,mimeType,size,parents,createdTime,modifiedTime,owners(emailAddress),"
          "shortcutDetails,videoMediaMetadata,imageMediaMetadata(width,height,rotation,cameraModel,time),"
          "thumbnailLink,fileExtension")
DRIVE_ID_RE = re.compile(r"[A-Za-z0-9_-]{25,44}")
HDR_TRANSFERS = {"arib-std-b67", "smpte2084"}
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
           "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv")
FRAMES = 8


def kind_of(mime: str) -> str:
    if mime == FOLDER_MIME:
        return "folder"
    if mime == SHORTCUT_MIME:
        return "shortcut"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime == "application/pdf":
        return "pdf"
    if mime.startswith("application/vnd.google-apps."):
        return "g-" + mime.rsplit(".", 1)[1]
    return "other"


class Drive:
    def __init__(self) -> None:
        self.session = build_session()
        self.lock = threading.Lock()

    def get(self, url: str, **params) -> dict:
        for attempt in range(5):
            resp = self.session.get(url, params=params, timeout=60)
            if resp.status_code in (429, 500, 502, 503) or (
                    resp.status_code == 403 and "rateLimit" in resp.text):
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return {}

    def list(self, q: str) -> list[dict]:
        out, token = [], None
        while True:
            params = dict(q=q, fields=f"nextPageToken,files({FIELDS})", pageSize=1000,
                          corpora="allDrives", includeItemsFromAllDrives="true",
                          supportsAllDrives="true")
            if token:
                params["pageToken"] = token
            data = self.get(API_BASE, **params)
            out += data.get("files", [])
            token = data.get("nextPageToken")
            if not token:
                return out

    def meta(self, file_id: str) -> dict:
        return self.get(f"{API_BASE}/{file_id}", fields=FIELDS, supportsAllDrives="true")

    def token(self) -> str:
        with self.lock:
            creds = self.session.credentials
            if not creds.valid or (creds.expiry and creds.expiry.timestamp() - time.time() < 600):
                creds.refresh(Request())
            return creds.token


# ---------------------------------------------------------------- inventory

def crawl(drive: Drive) -> dict[str, dict]:
    files = {f["id"]: f for f in drive.list("trashed=false")}
    print(f"global listing: {len(files)} items", flush=True)
    queue = [f["id"] for f in files.values() if f["mimeType"] == FOLDER_MIME]
    for f in list(files.values()):
        target = (f.get("shortcutDetails") or {}).get("targetId")
        if target and target not in files:
            meta = drive.meta(target)
            if meta:
                files[target] = meta
                if meta["mimeType"] == FOLDER_MIME:
                    queue.append(target)
    walked: set[str] = set()
    while queue:
        folder = queue.pop()
        if folder in walked:
            continue
        walked.add(folder)
        for child in drive.list(f"'{folder}' in parents and trashed=false"):
            if child["id"] not in files:
                files[child["id"]] = child
            if child["mimeType"] == FOLDER_MIME:
                queue.append(child["id"])
    print(f"after walking {len(walked)} folders: {len(files)} items", flush=True)

    # Name the folders above what was shared, where the account can read them.
    missing = {p for f in files.values() for p in f.get("parents", []) if p not in files}
    while missing:
        found = {}
        for pid in missing:
            meta = drive.meta(pid)
            found[pid] = meta or {"id": pid, "name": f"[not shared {pid}]", "mimeType": FOLDER_MIME,
                                  "unreadable": True}
        files.update(found)
        missing = {p for f in found.values() for p in f.get("parents", []) if p not in files}
    return files


def site_references() -> tuple[dict[str, set[str]], dict[str, str]]:
    """Drive IDs mentioned anywhere in the repo -> the files that mention them,
    and gallery folder ID -> page."""
    refs: dict[str, set[str]] = defaultdict(set)
    galleries: dict[str, str] = {}
    skip = {".git", "_inventory", "node_modules", "__pycache__"}
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or skip & set(path.relative_to(REPO_ROOT).parts):
            continue
        rel = str(path.relative_to(REPO_ROOT))
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
            refs[path.stem].add(rel)  # localized copies are named by Drive ID
            continue
        if path.suffix.lower() not in {".html", ".json", ".js", ".xml", ".md", ".py", ".txt", ".css"}:
            continue
        text = path.read_text(errors="ignore")
        for token in set(DRIVE_ID_RE.findall(text)):
            refs[token].add(rel)
        if path.suffix == ".html":
            for match in MARKER_RE.finditer(text):
                folder = parse_attrs(match.group("attrs")).get("id", "")
                if folder:
                    galleries[folder] = rel
    return refs, galleries


def inventory(drive: Drive) -> list[dict]:
    raw = crawl(drive)
    refs, galleries = site_references()

    def ancestors(fid: str) -> list[str]:
        chain, seen = [], set()
        cur = raw.get(fid, {})
        while cur.get("parents") and cur["parents"][0] not in seen:
            pid = cur["parents"][0]
            seen.add(pid)
            chain.append(pid)
            cur = raw.get(pid, {})
        return chain[::-1]

    rows = []
    for fid, f in raw.items():
        chain = ancestors(fid)
        vmeta = f.get("videoMediaMetadata") or {}
        imeta = f.get("imageMediaMetadata") or {}
        w, h = vmeta.get("width") or imeta.get("width"), vmeta.get("height") or imeta.get("height")
        if imeta.get("rotation") in (1, 3) and w and h:
            w, h = h, w
        used = sorted(set(refs.get(fid, set())) - {"scripts/drive_audit.json"})
        via_gallery = [galleries[a] for a in chain if a in galleries]
        rows.append({
            "id": fid,
            "name": f.get("name", ""),
            "kind": kind_of(f.get("mimeType", "")),
            "mime": f.get("mimeType", ""),
            "size": int(f.get("size", 0) or 0),
            "path": "/".join(raw.get(a, {}).get("name", "?") for a in chain),
            "parent": chain[-1] if chain else "",
            "ancestors": chain,
            "created": f.get("createdTime", "")[:10],
            "modified": f.get("modifiedTime", "")[:10],
            "owner": ((f.get("owners") or [{}])[0]).get("emailAddress", ""),
            "w": w, "h": h,
            "dur": round(int(vmeta["durationMillis"]) / 1000, 1) if vmeta.get("durationMillis") else None,
            "camera": imeta.get("cameraModel"),
            "target": (f.get("shortcutDetails") or {}).get("targetId"),
            "unreadable": bool(f.get("unreadable")),
            "on_site": used,
            "in_gallery": sorted(set(via_gallery)),
        })
    rows.sort(key=lambda r: (r["path"].lower(), r["kind"] != "folder", r["name"].lower()))
    return rows


def write_inventory(rows: list[dict], sa_email: str) -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "files.json").write_text(json.dumps(rows, indent=0, ensure_ascii=False))

    by_id = {r["id"]: r for r in rows}
    direct: dict[str, dict] = {r["id"]: defaultdict(int) for r in rows if r["kind"] == "folder"}
    total: dict[str, dict] = {r["id"]: defaultdict(int) for r in rows if r["kind"] == "folder"}
    for r in rows:
        if r["kind"] == "folder":
            continue
        for a in r["ancestors"]:
            for bucket in (total[a], direct[a]) if a == r["parent"] else (total[a],):
                bucket[r["kind"]] += 1
                bucket["bytes"] += r["size"]
                bucket["video_s"] += int(r["dur"] or 0) if r["kind"] == "video" else 0
                bucket["used"] += bool(r["on_site"] or r["in_gallery"])
    folders = []
    for fid in total:
        r = by_id[fid]
        folders.append({"id": fid, "name": r["name"], "path": (r["path"] + "/" + r["name"]).lstrip("/"),
                        "depth": len(r["ancestors"]), "direct": dict(direct[fid]), "total": dict(total[fid]),
                        "unreadable": r["unreadable"]})
    folders.sort(key=lambda f: f["path"].lower())
    (OUT / "folders.json").write_text(json.dumps(folders, indent=0, ensure_ascii=False))

    def fmt(s: dict) -> str:
        parts = [f"{s[k]} {k}" for k in ("video", "image", "audio", "pdf", "other") if s.get(k)]
        parts += [f"{s[k]} {k[2:]}" for k in sorted(s) if k.startswith("g-") and s[k]]
        if s.get("video_s"):
            parts.append(f"{s['video_s'] / 60:.0f} min video")
        if s.get("bytes"):
            b = s["bytes"]
            parts.append(f"{b / 1e9:.1f} GB" if b >= 1e8 else f"{b / 1e6:.0f} MB")
        if s.get("used"):
            parts.append(f"{s['used']} on site")
        return ", ".join(parts) or "empty"

    kinds = defaultdict(int)
    for r in rows:
        kinds[r["kind"]] += 1
    lines = [f"# Drive inventory ({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())})", "",
             f"Service account: `{sa_email}`", "",
             "Totals: " + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])),
             f"Files already referenced by the site: {sum(bool(r['on_site']) for r in rows)}; "
             f"inside a gallery folder: {sum(bool(r['in_gallery']) for r in rows)}", "", "## Folders", ""]
    for f in folders:
        lines.append(f"{'  ' * f['depth']}- **{f['name']}** `{f['id']}` — {fmt(f['total'])}")
    (OUT / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:8]), flush=True)


# ------------------------------------------------------------------- sheets

def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int = 14) -> None:
    f = font(size)
    x, y = xy
    box = draw.textbbox((x, y), text, font=f)
    draw.rectangle((box[0] - 3, box[1] - 2, box[2] + 3, box[3] + 2), fill=(0, 0, 0))
    draw.text((x, y), text, fill=(255, 255, 255), font=f)


def ffprobe_url(url: str, headers: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-headers", headers, "-select_streams", "v:0",
         "-show_entries", "stream=width,height,color_transfer:stream_side_data=rotation:format=duration",
         "-of", "json", url], capture_output=True, text=True, timeout=180)
    data = json.loads(out.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    return {"hdr": stream.get("color_transfer") in HDR_TRANSFERS,
            "dur": float((data.get("format") or {}).get("duration") or 0)}


def grab(url: str, headers: str, t: float, hdr: bool, dest: Path) -> bool:
    vf = (TONEMAP + "," if hdr else "") + "scale=480:480:force_original_aspect_ratio=decrease"
    for attempt in range(2):
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-headers", headers, "-ss", f"{t:.2f}", "-i", url,
             "-frames:v", "1", "-vf", vf, "-q:v", "4", str(dest)],
            capture_output=True, text=True, timeout=300)
        if proc.returncode == 0 and dest.exists() and dest.stat().st_size:
            return True
        time.sleep(2)
    return False


def video_sheet(drive: Drive, row: dict, dest: Path) -> dict:
    url = f"{API_BASE}/{row['id']}?alt=media&supportsAllDrives=true"
    headers = f"Authorization: Bearer {drive.token()}\r\n"
    info = ffprobe_url(url, headers)
    dur = row.get("dur") or info["dur"]
    if not dur:
        return {"error": "no duration"}
    times = [dur * (i + 0.5) / FRAMES for i in range(FRAMES)]
    frames = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(times):
            p = Path(tmp) / f"{i}.jpg"
            frames.append(Image.open(p).convert("RGB") if grab(url, headers, t, info["hdr"], p) else None)
    good = [f for f in frames if f]
    if not good:
        return {"error": "no frames"}
    fw, fh = good[0].size
    cols = FRAMES if fh > fw else FRAMES // 2
    cell_w, cell_h = (240, round(240 * fh / fw)) if fh > fw else (360, round(360 * fh / fw))
    rows_n = -(-FRAMES // cols)
    head = 34
    sheet = Image.new("RGB", (cols * cell_w, head + rows_n * cell_h), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    title = f"{row['name']}  ·  {int(dur // 60)}:{int(dur % 60):02d}  ·  {row.get('w')}x{row.get('h')}"
    draw.text((8, 8), title[:150], fill=(255, 255, 255), font=font(16))
    for i, (t, fr) in enumerate(zip(times, frames)):
        x, y = (i % cols) * cell_w, head + (i // cols) * cell_h
        if fr:
            sheet.paste(fr.resize((cell_w, cell_h)), (x, y))
        label(draw, (x + 5, y + 5), f"{int(t // 60)}:{t % 60:04.1f}", 13)
    sheet.save(dest, quality=72)
    return {"sheet": str(dest.relative_to(OUT)), "times": [round(t, 1) for t in times],
            "missing": sum(f is None for f in frames)}


def thumb(drive: Drive, link: str | None) -> Image.Image | None:
    if not link:
        return None
    if not re.search(r"=s640$", link):
        link = re.sub(r"=s\d+$", "=s400", link)
    for attempt in range(3):
        try:
            headers = {"Authorization": f"Bearer {drive.token()}"} if attempt else {}
            resp = requests.get(link, headers=headers, timeout=60)
            if resp.status_code == 200:
                return Image.open(io.BytesIO(resp.content)).convert("RGB")
            if resp.status_code == 404:
                return None
        except Exception:  # noqa: BLE001 - a missing thumbnail is not fatal
            pass
        time.sleep(2 ** attempt)
    return None


def mosaic(drive: Drive, folder: str, rows: list[dict], raw_meta: dict[str, dict],
           limit: int | None = None) -> list[dict]:
    items = [r for r in rows if r["parent"] == folder and r["kind"] in ("image", "video")]
    items.sort(key=lambda r: r["name"].lower())
    if limit and len(items) > limit:  # raw folders: an even sample, not every frame
        items = [items[round(i * (len(items) - 1) / (limit - 1))] for i in range(limit)]
    per, cols, cell = 48, 8, 200
    sheets = []
    with ThreadPoolExecutor(8) as pool:
        thumbs = list(pool.map(lambda r: thumb(drive, raw_meta.get(r["id"], {}).get("thumbnailLink")), items))
    for start in range(0, len(items), per):
        chunk = items[start:start + per]
        n_rows = -(-len(chunk) // cols)
        sheet = Image.new("RGB", (cols * cell, n_rows * cell), (24, 24, 24))
        draw = ImageDraw.Draw(sheet)
        for i, r in enumerate(chunk):
            x, y = (i % cols) * cell, (i // cols) * cell
            im = thumbs[start + i]
            if im:
                im.thumbnail((cell - 4, cell - 4))
                sheet.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
            tag = f"{start + i + 1}" + (f" ▶{int(r['dur'] or 0)}s" if r["kind"] == "video" else "")
            label(draw, (x + 4, y + 4), tag, 13)
        dest = OUT / "sheets" / "m" / f"{folder}-{start // per + 1}.jpg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(dest, quality=70)
        sheets.append({"sheet": str(dest.relative_to(OUT)),
                       "cells": [{"n": start + i + 1, "id": r["id"], "name": r["name"], "kind": r["kind"]}
                                 for i, r in enumerate(chunk)]})
    return sheets


def make_sheets(drive: Drive, rows: list[dict], config: dict) -> None:
    by_id = {r["id"]: r for r in rows}
    index_path = OUT / "sheets" / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"videos": {}, "mosaics": {}}

    todo = [v for v in config.get("videos", []) if v in by_id and v not in index["videos"]]
    print(f"video sheets: {len(todo)} to make", flush=True)
    (OUT / "sheets" / "v").mkdir(parents=True, exist_ok=True)
    done = [0]

    def one(vid: str) -> None:
        try:
            result = video_sheet(drive, by_id[vid], OUT / "sheets" / "v" / f"{vid}.jpg")
        except Exception as exc:  # noqa: BLE001 - keep going, record the failure
            result = {"error": str(exc)[:200]}
        with drive.lock:
            index["videos"][vid] = result
            done[0] += 1
            if done[0] % 10 == 0:
                print(f"  {done[0]}/{len(todo)}", flush=True)
                index_path.write_text(json.dumps(index, indent=1))

    with ThreadPoolExecutor(int(config.get("workers", 6))) as pool:
        list(pool.map(one, todo))

    # entries are a folder ID, or {"id": ..., "max": N} to sample N items evenly
    folders = [f if isinstance(f, dict) else {"id": f} for f in config.get("mosaics", [])]
    folders = [f for f in folders if f["id"] not in index["mosaics"]]
    print(f"mosaics: {len(folders)} folders to make", flush=True)
    for n, f in enumerate(folders, 1):
        fid = f["id"]
        raw_meta = {m["id"]: m for m in drive.list(f"'{fid}' in parents and trashed=false")}
        index["mosaics"][fid] = mosaic(drive, fid, rows, raw_meta, f.get("max"))
        if n % 25 == 0:
            print(f"  {n}/{len(folders)}", flush=True)
            index_path.write_text(json.dumps(index, indent=1))
    index_path.write_text(json.dumps(index, indent=1))
    errors = {k: v for k, v in index["videos"].items() if "error" in v}
    print(f"sheets done; {len(errors)} video errors", flush=True)


def make_picks(drive: Drive, rows: list[dict], picks: list[dict]) -> None:
    """Clean 640px WebP stills for the report: a frame at `t` seconds for a
    video, Drive's own thumbnail for an image."""
    by_id = {r["id"]: r for r in rows}
    out = OUT / "picks"
    out.mkdir(parents=True, exist_ok=True)
    todo = [p for p in picks if p["id"] in by_id and not (out / f"{p['id']}.webp").exists()]
    print(f"picks: {len(todo)} to make", flush=True)

    def one(pick: dict) -> None:
        row, dest = by_id[pick["id"]], out / f"{pick['id']}.webp"
        im = None
        try:
            if row["kind"] == "video":
                url = f"{API_BASE}/{row['id']}?alt=media&supportsAllDrives=true"
                headers = f"Authorization: Bearer {drive.token()}\r\n"
                hdr = ffprobe_url(url, headers)["hdr"]
                with tempfile.TemporaryDirectory() as tmp:
                    frame = Path(tmp) / "f.jpg"
                    vf = (TONEMAP + "," if hdr else "") + "scale=640:640:force_original_aspect_ratio=decrease"
                    proc = subprocess.run(
                        ["ffmpeg", "-v", "error", "-y", "-headers", headers, "-ss", f"{pick.get('t') or 0:.2f}",
                         "-i", url, "-frames:v", "1", "-vf", vf, "-q:v", "3", str(frame)],
                        capture_output=True, text=True, timeout=300)
                    if proc.returncode == 0 and frame.exists():
                        im = Image.open(frame).convert("RGB")
            else:
                link = drive.meta(row["id"]).get("thumbnailLink")
                im = thumb(drive, link and re.sub(r"=s\d+$", "=s640", link))
                if im:
                    im.thumbnail((640, 640))
        except Exception as exc:  # noqa: BLE001 - a missing still is not fatal
            print(f"  pick {row['name']}: {exc}", flush=True)
        if im:
            im.save(dest, "WEBP", quality=72)

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(one, todo))
    print(f"picks done: {len(list(out.glob('*.webp')))} stills", flush=True)


def main() -> None:
    drive = Drive()
    sa_email = json.loads(os.environ["DRIVE_SA_KEY"]).get("client_email", "?")
    rows = inventory(drive)
    write_inventory(rows, sa_email)
    config = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    if config.get("videos") or config.get("mosaics"):
        if not shutil.which("ffmpeg"):
            raise SystemExit("ffmpeg is required for sheets")
        make_sheets(drive, rows, config)
    if config.get("picks"):
        make_picks(drive, rows, config["picks"])


if __name__ == "__main__":
    main()
