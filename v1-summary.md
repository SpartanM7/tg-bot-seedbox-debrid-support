# Tg-Bot — v1 FINAL SUMMARY

This document defines the **v1 frozen architecture, behavior, and constraints**
of the WZML-X control-plane Telegram bot.

It is the **single source of truth** for:
- design intent
- supported features
- safety guarantees
- future optimization ideas

Use this file as context when:
- working in VS Code
- asking questions via ChatGPT extensions
- reviewing or extending the codebase

---

## 1. PROJECT GOAL (v1)

Tg-bo tis a **control-plane Telegram bot** that orchestrates downloads using
**external services only**.

The bot itself:
- does NOT perform torrent downloading
- does NOT act as a heavy downloader by default
- only coordinates, routes, post-processes, and uploads

All heavy lifting is delegated to:
- Real-Debrid
- Seedbox (Feral Hosting using rTorrent)
- yt-dlp (explicit, user-triggered only)

The bot is designed to be:
- Heroku-deployable
- deterministic
- explicit (no hidden behavior)
- power-user friendly

---

## 2. SUPPORTED BACKENDS (v1)

### 2.1 Real-Debrid
Used for:
- public torrents
- cached content
- supported direct download hosts

Capabilities:
- cache / instant availability check
- magnet submission
- direct HTTP downloads
- listing & deleting torrents/downloads

Constraints:
- never used for private torrents
- never auto-fallback to yt-dlp

---

### 2.2 Seedbox (Feral Hosting – rTorrent)
Used for:
- private torrents
- uncached public torrents
- unlimited traffic scenarios

Integration:
- ruTorrent / rTorrent XML-RPC (SCGI)
- same API Sonarr/Radarr use

Capabilities:
- add torrent
- list torrents
- stop/delete torrents
- download completed data via HTTP/FTP/SFTP

---

### 2.3 yt-dlp (Explicit Only)
Used ONLY when the user explicitly asks for it.

Important rules:
- no implicit fallback to yt-dlp
- bot returns an error if RD does not support a link
- user decides whether to run yt-dlp

Commands:
- /ytdl <url>
- /ytdl_gdrive <url>

Risk:
- user accepts Heroku restart risk
- this is a power-user feature

---

## 3. AUTO-ROUTING (RSS ONLY)

Auto-routing applies **only to RSS feeds**, not manual commands.

Routing decision (AUTO mode):
1. If backend is forced → use it
2. If torrent is private → seedbox
3. If public & cached on Real-Debrid → Real-Debrid
4. Else → seedbox

RSS feeds are configured **individually**, never globally.

---

## 4. COMMAND PHILOSOPHY (VERY IMPORTANT)

There are:
- NO global defaults
- NO implicit decisions

Everything is explicit via commands.

### Upload destination is command-based

Examples:
- /rd_torrent            → Telegram
- /rd_torrent_gdrive     → Google Drive
- /sb_torrent            → Telegram
- /sb_torrent_gdrive     → Google Drive
- /ytdl                  → Telegram
- /ytdl_gdrive           → Google Drive

This avoids:
- surprises
- hidden uploads
- unintended storage usage

---

## 5. FOLDER COMPRESSION (IMAGE/PIC RULE)

Compression is a **post-processing step**, backend-agnostic.

### Trigger
If a folder name contains (case-insensitive):
- pic
- pics
- image
- images

### Behavior
- folder is zipped before upload
- ZIP name = folder name

### Safety constraints
- ONLY ONE compression task at a time
- compression is serialized (queue/lock)
- avoids CPU spikes on Heroku

### Large folders
If folder is too large to safely zip:
- ZIP is skipped
- upload is allowed ONLY if destination is Google Drive
- Telegram upload is skipped
- folder structure is preserved on Drive

No silent fallback. Behavior is explicit.

---

## 6. DIRECT ZIP COMMANDS (v1)

The bot can zip folders **already present in Google Drive**.

Commands:
- /zip_telegram <gdrive_folder_link>
- /zip_gdrive <gdrive_folder_link>

Behavior:
- reads folder contents
- creates ZIP
- uploads ZIP to selected destination
- original folder remains untouched

---

## 7. FULL SERVICE CONTROL FROM TELEGRAM

### Real-Debrid
- /rd_torrents
- /rd_downloads
- /rd_delete <id>
- /rd_clear_all

### Seedbox (rTorrent)
- /sb_torrents
- /sb_stop <hash>
- /sb_delete <hash>
- /sb_files

No need to open service dashboards.

---

## 8. WHAT v1 INTENTIONALLY DOES NOT DO

These are **deliberate exclusions**, not missing features.

- no implicit yt-dlp usage
- no local torrent engine
- no background guessing of upload destination
- no parallel compression
- no automatic retries across backends
- no Sonarr/Radarr orchestration (yet)
- no per-user quota enforcement (yet)

---

## 9. HEROKU SAFETY ASSUMPTIONS

The bot is designed to survive Heroku constraints by:
- minimizing long-running CPU tasks
- serializing compression
- offloading downloads to external services
- keeping logic explicit and user-driven

yt-dlp is allowed only because:
- user explicitly triggers it
- user accepts instability risk

---

## 10. v1 IS FROZEN

This spec is **frozen**.

Changes from here must be:
- additive
- backward-compatible
- tracked as v2+

---

## 11. OPTIMIZATIONS & IMPROVEMENTS (v2+ IDEAS)

These are NOT implemented in v1.

### Backend & Routing
- Real-Debrid → Seedbox automatic fallback (opt-in)
- backend health checks
- per-backend quotas

### Automation
- Sonarr / Radarr orchestration
- RSS season pack intelligence
- episode-level deduplication

### Performance
- streaming uploads (no temp disk)
- async upload pipelines
- smarter ZIP size estimation

### UX
- inline Telegram menus
- progress dashboards
- per-command confirmations

### Reliability
- job persistence via MongoDB
- resume failed uploads
- retry policies

### Security
- role-based access (admin/user)
- command whitelisting
- encrypted token storage

---

## 12. GUIDING PRINCIPLES (DO NOT BREAK)

- Explicit > Implicit
- User control > Automation surprises
- Stability > Feature count
- Externalize heavy work
- One responsibility per layer

If a change violates these, it does not belong in this project.

---

END OF v1 SUMMARY
