#!/usr/bin/env python3
"""
Check a staged copy of the site before it is deployed.

    python3 scripts/check_site.py <staged site dir>

Fails (exit 1) when
  - a development path (scripts/, .github/, README.md, _scout/) made it into
    the staged copy, or
  - an HTML page, the stylesheet, the sitemap or the web manifest points at a
    local file that is not in the staged copy (a page, image, video, script,
    font or icon that would 404 once deployed).

Links are resolved the way GitHub Pages serves them: "dir/" means
dir/index.html and an extensionless path may be a .html page. External URLs,
mail and phone links, fragments and data: URIs are not checked; absolute
https://thestooppgh.com/ URLs are checked as local paths.
"""
from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

SITE_HOST = "thestooppgh.com"
DEV_PATHS = ("scripts", ".github", "README.md", "_scout")
URL_ATTRS = {"href", "src", "poster", "data-src", "data-src-720", "data-src-1080", "data-src-portrait"}


class Refs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, int]] = []

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        for name, value in attrs:
            if not value:
                continue
            if name in URL_ATTRS:
                self.refs.append((value, line))
            elif name in ("srcset", "imagesrcset"):
                for part in value.split(","):
                    url = part.strip().split(" ")[0]
                    if url:
                        self.refs.append((url, line))
            elif name == "content" and dict(attrs).get("property", "") in ("og:image", "og:image:url", "og:image:secure_url", "og:video", "og:video:url"):
                self.refs.append((value, line))
            elif name == "content" and dict(attrs).get("name", "") == "twitter:image":
                self.refs.append((value, line))


def local_target(root: Path, page: Path, url: str) -> Path | None:
    """The staged file a URL refers to, or None when it is not a local file."""
    url = url.strip()
    if not url or url.startswith(("#", "%23", "mailto:", "tel:", "sms:", "data:", "javascript:", "blob:")):
        return None
    parts = urlsplit(url)
    if parts.scheme in ("http", "https"):
        if parts.hostname not in (SITE_HOST, "www." + SITE_HOST):
            return None
        return root / unquote(parts.path).lstrip("/")
    if parts.scheme or url.startswith("//"):
        return None
    path = unquote(parts.path)
    if not path:
        return None
    return (root / path.lstrip("/")) if path.startswith("/") else (page.parent / path)


def exists_as_served(target: Path) -> bool:
    if target.is_file():
        return True
    if target.is_dir():
        return (target / "index.html").is_file()
    return target.with_name(target.name + ".html").is_file()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    root = Path(sys.argv[1]).resolve()
    problems: list[str] = []

    for dev in DEV_PATHS:
        if (root / dev).exists():
            problems.append(f"development path is in the staged site: {dev}")

    checked = 0
    for page in sorted(root.rglob("*.html")):
        parser = Refs()
        parser.feed(page.read_text(encoding="utf-8", errors="replace"))
        for url, line in parser.refs:
            target = local_target(root, page, url)
            if target is None:
                continue
            checked += 1
            if not exists_as_served(target.resolve()):
                problems.append(f"{page.relative_to(root)}:{line}: missing {url}")

    for css in sorted(root.rglob("*.css")):
        for m in re.finditer(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", css.read_text(encoding="utf-8", errors="replace")):
            target = local_target(root, css, m.group(1))
            if target is None:
                continue
            checked += 1
            if not exists_as_served(target.resolve()):
                problems.append(f"{css.relative_to(root)}: missing {m.group(1)}")

    sitemap = root / "sitemap.xml"
    if sitemap.is_file():
        for m in re.finditer(r"<(?:loc|image:loc)>([^<]+)</", sitemap.read_text(encoding="utf-8")):
            target = local_target(root, sitemap, m.group(1))
            if target is None:
                continue
            checked += 1
            if not exists_as_served(target.resolve()):
                problems.append(f"sitemap.xml: missing {m.group(1)}")

    manifest = root / "site.webmanifest"
    if manifest.is_file():
        for m in re.finditer(r'"src"\s*:\s*"([^"]+)"', manifest.read_text(encoding="utf-8")):
            target = local_target(root, manifest, m.group(1))
            if target is None:
                continue
            checked += 1
            if not exists_as_served(target.resolve()):
                problems.append(f"site.webmanifest: missing {m.group(1)}")

    for p in problems:
        print("::error::" + p if "GITHUB_ACTIONS" in __import__("os").environ else "ERROR " + p)
    print(f"checked {checked} local links; {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
