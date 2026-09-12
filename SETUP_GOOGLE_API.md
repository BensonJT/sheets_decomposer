# Google Sheets API setup (personal account, ~15 minutes, once)

Two credential styles. **Start with OAuth** (it reads anything your own Google account can open). Add a service account later if you want headless runs.

Neither requires a paid GCP account. Sheets/Drive API calls are free within quota (300 read requests per minute per project; one `ingest` = 2 requests).

## A. OAuth desktop client (recommended first)

1. Open https://console.cloud.google.com/ signed in as the Google account that the sheets are shared with.
2. Top bar → project picker → **New project** → name `sheets-decomposer` → Create → select it.
3. **APIs & Services → Library**: search **Google Sheets API** → Enable. Search **Google Drive API** → Enable. (Drive is only for owner / modified-time metadata; the tool degrades gracefully without it.)
4. **APIs & Services → OAuth consent screen** (Google now calls this "Google Auth Platform → Branding/Audience"):
   - User type **External** → Create.
   - App name `sheets-decomposer`, your email for support and developer contact. Save.
   - **Audience → Publishing status: Testing.** Add your own Gmail address under **Test users**. Testing mode is fine forever for one user; tokens expire after 7 days in testing mode, so you will re-consent in the browser about once a week. That is a single click.
   - Scopes: nothing to add here; the app requests them at runtime.
5. **APIs & Services → Credentials → + Create credentials → OAuth client ID**:
   - Application type **Desktop app**, name `sheets-decomposer-cli` → Create.
   - **Download JSON** → save it as `~/.config/sheets_decomposer/credentials.json` (in WSL: `mkdir -p ~/.config/sheets_decomposer` then copy from `/mnt/c/Users/Jeffrey Benson/Downloads/client_secret_….json`).
6. First run:
   ```bash
   cd ~/code/sheets_decomposer
   ./sd ingest "https://docs.google.com/spreadsheets/d/<ID>/edit"
   ```
   A browser tab opens (in WSL it may print the URL instead; paste it into Windows Chrome). Choose the account, click through the "Google hasn't verified this app" warning (Advanced → Go to sheets-decomposer) since you are the developer, allow the two read-only scopes. The token caches to `~/.config/sheets_decomposer/token.json`; later runs are silent.

Scopes requested: `spreadsheets.readonly` and `drive.metadata.readonly`. Nothing is written. If a write scope is ever needed, `auth.py` has `SCOPES_RW`; delete `token.json` to re-consent.

## B. Service account (headless; share-the-sheet model)

1. Same project → **IAM & Admin → Service Accounts → + Create service account** → name `sheets-reader` → Create and continue → skip roles → Done.
2. Click the account → **Keys → Add key → Create new key → JSON** → save as `~/.config/sheets_decomposer/service_account.json`.
3. Copy the service account's email (`sheets-reader@sheets-decomposer-….iam.gserviceaccount.com`).
4. In the target Google Sheet → **Share** → paste that email → Viewer. This is the whole trick: the service account is just another "user" you share with.
5. Run with `./sd ingest <url> --auth service`.

Enterprise note: in a corporate Workspace, org policy usually blocks key creation (`iam.disableServiceAccountKeyCreation`) and a Workspace admin must trust the app for Sheets scopes. Ask for keyless auth (workload identity or Application Default Credentials) by name, and start extracting in Apps Script the same day so the approval clock never blocks the work. On a personal account none of that applies.

## C. No credentials at all (works tonight)

- **Link-shared sheet:** Share → "Anyone with the link" → Viewer, then `./sd ingest <url> --auth export`. The tool downloads the xlsx export; formulas survive the export.
- **Any .xlsx file:** `./sd ingest path/to/file.xlsx`. If a workbook arrives as an Excel attachment, this is the path. Cached values are present if the file was last saved by Excel or Sheets.

## Where things live

| Item | Path |
|---|---|
| OAuth client | `~/.config/sheets_decomposer/credentials.json` |
| Cached token | `~/.config/sheets_decomposer/token.json` |
| Service account key | `~/.config/sheets_decomposer/service_account.json` |
| Overrides | `.env` (see `.env.example`) |

All three are gitignored. Never commit them anywhere.

## Troubleshooting

- `Access blocked: sheets-decomposer has not completed the Google verification process` → your email is not in Test users (step 4).
- `invalid_grant` / `Token has been expired or revoked` → delete `token.json` and rerun (weekly in testing mode).
- `403 The caller does not have permission` with a service account → the sheet was not shared with the SA email.
- Browser does not open from WSL → copy the printed `http://localhost:…` URL into Windows Chrome; the callback still reaches WSL.
- `HttpError 429` → quota; wait a minute. One ingest is two calls, so this only happens in loops.

## D. Pushing to the Gem's knowledge Docs (added 2026-09-11)

The Gem reads two Google Docs (`gem_context` and `report`) linked as knowledge. Drive-linked knowledge is read live, so overwriting the Docs updates the Gem with no re-upload.

1. **APIs & Services → Library → Google Docs API → Enable** (one click, same project).
2. The tool now requests the `documents` scope. Delete the old token so it can re-consent once:
   ```bash
   rm ~/.config/sheets_decomposer/token.json
   ```
3. Doc URLs live in `.env` (`SD_GEM_CONTEXT_DOC`, `SD_REPORT_DOC`). Then either:
   ```bash
   ./sd push-docs out/sample_calls_chats                 # push what is on disk
   ./sd ingest "<sheet url>" --push-docs                 # ingest and push in one go
   ```
Markdown lands as plain text in the Doc, which is what the Gem reads anyway. The Docs are wiped and rewritten on every push; do not hand-edit them.
