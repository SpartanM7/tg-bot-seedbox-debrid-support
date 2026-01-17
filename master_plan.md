PROJECT NAME:
TG Bot – Seedbox + Real-Debrid + RSS + Google Drive

PROJECT MODE:
MAINTENANCE + EXTENSION (PRODUCTION SYSTEM)

ABSOLUTE NON-NEGOTIABLE RULES:

DO NOT remove, rename, refactor, or weaken ANY existing functionality.

DO NOT change file structure, module boundaries, or command names.

Existing behavior is production-critical.

ALL changes must be ADDITIVE or BUG-FIX ONLY.

Existing tests MUST continue to pass.

New features must be opt-in via config or environment variables.

If a change risks altering existing behavior, STOP and ASK.

No cleanup, simplification, or optimization unless explicitly requested.

FAILURE CONDITION:
If any existing working feature stops working, the solution is INVALID.

SYSTEM CONTEXT (LOCKED, DO NOT GUESS):

Redis:
Upstash Redis (hosted, TLS, latency-sensitive)

Telegram:
Single bot token
Telethon user session used for files < 2GB

Google Drive:
rclone-based integration (NOT OAuth, NOT Service Account)

Heroku:
Paid Eco dyno ($5 plan)

Auto-upload default:
Must be controlled via environment variable

RSS:
Unlimited feeds (private bot)

Task cancellation:
Command format: /cancel <task_id>

CURRENT ENVIRONMENT VARIABLES (MUST NOT BE RENAMED):

BOT_TOKEN
TELEGRAM_API_ID
TELEGRAM_API_HASH
TELEGRAM_PHONE
TELEGRAM_SESSION

RD_ACCESS_TOKEN
RD_ACCESS_TOKEN_TEST
RD_CLIENT_ID
RD_CLIENT_SECRET

RUTORRENT_URL
RUTORRENT_USER
RUTORRENT_PASS

REDIS_URL

DRIVE_DEST
MAX_ZIP_SIZE_BYTES

YTDL_MAX_RUNTIME
YTDL_CMD

RSS_POLL_INTERVAL
SFTP_PASS
LOG_LEVEL (optional)

PROJECT STRUCTURE (DO NOT MODIFY):

bot/main_bot.py
bot/downloader.py
bot/rss.py
bot/monitor.py
bot/state.py
bot/status_manager.py
bot/storage_queue.py
bot/telethon_uploader.py
bot/telegram_loop.py

bot/clients/realdebrid.py
bot/clients/seedbox.py

bot/utils/splitter.py
bot/utils/packager.py
bot/utils/system_info.py
bot/utils/thumbnailer.py

tests/ (ALL TESTS MUST CONTINUE TO PASS)

PHASE 1: CRITICAL FIXES (NO NEW FEATURES)

FIX 1: /rd_download COMMAND FAILING WITH RD API 400 WRONG_PARAMETER

Goal:
Fix Real-Debrid API usage without changing command behavior.

Rules:

Do NOT change the /rd_download command signature

Do NOT remove any existing parameters

Fix incorrect usage of deprecated or invalid parameters

Use compatibility logic instead of replacement

Add logging only, no behavior change

Likely cause:
Incorrect use of remote or remote_download parameter when calling RD unrestrict endpoint.

FIX 2: RSS COMMANDS NOT WORKING

Goal:
Restore RSS commands to working state.

Rules:

Do NOT redesign RSS system in this phase

Fix handler registration issues

Fix Redis key usage if broken

Commands must respond correctly

No auto-download in this phase

FIX 3: GOOGLE DRIVE UPLOAD NOT WORKING

Goal:
Restore Google Drive uploads using rclone exactly as before.

Rules:

Keep rclone-based approach

Do NOT switch to OAuth or Service Accounts

Fix path, permissions, or invocation issues

Existing tests must pass

PHASE 2: AUTO-UPLOAD CORE (ADDITIVE ONLY)

FEATURE 1: AUTO-UPLOAD ENGINE

Goal:
Automatically download and upload content added to:

Real-Debrid

Seedbox

Design:

Background watcher (new module only)

Poll RD torrents and seedbox torrents

Deduplicate using Redis

Route output based on environment variable

New ENV variables (OPTIONAL):
AUTO_UPLOAD_ENABLED=true|false
AUTO_UPLOAD_TARGET=telegram|gdrive

Rules:

Manual commands must continue working

Auto-upload must be disabled by default

No duplicate downloads allowed

PHASE 3: ADVANCED RSS SYSTEM (REDIS-BACKED)

FEATURE 2: RSS AUTOMATION WITH PER-FEED CONFIG

RSS Data Model (Redis):
rss:<id> contains:

feed_url

added_timestamp

telegram_channel_id

gdrive_destination

engine_preference (auto | rd | seedbox)

Rules:

Only download items published AFTER added_timestamp

No duplicate downloads

Manual polling supported

Routing logic:
If RD cached -> Real-Debrid
Else -> Seedbox

RSS must persist across restarts.

PHASE 4: TASK CANCELLATION

FEATURE 3: /cancel <task_id>

Cancelable tasks:

Real-Debrid downloads

Seedbox downloads

Telegram uploads

Google Drive uploads

Rules:

Every task must have a unique task_id

Cancellation state stored in Redis

Long-running loops must check cancellation flag

Cancellation must be graceful

PHASE 5: LIVE STATUS SYSTEM

FEATURE 4: AUTO-UPDATING STATUS MESSAGE

Status must show:

Real-Debrid torrents (hash, progress)

Seedbox torrents

Download progress (current / total)

Upload progress (current / total)

CPU usage

RAM usage

Disk used / free

Download and upload speeds

Task IDs for cancellation

Rules:

Only ONE active status message per user

Auto-update every 30 seconds

Older status messages must be deleted

/cancel <task_id> must work

PHASE 6: PERFORMANCE AND EXTENSIONS

FEATURE 5: TELEGRAM UPLOAD SPEED IMPROVEMENT

Approach:

Parallel chunk uploads

Telethon tuning inspired by WZML-X

Must respect Telegram limits

No API abuse

FEATURE 6: GOOGLE DRIVE UPLOAD AND DOWNLOAD

Add:

Google Drive -> Telegram

Google Drive -> Seedbox

Folder-level operations

Rules:

Existing GDrive upload behavior must remain unchanged

FEATURE 7: REAL-DEBRID STREAMING (NO LOCAL DOWNLOAD)

Goal:
Stream files directly from Real-Debrid to:

Telegram

Google Drive

Constraints:

RD does not allow cross-IP downloading

Must use RD-generated direct streaming links

Must support chunked streaming

No local disk storage

TESTING AND SAFETY RULES:

All existing tests must pass

New tests may be added, none removed

No environment variable renaming

No Redis key breaking changes

No file deletions

FINAL EXECUTION INSTRUCTIONS FOR ANY LLM:

Implement ONE phase at a time

Provide DROP-IN PATCHES only

No refactoring

No reformatting

Explicitly state what was added

Explicitly confirm nothing was removed

END FILE