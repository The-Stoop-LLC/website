# Gallery build script

`build_galleries.py` regenerates inline image/video galleries on case study
pages by reading the contents of public Google Drive folders. It replaces
the body of each `DRIVE_GALLERY` marker pair with `<img>` thumbnails (for
images) and `<iframe>` previews (for videos), using Drive's public
thumbnail and preview endpoints so we don't have to host the assets.

## How a page declares a gallery

In any HTML file under the repo, drop a marker pair where the gallery
should render. The script finds them by regex.

```html
<h3>Gym Tour</h3>
<!-- DRIVE_GALLERY_START id=1xlgNfMgYb6-tijjnjIvJkNFXCWSAjGm7 label="Iron 24 Local Franchise - Gym Tour" -->
<!-- DRIVE_GALLERY_END -->
```

Attributes:

- `id` (required) - the Drive folder ID (the part after `/folders/` in the
  Drive URL).
- `label` (optional) - used as the `alt` text and iframe `title` prefix.
  Each generated tile gets a numeric suffix.

Anything between the two markers is overwritten on every run, so don't
hand-edit it. If the API call fails the script aborts before writing, so
you won't accidentally blank a page.

## One-time Google Cloud setup

You need a Drive API key. Steps:

1. Open [Google Cloud Console](https://console.cloud.google.com/) and
   create (or select) a project.
2. **APIs & Services -> Library**, search for "Google Drive API",
   click **Enable**.
3. **APIs & Services -> Credentials -> + Create Credentials -> API key**.
   Copy the key.
4. Click the key, then under **API restrictions** restrict it to "Google
   Drive API" so it can't be misused if it leaks. Optionally add an
   application restriction (HTTP referrers or IPs).
5. Save the key as a GitHub Actions secret named `DRIVE_API_KEY` on the
   `the-stoop-llc/website` repo (Settings -> Secrets and variables ->
   Actions -> New repository secret).

Each Drive folder you reference in a marker must be shared as
**"Anyone with the link -> Viewer"**. The script only sees what an
unauthenticated public visitor would see.

## Running locally

```bash
cd /path/to/website
pip install -r scripts/requirements.txt
DRIVE_API_KEY=ya29.your-key python3 scripts/build_galleries.py
git diff           # review the regenerated HTML
git add -p         # commit the parts you want
```

The script prints one line per file it touched and a final summary. Exit
code is non-zero only if the API call fails or the env var is missing.

## Running in CI

`.github/workflows/build-galleries.yml` runs the same script:

- on **manual dispatch** (Actions tab -> "Build Drive galleries" -> Run
  workflow), and
- **daily on a schedule** so newly added Drive files show up without a
  manual trigger.

The workflow commits the regenerated HTML back to `main` only if there's
a real diff, so it stays quiet when nothing changed.

## Adding a new gallery

1. Share the Drive folder as "Anyone with the link -> Viewer".
2. Drop a marker pair into the relevant HTML page with the folder ID.
3. Either run the script locally and commit, or push the marker change
   and let the daily workflow pick it up (or trigger the workflow
   manually).

## Troubleshooting

- **"You need access" inside an iframe** - the source folder isn't
  shared publicly. Re-share with "Anyone with the link -> Viewer".
- **Empty gallery body, no error** - the folder has no images or videos
  (only sub-folders, Docs, etc.). Sub-folders are intentionally skipped
  so you can keep "Raw" or "Working" sub-folders private inside a shared
  parent.
- **HTTP 403 from the Drive API** - either the API key isn't enabled for
  the Drive API, or it has a referrer restriction that blocks GitHub
  Actions runners. Loosen the restriction or re-enable Drive API on the
  key.
- **HTTP 429** - rate limited. The script retries with backoff; if it
  still fails, slow the workflow schedule or batch fewer folders.
