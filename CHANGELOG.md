# Changelog

All notable changes to this project are documented in this file.

## [v1] - 2026-01-03
### Added
- Real‑Debrid HTTP client implementation (`bot/clients/realdebrid.py`)
- Seedbox client scaffold (`bot/clients/seedbox.py`)
- RSS processor and auto-routing (`bot/rss.py`)
- Telegram command scaffolding and handlers (`bot/telegram.py`)
- yt-dlp background job runner and queue (`bot/jobs.py`, `bot/queue.py`)
- Packager fixes: `dest` awareness, size limits, structured results (`bot/utils/packager.py`)
- Redis-backed job queue + cross-dyno lock fallback (`bot/queue.py`)
- Unit and integration test scaffolding (tests under `tests/`)

### Changed
- README updated with configuration and deployment instructions

### Notes
- RD integration test is present but skipped by default; set `RD_ACCESS_TOKEN_TEST` to run it.
- Cross-dyno locking uses Redis when `REDIS_URL` is provided; otherwise falls back to in-memory locks for local testing.
