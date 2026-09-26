#!/usr/bin/env python3
"""
Render case-study share images (assets/og/<slug>.jpg, 1200x630) from the
case-study covers, in the site's share-image style: the cover darkened with
a bottom gradient, THE STOOP mark top-left, a yellow eyebrow, the title in
Anton, a subtitle in Outfit, and thestooppgh.com bottom-right.

Driven by scripts/og.json. Usage:

    python3 scripts/make_og.py                 # every slug in og.json
    python3 scripts/make_og.py take-a-nurse    # one slug

Fonts: scripts/fonts (Anton and Outfit, SIL Open Font License).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

REPO = Path(__file__).resolve().parent.parent
FONTS = REPO / "scripts" / "fonts"
COVERS = REPO / "assets" / "images" / "covers"
OUT = REPO / "assets" / "og"
CONFIG = REPO / "scripts" / "og.json"
W, H = 1200, 630
YELLOW = (255, 204, 0)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def stoop_mark(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float = 1.35) -> None:
    s = scale
    for i, (dy, hh) in enumerate(((28, 12), (20, 20), (12, 28))):
        draw.rectangle((x + i * 9 * s, y + dy * s, x + i * 9 * s + 8 * s, y + (dy + hh) * s), fill=YELLOW)
    tracked(draw, (x + 34 * s, y + 9 * s), "THE STOOP", font("outfit-800.ttf", round(24 * s)), "white", 3 * s)


def tracked(draw: ImageDraw.ImageDraw, xy: tuple, text: str, fnt: ImageFont.FreeTypeFont, fill, tracking: float, anchor_right: bool = False) -> None:
    """Draw text with extra letter-spacing (the wordmark, eyebrow and URL are tracked in the house style)."""
    widths = [draw.textlength(ch, font=fnt) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x, y = xy
    if anchor_right:
        x -= total
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += w + tracking


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = (line + " " + w).strip()
        if draw.textlength(trial, font=fnt) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def render(slug: str, spec: dict) -> Path:
    src = COVERS / f"{spec.get('cover', slug)}-1600.jpg"
    im = Image.open(src).convert("RGB")
    im = im.resize((W, round(im.height * W / im.width)), Image.LANCZOS)
    focus = float(spec.get("focus", 0.5))
    top = max(0, min(im.height - H, round(im.height * focus - H / 2)))
    im = im.crop((0, top, W, top + H))
    im = ImageEnhance.Brightness(im).enhance(0.38)
    grad = Image.new("L", (1, H))
    for y in range(H):
        grad.putpixel((0, y), round(200 * max(0, (y - H * 0.35) / (H * 0.65))))
    im = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im, grad.resize((W, H)))
    d = ImageDraw.Draw(im)
    stoop_mark(d, 80, 58)
    if spec.get("kind") == "blog":
        # blog share image: eyebrow, the post title wrapped in Outfit, the site URL under it
        tracked(d, (80, 214), "BLOG", font("outfit-500.ttf", 22), YELLOW, 8)
        title_font = font("outfit-800.ttf", 60)
        y = 250
        for line in wrap(d, spec["title"], title_font, 1040):
            d.text((80, y), line, font=title_font, fill="white")
            y += 72
        tracked(d, (80, y + 24), "thestooppgh.com", font("outfit-400.ttf", 22), (200, 200, 200), 2)
        dest = OUT / f"{slug}.jpg"
        im.save(dest, "JPEG", quality=86, optimize=True, progressive=True)
        return dest
    sub_font = font("outfit-500.ttf", 26)
    lines = wrap(d, spec["subtitle"], sub_font, 800)
    sub_h = len(lines) * 34
    title_y = 520 - sub_h - 128          # title sits above the subtitle block
    tracked(d, (80, title_y - 34), spec.get("eyebrow", "CASE STUDY"), font("outfit-700.ttf", 22), YELLOW, 6)
    d.text((80, title_y), spec["title"], font=font("anton.ttf", 92), fill="white")
    for i, line in enumerate(lines):
        d.text((80, 520 - sub_h + 34 * i + 8), line, font=sub_font, fill=(235, 235, 235))
    d.rectangle((1060, 520, 1120, 524), fill=YELLOW)
    tracked(d, (1120, 548), "thestooppgh.com", font("outfit-400.ttf", 20), (190, 190, 190), 2, anchor_right=True)
    dest = OUT / f"{slug}.jpg"
    im.save(dest, "JPEG", quality=86, optimize=True, progressive=True)
    return dest


def main() -> int:
    cfg = {k: v for k, v in json.loads(CONFIG.read_text()).items() if not k.startswith("_")}
    slugs = sys.argv[1:] or list(cfg)
    for slug in slugs:
        dest = render(slug, cfg[slug])
        print(f"wrote {dest.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
