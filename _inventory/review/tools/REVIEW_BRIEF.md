# Content review brief: The Stoop's Google Drive

The Stoop is a Pittsburgh creative and marketing agency (thestooppgh.com). Its owner wants the best and most engaging client content on the website. You are reviewing contact sheets made from the agency's Google Drive and scoring what you see. Your judgments go into a report that recommends which pieces go where on the site.

## Your inputs

Your chunk file is a JSON with two lists.

`videos[]`: one per distinct finished video. Aspect-ratio, logo and no-logo versions are grouped under `variants`.
- `sheet` is a JPEG contact sheet. It has a title bar (file name, duration, resolution) and 8 frames spread evenly through the video.
  - Landscape videos: 4 columns × 2 rows.
  - Portrait videos: 8 frames in one row.
  - Frame times are in `frame_times`, and each frame is labelled with its time.
- `on_site` lists the site pages already using it. Empty means it is unused.

`mosaics[]`: one per Drive folder.
- `sheets[]` are numbered thumbnail grids of the images and videos directly in that folder: 8 columns, 48 per sheet.
- Each sheet's `cells[]` maps a cell number `n` to its Drive file `id` and `name`. Video cells show ▶ and the duration.
- `raw: true` means an unedited camera dump. `items_in_folder` can be larger than the number of cells because raw folders are sampled at up to 48 items.
- `on_site` on a cell means it is already on the site.

Look at EVERY sheet in your chunk with the Read tool; it displays images. Do not guess from file names.

## The website (where content can go)
- **Homepage hero loop**: a muted background sizzle made of 3–6 s shots, with side-by-side stacks of vertical clips. The best candidates are striking motion with no text or logo overlays that reads instantly: drone, FPV, action, people, food, landscapes. It already uses:
  - Iron 24 Group Training, FPV and Group
  - MFPAA Feb 2026 60 s
  - Dr. Tea "Emily and Mike" and "Drink Edit Flowers"
  - Sylvan Gardens Drone Clip 2, Drone Vertical 3 and First Property
  - X Shadyside Lucid Juice reel
  - CSMP Fire Roasted Tomato Soup
  - an SXP clip
- **Case study pages**:
  - Existing: work/iron-24, work/sylvan-gardens, work/csmp, work/dr-tea, work/mfpaa, work/x-shadyside, work/sxp, work/take-a-nurse.
    - The Take a Nurse page currently shows only brand design (logos, cards, guide) and no photos or video.
  - No page yet: Union Trust Building (UTB), Chad Isaiah Photography, Castle Rock Tax Services.
- **Service pages**: content-development, organic-social, influencer-marketing, influencer-coaching, digital-advertising, design-branding, website-design, automation-ops.
- **Blog posts**:
  - 15-fitness-influencers-267k-views (Iron 24 influencers)
  - content-production-at-scale-gym (Iron 24, 81 assets)
  - anatomy-of-a-47k-nonprofit-campaign (MFPAA)
  - how-we-generated-480k-views-for-dr-tea
  - organic-social-growth-landscaping (Sylvan Gardens)
  - themed-content-calendar-food-brands (CSMP)
  - cross-brand-partnerships-guide (X Shadyside × Lucid Juice)
  - influencer-marketing-roi-guide
- **Homepage / work index**: client cover images, meaning one strong, clean, representative still per client.

## Scoring (1–5) for "best and most engaging for the website"
- 5: portfolio-grade. It hooks in the first second, is polished (color, framing, pacing, typography) and makes The Stoop look great.
- 4: strong. You'd happily feature it.
- 3: usable as supporting or gallery material.
- 2: weak: dated, a draft, awkward framing, poor light, or redundant.
- 1: not usable: a test, blurry, blank, a screenshot, or a duplicate of a better piece.

Also flag issues: a watermark or another brand's logo in the corner, an obvious draft or "rough", low resolution, text typos you can see, a near-duplicate of another item, or people's faces in unflattering moments.

## What to write

Write your results to `/tmp/claude-0/-home-user-website/3166c4f1-956e-5ec8-ac6e-b1e29281e91b/scratchpad/reviews/<chunk-name>.json`. Write it incrementally: create the file after your first few sheets and rewrite it every ~10 sheets, so progress survives if your context gets long.

The file has this shape:

```json
{
  "chunk": "<chunk-name>",
  "videos": [
    {"id": "<id from chunk>", "score": 4, "type": "reel|ad|story|testimonial|talking-head|montage|event-recap|drone|b-roll|motion-graphic|interview|other",
     "orientation": "landscape|portrait|square",
     "summary": "One plain sentence: what the viewer sees.",
     "best_frame": 3,
     "placements": ["hero-loop", "case-study", "service:organic-social", "blog:<slug>", "cover", "gallery"],
     "hero_moment": "e.g. 0:12 drone reveal over patio (only if hero-loop is in placements)",
     "issues": ["watermark top-right"],
     "why": "One sentence on why it scores this way."}
  ],
  "folders": [
    {"folder_id": "<folder_id>", "raw": false, "score": 3,
     "summary": "One sentence: what the folder holds and its overall quality.",
     "best": [{"n": 12, "id": "<cell id>", "score": 5, "why": "short", "placements": ["cover", "case-study"]}],
     "issues": []}
  ],
  "takeaways": "3–5 sentences: the strongest material in this chunk that is NOT yet on the site, and where it should go."
}
```

Rules:
- `best_frame` is the 0-based index of the frame on the video's sheet that would make the best thumbnail.
- `ids` must be copied exactly from the chunk JSON. Never type an ID from memory.
- Give every video an entry. Give every folder an entry. For finished-photo folders, list the standout cells in `best`, up to 8 per folder, sorted by score, and only cells scoring 4 or 5. Raw folders get a one-line summary and at most 3 `best` cells, and only if something is genuinely standout (e.g. a hero-loop shot or a cover still).
- Be decisive and honest. Most material should score 2–3, and a 5 should be rare.
- Placements should be specific: name the service page or blog slug that the piece actually proves.
- Keep text short. The report shows these lines next to thumbnails.

When done, reply in at most 10 lines: the counts you scored, your top 5 unused picks (name, score, placement), and anything surprising.
