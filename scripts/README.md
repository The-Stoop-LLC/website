# Gallery build script

`build_galleries.py` regenerates inline image/video galleries on case study
pages by reading the contents of Google Drive folders. It replaces
the body of each `DRIVE_GALLERY` marker pair with `<img>` thumbnails (for
images) and `<iframe>` previews (for videos), using Drive's public
thumbnail and preview endpoints so we don't have to host the assets.

The script authenticates with a Google Cloud **service account** (more
robust than API keys, which have a habit of failing with cryptic
"INVALID_ARGUMENT" errors caused by silent restriction or project
mismatches).

## How a page declares a gallery

In any HTML file under the repo, drop a marker pair where the gallery
should render. The script finds them by regex.

```html
<h3>Showcase</h3>
<!-- DRIVE_GALLERY_START id=1__TY2uChBpUcNSQKGbW00CZQ8HignV9g label="Iron 24 Local Franchise - Showcase" -->
<!-- DRIVE_GALLERY_END -->
```

Attributes:

- `id` (required) - the Drive folder ID (the part after `/folders/` in the
  Drive URL).
- `label` (optional) - used as the `alt` text and iframe `title` prefix.
  Each generated tile gets a numeric suffix.
- `exclude` (optional) - comma-separated list of sub-folder names (case
  insensitive) to skip when recursing. Defaults to `Raw` so private
  "Raw" sub-folders inside a shared parent stay private. Override to add
  more, e.g. `exclude="Raw,Working,Originals"`.

The script **recurses into sub-folders** automatically (up to 10 levels
deep). Files from the entire tree are flattened, deduplicated by ID, and
sorted by name. So a folder organized like `Showcase/Photos/...` and
`Showcase/Videos/...` is rendered as a single combined gallery.

Anything between the two markers is overwritten on every run, so don't
hand-edit it. If the API call fails the script aborts before writing, so
you won't accidentally blank a page.

## One-time Google Cloud setup

You need a service account with the Drive API enabled.

1. Open [Google Cloud Console](https://console.cloud.google.com/) and
   create or select a project (e.g. `the-stoop-website`).
2. **APIs & Services -> Library**, search for "Google Drive API",
   click **Enable**.
3. **IAM & Admin -> Service Accounts -> + Create service account**.
   - Service account name: `website-galleries`
   - Service account ID: leave the auto-generated value
   - Description: "Reads Drive folders for the website gallery build script."
   - Click **Create and continue**, skip the "Grant access" step
     (no project roles needed - we grant access per-folder), click **Done**.
4. From the service accounts list, click the new
   `website-galleries@<project>.iam.gserviceaccount.com` row.
   - Switch to the **Keys** tab.
   - **Add Key -> Create new key -> JSON -> Create**.
   - A `.json` file downloads. Open it in a text editor; the entire
     contents (including the `{` and `}`) becomes the secret value below.
5. Note the service account **email** - it looks like
   `website-galleries@<project>.iam.gserviceaccount.com`. You'll use it
   in step 7.
6. Save the JSON file contents as a GitHub Actions secret on the
   `the-stoop-llc/website` repo:
   - Settings -> Secrets and variables -> Actions -> New repository secret
   - Name: `DRIVE_SA_KEY` (exactly that)
   - Secret: paste the entire JSON, including the outer `{...}` braces.
     No quotes around it. No trailing newline.
7. **For folders inside a Shared Drive**, also add the service account
   email as a member of that Shared Drive:
   - Open the Shared Drive in Drive
   - Click **Manage members** (top right)
   - Add the service account email (`website-galleries@<project>.iam.gserviceaccount.com`),
     role **Viewer**, **Notify** unchecked, click **Send**
   - This is required because Shared Drives don't honor folder-level
     "Anyone with the link" sharing for Drive API enumeration.
   The script automatically passes `supportsAllDrives=true` and
   `includeItemsFromAllDrives=true` on every API call so Shared Drive
   contents are returned.

8. Set each Drive folder referenced by a `DRIVE_GALLERY` marker to
   **"Anyone with the link -> Viewer"**:
   - Right-click the folder in Drive -> **Share** -> **Share**
   - Click **General access** in the lower section -> change from
     "Restricted" to **"Anyone with the link"**, role **Viewer**
   - Click **Done**

   This is required, not optional. The rendered page loads thumbnails
   from `https://drive.google.com/thumbnail?id=FILE_ID` directly from
   the visitor's browser - those URLs only resolve if the file is set
   to "Anyone with the link". Sharing only with the service account
   email lets the script enumerate, but the rendered page would still
   show broken images. Setting the parent folder to public also
   reliably cascades the permission to all current and future
   sub-folders, which sharing-by-email does not always do.

9. (Optional cleanup) If the previous `DRIVE_API_KEY` secret still
   exists, delete it from the repo secrets page.

## Running locally

```bash
cd /path/to/website
pip install -r scripts/requirements.txt
DRIVE_SA_KEY="$(cat /path/to/service-account.json)" python3 scripts/build_galleries.py
git diff           # review the regenerated HTML
git add -p         # commit the parts you want
```

The script prints one line per file it touched and a final summary. Exit
code is non-zero only if auth fails or a Drive API call fails.

## Running in CI

`.github/workflows/build-galleries.yml` runs the same script:

- on **manual dispatch** (Actions tab -> "Build Drive galleries" -> Run
  workflow), and
- **daily on a schedule** so newly added Drive files show up without a
  manual trigger.

The workflow commits the regenerated HTML back to `main` only if there's
a real diff, so it stays quiet when nothing changed.

## Adding a new gallery

1. Share the Drive folder with the service account email (Viewer).
2. Drop a marker pair into the relevant HTML page with the folder ID.
3. Either run the script locally and commit, or push the marker change
   and let the daily workflow pick it up (or trigger the workflow
   manually).

## Troubleshooting

- **`DRIVE_SA_KEY environment variable is required`** - the secret
  isn't set, or the env var isn't being passed to the step. Check
  `.github/workflows/build-galleries.yml` references
  `secrets.DRIVE_SA_KEY` and the secret exists at
  Settings -> Secrets and variables -> Actions.
- **`DRIVE_SA_KEY is not valid JSON`** - whatever was pasted into the
  secret isn't a complete JSON object. Re-download the key file from
  IAM -> Service Accounts -> Keys and paste the whole file contents
  (including the outer braces) verbatim.
- **HTTP 404 for a folder** - the service account doesn't have access
  to that folder. Share it with the service account email as Viewer.
- **HTTP 403 from the Drive API** - either the Drive API isn't enabled
  on the service account's project, or the service account is disabled.
  Check both in Google Cloud Console.
- **Empty gallery body, no error** - the folder (and all its non-excluded
  sub-folders) contained no images or videos, only Docs/Sheets/etc.
  Or every sub-folder is in the `exclude` list. The script recurses by
  default, so this usually means the source is empty rather than that
  the script ignored content.
- **HTTP 429** - rate limited. The script retries with backoff; if it
  still fails, slow the workflow schedule or batch fewer folders.
