# The Stoop — website

Marketing site for The Stoop, a Pittsburgh digital advertising and influencer
marketing agency: **[thestooppgh.com](https://thestooppgh.com)**.

Plain HTML, CSS and JavaScript. No build step, no framework.

## Deploy

Every push to `main` deploys to GitHub Pages through
`.github/workflows/deploy-pages.yml` (about a minute). GitHub Pages serves
`/contact` from `contact.html`, so extensionless links work. A finished
"Build Drive galleries" run also triggers a deploy, since the commits it
pushes don't count as pushes.

After changing `assets/css/site.css` or `assets/js/site.js`, bump the `?v=`
on every page's `<link>`/`<script>` so browsers fetch the new file.

## Layout

| Path | What it is |
|---|---|
| `index.html` | Homepage |
| `contact.html` | The only contact page and inquiry form (`/contact`) |
| `services/*.html` | One page per service; buttons link to `/contact?service=<slug>` |
| `services/thank-you/*.html` | Post-submit pages, one per service (noindex) |
| `services/contact.html` | Forwards old links to `/contact` |
| `work/` | Case study index and case studies |
| `blog/` | Blog index, posts, `feed.xml` |
| `founder`, `faq`, `pricing`, `process`, `reviews`, `policy`, `404` | Other pages |
| `assets/css/site.css`, `assets/js/site.js` | Shared styles and behavior |
| `assets/js/contact.js` | Contact form behavior |
| `assets/images/covers/` | Case study covers, JPEG + WebP, 800px and 1600px |
| `assets/images/drive/` | Photos copied from Google Drive, with WebP thumbnails in `thumbs/` |
| `sitemap.xml`, `robots.txt`, `llms.txt`, `llms-full.txt` | Search and AI crawlers |
| `scripts/` | Maintenance scripts (below) |

## Contact form and leads

`/contact` is a native HTML form. GoHighLevel's External Tracking script
(on every page, loaded before `site.js`) captures the submit and creates
the contact in GHL; fields are mapped to GHL contact fields in GHL.

- Required: first name, last name, email, phone, service. Optional:
  motivation, how they found us, and "Other" details.
- **Dropdown values must match the GHL custom field options exactly**
  (e.g. "Website Design & Development"), or GHL drops the value.
- `?service=<slug>` pre-selects the service; after submitting, the visitor
  goes to `services/thank-you/<slug>.html` ("Other" uses `contact.html`).
- Each thank-you page fires the GA4 `generate_lead` event once per session.
- If GHL's script can't load (e.g. an ad blocker), the form shows the
  email/phone fallback instead of submitting.

## Analytics

GA4 (`G-L3QFSMDD86`) with Consent Mode v2 defaults (storage denied for
EEA/UK/Swiss visitors, granted elsewhere), plus a GTM container
(`GTM-PWLD85D9`, empty for now). Don't add a GA4 tag for the same ID in GTM:
pageviews would count twice.

## Scripts

| Script | When to run |
|---|---|
| `scripts/build_galleries.py` | Rebuilds case study galleries from Drive folders (the "Build Drive galleries" GitHub Action; manual trigger). See `scripts/README.md`. |
| `scripts/localize_drive_images.py` | Copies Drive-hosted images and video posters into the repo (runs in that Action). |
| `scripts/make_thumbs.py` | Builds WebP thumbnails for gallery tiles (runs in that Action). |
| `scripts/gallery_alt.json` | Hand-written alt text for gallery photos, keyed by Drive file id. |
| `scripts/hero_loop.json` | The homepage background video's cut list (Drive file, start, length, crop anchors). Edit it on a branch and push: the "Build hero loop" Action downloads the clips, rebuilds `assets/video/` and commits it to that branch. Its `scout` list writes contact sheets to `_scout/` for picking shots; empty it before merging. |
| `scripts/sitemap_lastmod.py --write` | After content changes: sets each sitemap `<lastmod>` from the page's schema dates and lists its images. |

## Brand

True black, white and Tangerine Yellow (`#FFCC00`). Fonts are self-hosted:
Anton for headlines, Outfit for body text.
