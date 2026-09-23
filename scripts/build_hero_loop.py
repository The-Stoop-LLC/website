#!/usr/bin/env python3
"""Build the homepage hero background loop from client footage on Drive.

scripts/hero_loop.json drives it:

  "segments": the cut list, in play order. Each entry takes a Drive file id,
      a start time and a duration in seconds. Optional crop anchors (0 = left
      or top edge, 0.5 = centre, 1 = right or bottom edge) choose which part
      of the frame survives the crop:
        "x" / "y"   for the 16:9 desktop cut
        "mx" / "my" for the 9:16 phone cut
  "scout": clips to preview. For each one a contact sheet (a frame every
      second or two, stamped with its time) is written to _scout/ so shots
      can be picked without downloading the footage. _scout/ is a working
      folder: empty the list before merging and the next run removes it.

Outputs (only when "segments" is non-empty):
  assets/video/hero-1080.mp4       1920x1080, large landscape screens
  assets/video/hero-720.mp4        1280x720, smaller landscape screens
  assets/video/hero-portrait.mp4   720x1280, phones and portrait tablets
  assets/video/hero-poster.{jpg,webp} and hero-poster-portrait.{jpg,webp}
      first frame of each cut, shown until the video plays

Videos are H.264 with no audio track and the index at the front, so they
start streaming at once in every browser. HDR phone footage is tone-mapped
to SDR so it doesn't look washed out.

Runs in .github/workflows/build-hero-loop.yml, which has the Drive service
account key (DRIVE_SA_KEY). Needs ffmpeg and ffprobe on PATH. For a local
dry run against files already on disk: --local DIR (files named <id>.<ext>).
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "scripts" / "hero_loop.json"
VIDEO_DIR = REPO_ROOT / "assets" / "video"
SCOUT_DIR = REPO_ROOT / "_scout"
API_BASE = "https://www.googleapis.com/drive/v3/files"

FPS = 30
# (name, width, height, crf, max bitrate in kbps) for each output cut
LANDSCAPE = [("hero-1080", 1920, 1080, 27, 3000), ("hero-720", 1280, 720, 27, 1600)]
PORTRAIT = [("hero-portrait", 720, 1280, 27, 1600)]
HDR_TRANSFERS = {"arib-std-b67", "smpte2084"}
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
           "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv")


def run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-3000:])
        raise RuntimeError(f"command failed: {' '.join(cmd[:6])} ...")
    return proc.stdout


# ---------- sources ----------

class Sources:
    """Downloads each Drive file once per run (or reads it from --local)."""

    def __init__(self, workdir: Path, local: Path | None):
        self.workdir = workdir
        self.local = local
        self.session = None
        self.paths: dict[str, Path] = {}

    def get(self, file_id: str) -> Path:
        if file_id in self.paths:
            return self.paths[file_id]
        if self.local:
            matches = sorted(self.local.glob(f"{file_id}.*"))
            if not matches:
                raise FileNotFoundError(f"no local file for {file_id} in {self.local}")
            path = matches[0]
        else:
            path = self.workdir / f"{file_id}.bin"
            self._download(file_id, path)
        self.paths[file_id] = path
        return path

    def drop(self, file_id: str) -> None:
        """Delete a downloaded file once it is no longer needed (runner disk is finite)."""
        path = self.paths.pop(file_id, None)
        if path and not self.local:
            path.unlink(missing_ok=True)

    def _download(self, file_id: str, dest: Path) -> None:
        if self.session is None:
            from build_galleries import build_session
            self.session = build_session()
        url = f"{API_BASE}/{file_id}"
        with self.session.get(url, params={"alt": "media", "supportsAllDrives": "true"},
                              stream=True, timeout=900) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
        print(f"  downloaded {file_id} ({dest.stat().st_size / 1e6:.0f} MB)")


def probe(path: Path) -> dict:
    """Display width/height (after rotation), duration and HDR flag of the first video stream."""
    out = json.loads(run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,color_transfer,r_frame_rate:stream_side_data=rotation"
        ":stream_tags=rotate:format=duration",
        "-of", "json", str(path),
    ]))
    stream = out["streams"][0]
    w, h = int(stream["width"]), int(stream["height"])
    rotation = 0
    for side in stream.get("side_data_list", []) or []:
        if "rotation" in side:
            rotation = int(float(side["rotation"]))
    rotation = rotation or int(stream.get("tags", {}).get("rotate", 0) or 0)
    if abs(rotation) % 180 == 90:
        w, h = h, w
    return {
        "width": w, "height": h,
        "duration": float(out["format"]["duration"]),
        "hdr": stream.get("color_transfer") in HDR_TRANSFERS,
        "fps": stream.get("r_frame_rate", ""),
    }


def crop_filter(info: dict, ratio: float, ax: float, ay: float) -> str:
    """ffmpeg crop to `ratio` (w/h), keeping the part of the frame the anchors point at."""
    w, h = info["width"], info["height"]
    if w / h > ratio:
        cw, ch = round(h * ratio), h
    else:
        cw, ch = w, round(w / ratio)
    cw -= cw % 2
    ch -= ch % 2
    cx = round((w - cw) * min(max(ax, 0.0), 1.0))
    cy = round((h - ch) * min(max(ay, 0.0), 1.0))
    return f"crop={cw}:{ch}:{cx}:{cy}"


def base_filters(info: dict) -> list[str]:
    return [TONEMAP] if info["hdr"] else []


# ---------- scout: contact sheets ----------

def font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def contact_sheet(src: Path, info: dict, label: str, dest: Path) -> None:
    dur = info["duration"]
    step = max(1.0, dur / 36)
    times = [round(step * (i + 0.5), 2) for i in range(int(dur / step))] or [dur / 2]
    tile_h = 180
    tile_w = round(tile_h * info["width"] / info["height"])
    cols = max(1, 1600 // (tile_w + 4))
    rows = math.ceil(len(times) / cols)
    head = 34
    sheet = Image.new("RGB", (cols * (tile_w + 4) + 4, head + rows * (tile_h + 4) + 4), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), f"{label}  |  {info['width']}x{info['height']}  {dur:.1f}s"
                      f"{'  HDR' if info['hdr'] else ''}", fill=(255, 204, 0), font=font(18))
    vf = ",".join(base_filters(info) + [f"scale={tile_w}:{tile_h}"])
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(times):
            frame = Path(tmp) / f"{i}.png"
            run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(src), "-frames:v", "1",
                 "-vf", vf, "-y", str(frame)])
            if not frame.exists():
                continue
            x = 4 + (i % cols) * (tile_w + 4)
            y = head + 4 + (i // cols) * (tile_h + 4)
            sheet.paste(Image.open(frame).convert("RGB"), (x, y))
            draw.rectangle((x, y, x + 58, y + 20), fill=(0, 0, 0))
            draw.text((x + 4, y + 2), f"{t:.1f}s", fill=(255, 255, 255), font=font(14))
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, "JPEG", quality=72, optimize=True)


def scout(entries: list[dict], sources: Sources) -> None:
    index = {}
    for n, entry in enumerate(entries, 1):
        fid = entry["id"]
        label = entry.get("label", fid)
        print(f"[scout {n}/{len(entries)}] {label}")
        try:
            src = sources.get(fid)
            info = probe(src)
            contact_sheet(src, info, label, SCOUT_DIR / f"{n:02d}-{fid}.jpg")
            index[fid] = {"sheet": f"{n:02d}-{fid}.jpg", "label": label, **info}
        except Exception as exc:  # keep going; one bad clip shouldn't sink the run
            print(f"  skipped: {exc}")
            index[fid] = {"label": label, "error": str(exc)}
        finally:
            sources.drop(fid)
    (SCOUT_DIR / "index.json").write_text(json.dumps(index, indent=2) + "\n")


# ---------- build: the loop ----------

def cut_segments(segments: list[dict], sources: Sources, tmp: Path) -> dict[str, list[Path]]:
    """Cut every segment to an intermediate per orientation, all at 30 fps, no audio."""
    parts: dict[str, list[Path]] = {"landscape": [], "portrait": []}
    last_use = {seg["id"]: i for i, seg in enumerate(segments)}
    for i, seg in enumerate(segments):
        src = sources.get(seg["id"])
        info = probe(src)
        start, dur = float(seg["start"]), float(seg["dur"])
        if start + dur > info["duration"] + 0.05:
            raise ValueError(f"segment {i} ({seg['id']}) runs past the clip's end ({info['duration']:.1f}s)")
        for orient, ratio, ax, ay, size in (
            ("landscape", 16 / 9, seg.get("x", 0.5), seg.get("y", 0.5), (1920, 1080)),
            ("portrait", 9 / 16, seg.get("mx", 0.5), seg.get("my", 0.5), (720, 1280)),
        ):
            vf = ",".join(base_filters(info) + [
                crop_filter(info, ratio, ax, ay),
                f"scale={size[0]}:{size[1]}:flags=lanczos",
                f"fps={FPS}", "setsar=1", "format=yuv420p",
            ])
            out = tmp / f"{orient}-{i:02d}.mp4"
            run(["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(src), "-t", str(dur),
                 "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
                 "-y", str(out)])
            parts[orient].append(out)
        print(f"  cut {i + 1}/{len(segments)}: {seg.get('note', seg['id'])} @ {start}s for {dur}s")
        if last_use[seg["id"]] == i:
            sources.drop(seg["id"])
    return parts


def encode(parts: list[Path], tmp: Path, name: str, w: int, h: int, crf: int, kbps: int) -> Path:
    listing = tmp / f"{name}.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts))
    out = VIDEO_DIR / f"{name}.mp4"
    run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-vf", f"scale={w}:{h}:flags=lanczos,setsar=1,format=yuv420p",
         "-an", "-c:v", "libx264", "-preset", "slow", "-profile:v", "high", "-crf", str(crf),
         "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k", "-g", str(FPS * 2),
         "-movflags", "+faststart", "-map_metadata", "-1", "-y", str(out)])
    return out


def poster(video: Path, stem: str) -> None:
    jpg = VIDEO_DIR / f"{stem}.jpg"
    run(["ffmpeg", "-v", "error", "-i", str(video), "-frames:v", "1", "-q:v", "4", "-y", str(jpg)])
    Image.open(jpg).save(VIDEO_DIR / f"{stem}.webp", "WEBP", quality=62, method=6)


def build(segments: list[dict], sources: Sources) -> None:
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        parts = cut_segments(segments, sources, tmp)
        for name, w, h, crf, rate in LANDSCAPE:
            out = encode(parts["landscape"], tmp, name, w, h, crf, rate)
            print(f"  {out.name}: {out.stat().st_size / 1e6:.2f} MB")
        for name, w, h, crf, rate in PORTRAIT:
            out = encode(parts["portrait"], tmp, name, w, h, crf, rate)
            print(f"  {out.name}: {out.stat().st_size / 1e6:.2f} MB")
    poster(VIDEO_DIR / "hero-1080.mp4", "hero-poster")
    poster(VIDEO_DIR / "hero-portrait.mp4", "hero-poster-portrait")
    total = sum(float(s["dur"]) for s in segments)
    print(f"built {len(segments)} shots, {total:.1f}s loop")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--local", type=Path, help="read <id>.<ext> files from this folder instead of Drive")
    args = parser.parse_args()
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"{tool} not found on PATH", file=sys.stderr)
            return 1
    config = json.loads(CONFIG.read_text())
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    shutil.rmtree(SCOUT_DIR, ignore_errors=True)  # rebuilt below, or gone once "scout" is emptied
    with tempfile.TemporaryDirectory() as work:
        sources = Sources(Path(work), args.local)
        if config.get("scout"):
            scout(config["scout"], sources)
        if config.get("segments"):
            build(config["segments"], sources)
    return 0


if __name__ == "__main__":
    sys.exit(main())
