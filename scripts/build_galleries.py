#!/usr/bin/env python3
"""
Regenerate inline Drive folder galleries in the website's HTML files.

Looks for marker pairs of the form:

    <!-- DRIVE_GALLERY_START id=<FOLDER_ID> [label="..."] -->
    ...generated content (replaced on each run)...
    <!-- DRIVE_GALLERY_END -->

For each pair, this script:
  1. Calls Drive API v3 files.list on the folder using a service account
  2. Emits an `<img>` thumbnail tile per image file (Drive thumbnail URLs)
  3. Emits an `<iframe>` preview per video file
  4. Replaces the marker body in-place

Each Drive folder must either be shared with the service account's email
(role: Viewer) or shared as "Anyone with the link -> Viewer". Drive
thumbnail and file-preview URLs work for any publicly viewable file, so
visitors don't need to authenticate.

Environment:
  DRIVE_SA_KEY  Full JSON content of a Google Cloud service account key
                with the Drive API enabled on its project.

Exit code is 0 whether or not anything changed; prints a summary.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterable

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

REPO_ROOT = Path(__file__).resolve().parent.parent
API_BASE = "https://www.googleapis.com/drive/v3/files"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

MARKER_RE = re.compile(
    r"(<!--\s*DRIVE_GALLERY_START\s+(?P<attrs>[^>]*?)-->)"
    r"(?P<body>.*?)"
    r"(<!--\s*DRIVE_GALLERY_END\s*-->)",
    re.DOTALL | re.IGNORECASE,
)
ATTR_RE = re.compile(r'(\w+)=(?:"([^"]*)"|(\S+))')


def parse_attrs(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for match in ATTR_RE.finditer(raw):
        key = match.group(1).lower()
        out[key] = match.group(2) if match.group(2) is not None else match.group(3)
    return out


def build_session() -> AuthorizedSession:
    raw = os.environ.get("DRIVE_SA_KEY")
    if not raw:
        raise RuntimeError("DRIVE_SA_KEY environment variable is required")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"DRIVE_SA_KEY is not valid JSON: {exc}. Paste the full service "
            "account JSON file contents into the secret."
        ) from exc
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=SCOPES
    )
    return AuthorizedSession(credentials)


FOLDER_MIME = "application/vnd.google-apps.folder"
DEFAULT_EXCLUDE_FOLDER_NAMES = frozenset({"raw"})
MAX_DEPTH = 10


def list_folder(
    folder_id: str,
    session: AuthorizedSession,
    exclude_folder_names: frozenset[str] = DEFAULT_EXCLUDE_FOLDER_NAMES,
) -> list[dict]:
    """Return all non-trashed image/video files under a Drive folder, recursing
    into sub-folders. Folders whose name (case-insensitive) matches
    `exclude_folder_names` are skipped, so private "Raw" siblings stay private.
    Files are sorted by name across the merged tree.
    """
    collected: list[dict] = []
    seen: set[str] = set()
    excludes_lower = {name.strip().lower() for name in exclude_folder_names if name.strip()}

    def walk(current_id: str, depth: int) -> None:
        if current_id in seen or depth > MAX_DEPTH:
            return
        seen.add(current_id)
        page_token: str | None = None
        while True:
            params = {
                "q": f"'{current_id}' in parents and trashed=false",
                "fields": "nextPageToken,files(id,name,mimeType)",
                "pageSize": 1000,
                "orderBy": "name",
            }
            if page_token:
                params["pageToken"] = page_token
            for attempt in range(3):
                response = session.get(API_BASE, params=params, timeout=30)
                if response.status_code == 200:
                    break
                if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(
                    f"Drive API list failed for folder {current_id}: "
                    f"HTTP {response.status_code} {response.text[:300]}"
                )
            payload = response.json()
            for child in payload.get("files", []):
                if child.get("mimeType") == FOLDER_MIME:
                    if child.get("name", "").lower() in excludes_lower:
                        continue
                    walk(child["id"], depth + 1)
                else:
                    collected.append(child)
            page_token = payload.get("nextPageToken")
            if not page_token:
                break

    walk(folder_id, 0)
    collected.sort(key=lambda f: f.get("name", "").lower())
    return collected


def render_image(file: dict, label: str, index: int) -> str:
    file_id = file["id"]
    alt = html.escape(f"{label} - {index}" if label else file.get("name", file_id))
    return (
        f'    <img src="https://drive.google.com/thumbnail?id={file_id}&sz=w800" '
        f'srcset="https://drive.google.com/thumbnail?id={file_id}&sz=w400 400w, '
        f'https://drive.google.com/thumbnail?id={file_id}&sz=w800 800w" '
        f'sizes="(max-width: 768px) 400px, 800px" '
        f'alt="{alt}" loading="lazy">'
    )


def render_video(file: dict, label: str, index: int) -> str:
    file_id = file["id"]
    title = html.escape(f"{label} - {index}" if label else file.get("name", file_id))
    return (
        f'    <iframe src="https://drive.google.com/file/d/{file_id}/preview" '
        f'style="width:100%; aspect-ratio:9/16; border:1px solid rgba(255,255,255,0.08); '
        f'border-radius:4px; background:#000;" loading="lazy" allow="autoplay" '
        f'title="{title}"></iframe>'
    )


def render_gallery(files: list[dict], label: str) -> str:
    images = [f for f in files if f.get("mimeType", "").startswith("image/")]
    videos = [f for f in files if f.get("mimeType", "").startswith("video/")]

    parts: list[str] = ["\n"]
    if images:
        parts.append('  <div class="gallery-grid reveal">\n')
        for index, file in enumerate(images, start=1):
            parts.append(render_image(file, label, index) + "\n")
        parts.append("  </div>\n")
    if videos:
        parts.append(
            '  <div class="reveal" style="display:grid; '
            "grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); "
            'gap:16px; margin-top:24px;">\n'
        )
        for index, file in enumerate(videos, start=1):
            parts.append(render_video(file, label, index) + "\n")
        parts.append("  </div>\n")
    if not images and not videos:
        parts.append("  <!-- No publicly viewable files found in this folder. -->\n")
    return "".join(parts)


def process_file(
    path: Path,
    session: AuthorizedSession,
    folder_cache: dict[tuple[str, frozenset[str]], list[dict]],
) -> int:
    """Rewrite gallery markers in `path`. Returns the number of galleries replaced."""
    original = path.read_text(encoding="utf-8")
    counter = [0]

    def sub(match: re.Match) -> str:
        attrs = parse_attrs(match.group("attrs"))
        folder_id = attrs.get("id")
        if not folder_id:
            return match.group(0)
        label = attrs.get("label", "")
        exclude_attr = attrs.get("exclude", "")
        excludes = (
            frozenset(name.strip() for name in exclude_attr.split(",") if name.strip())
            if exclude_attr
            else DEFAULT_EXCLUDE_FOLDER_NAMES
        )
        cache_key = (folder_id, excludes)
        if cache_key not in folder_cache:
            folder_cache[cache_key] = list_folder(folder_id, session, excludes)
        body = render_gallery(folder_cache[cache_key], label)
        counter[0] += 1
        return match.group(1) + body + match.group(4)

    new_text = MARKER_RE.sub(sub, original)
    if new_text != original:
        path.write_text(new_text, encoding="utf-8")
    return counter[0]


def iter_html_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.html"):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        yield path


def main() -> int:
    try:
        session = build_session()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    folder_cache: dict[tuple[str, frozenset[str]], list[dict]] = {}
    total_galleries = 0
    files_touched = 0
    for html_path in iter_html_files(REPO_ROOT):
        try:
            count = process_file(html_path, session, folder_cache)
        except Exception as exc:
            print(f"  ERROR {html_path.relative_to(REPO_ROOT)}: {exc}", file=sys.stderr)
            return 1
        if count:
            files_touched += 1
            total_galleries += count
            print(f"  {html_path.relative_to(REPO_ROOT)}: {count} gallery/galleries regenerated")

    print(
        f"\nDone. {total_galleries} gallery markers across {files_touched} files; "
        f"{len(folder_cache)} unique Drive folders fetched."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
