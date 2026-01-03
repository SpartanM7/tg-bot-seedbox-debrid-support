
# WZML-X v1 FINAL

Explicit control-plane Telegram bot.

## Features
- **Real-Debrid**: Full API integration (Add magnet, List, Delete, Unrestrict Link).
- **Seedbox (rTorrent)**: Full XML-RPC control (Add, Stop, Start, Delete, List).
- **yt-dlp**: Explicit command support with persistent background job tracking.
- **RSS Automation**: Persistent feed tracking and auto-routing (Private->Seedbox, Cached->RD).
- **Explicit Control**: No auto-downloading loop; currently acts as a control-plane.
- **Persistence**: Redis-backed state (with local JSON fallback) for robust restarts.

## Configuration

Set the following environment variables (required / optional):

- `BOT_TOKEN` (required) — Telegram bot token
- `RD_ACCESS_TOKEN` (required for Real‑Debrid features) — personal access token
- `RD_ACCESS_TOKEN_TEST` (optional) — test token used by the integration test; keep separate from main token
- `RD_CLIENT_ID`, `RD_CLIENT_SECRET` (optional)
- `RUTORRENT_URL`, `RUTORRENT_USER`, `RUTORRENT_PASS` (required for seedbox features)
- `REDIS_URL` (optional) — if set, enables cross-dyno job storage and locks
- `MAX_ZIP_SIZE_BYTES` (optional) — max folder size before skipping zip for Telegram (default 100MB)
- `YTDL_MAX_RUNTIME` (optional) — yt-dlp runtime limit in seconds (default 600)

---

## Deployment (Heroku)

This app is designed for Heroku. Basic steps:

1. Install Heroku CLI and login: `heroku login`
2. Create an app: `heroku create your-app-name`
3. Add Redis if you want cross-dyno locks and job persistence:
   - `heroku addons:create heroku-redis:hobby-dev`
   - The addon sets `REDIS_URL` automatically
4. Set required config vars:
   - `heroku config:set BOT_TOKEN=xxx RD_ACCESS_TOKEN=yyy RUTORRENT_URL=... RUTORRENT_USER=... RUTORRENT_PASS=...`
5. Push to Heroku:
   - `git push heroku main` (or `master` depending on your branch)
6. Scale dynos if necessary (web process is defined in `Procfile`):
   - `heroku ps:scale web=1`

Notes & tips:

- Heroku has ephemeral filesystem — rely on external services (RD, seedbox, Google Drive) for persistent storage.
- yt-dlp and compression can be CPU and time intensive; prefer Google Drive uploads for large folders.
- The app is conservative by default: yt-dlp runs only when explicitly requested (`/ytdl`).

---

## Running tests

- Unit tests: `python -m unittest discover -s tests -v`
- RD integration test (skipped unless `RD_ACCESS_TOKEN_TEST` is set):
  - `RD_ACCESS_TOKEN_TEST=your_test_token python -m unittest tests.test_realdebrid_integration -v`

---

## CHANGELOG
See `CHANGELOG.md` for a summary of changes in v1.

