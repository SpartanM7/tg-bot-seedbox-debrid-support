#!/usr/bin/env python3
"""
Unified Telegram bot for managing torrents via Real-Debrid and Seedbox.
Handles RSS feeds with smart polling and caching.
V13 COMPATIBLE - No async/await in handlers
"""

import os
import sys
import logging
import time
import threading
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    Filters,
    CallbackContext,
)

# Import bot modules
from bot.clients.realdebrid import RDClient
from bot.clients.seedbox import SeedboxClient
from bot.monitor import Monitor
from bot.downloader import Downloader
from bot.state import get_state
from bot.status_manager import StatusManager
from bot.rss import RSSManager

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Environment variables - WITH TOKEN SANITIZATION
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
# Strip any whitespace, quotes, or hidden characters from token
if TOKEN:
    TOKEN = TOKEN.strip().strip('"').strip("'").strip()
    logger.info(f"Bot token loaded: {TOKEN[:10]}...{TOKEN[-4:]}")

ALLOWED_USERS = [int(uid) for uid in os.getenv("ALLOWED_USER_IDS", "").split(",") if uid.strip()]
RD_API_KEY = os.getenv("RD_ACCESS_TOKEN")
SB_HOST = os.getenv("SEEDBOX_HOST")
SB_USER = os.getenv("RUTORRENT_USER")
SB_PASS = os.getenv("RUTORRENT_PASS") or os.getenv("SFTP_PASS")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID") or os.getenv("DRIVE_DEST")
TG_UPLOAD_TARGET = os.getenv("TG_UPLOAD_TARGET")

# Initialize clients with error handling
try:
    rd_client = RDClient(RD_API_KEY) if RD_API_KEY else None
    if rd_client:
        logger.info("✅ Real-Debrid client initialized")
except Exception as e:
    logger.warning(f"⚠️ Real-Debrid not configured: {e}")
    rd_client = None

try:
    sb_client = SeedboxClient() if all([SB_USER, SB_PASS]) else None
    if sb_client:
        logger.info("✅ Seedbox client initialized")
except Exception as e:
    logger.warning(f"⚠️ Seedbox not configured: {e}")
    sb_client = None

state_manager = get_state()
status_manager = StatusManager()
downloader = Downloader()

# RSS Configuration
RSS_POLL_INTERVAL = int(os.getenv("RSS_POLL_INTERVAL", "900"))
RSS_UPLOAD_DEST = os.getenv("RSS_UPLOAD_DEST", "gdrive")
RSS_API_DELAY = float(os.getenv("RSS_API_DELAY", "2.0"))
RSS_DELETE_AFTER_UPLOAD = os.getenv("RSS_DELETE_AFTER_UPLOAD", "false").lower() == "true"

rss_manager = RSSManager(
    rd_client=rd_client,
    sb_client=sb_client,
    state_manager=state_manager,
    upload_dest=RSS_UPLOAD_DEST,
    api_delay=RSS_API_DELAY,
    default_chat_id=TG_UPLOAD_TARGET,
    delete_after_upload=RSS_DELETE_AFTER_UPLOAD
)

# Initialize monitor
monitor = Monitor(
    downloader=downloader,
    rd_client=rd_client,
    sb_client=sb_client
)


def check_auth(user_id: int) -> bool:
    """Check if user is authorized"""
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


def start(update: Update, context: CallbackContext):
    """Start command"""
    if not check_auth(update.effective_user.id):
        update.message.reply_text("❌ Unauthorized")
        return

    msg = (
        "🤖 *Torrent Bot*\n\n"
        "*Commands:*\n"
        "📥 Send magnet/torrent file\n"
        "/status \- Active downloads\n\n"
        "*RSS Feeds:*\n"
        "/add\_feed \- Add RSS feed\n"
        "/list\_feeds \- List RSS feeds\n"
        "/poll\_feeds \- Force RSS poll\n"
        "/remove\_feed \- Remove RSS feed\n"
        "/rss\_stats \- View RSS statistics\n"
        "/rss\_failed \- View failed items"
    )

    update.message.reply_text(msg, parse_mode="MarkdownV2")


def handle_magnet(update: Update, context: CallbackContext):
    """Handle magnet link or torrent file"""
    if not check_auth(update.effective_user.id):
        update.message.reply_text("❌ Unauthorized")
        return

    user_id = update.effective_user.id
    message = update.message

    # Extract magnet or torrent
    magnet = message.text if message.text and message.text.startswith("magnet:") else None
    torrent_file = None

    if message.document and message.document.file_name.endswith(".torrent"):
        file = context.bot.get_file(message.document.file_id)
        torrent_file = file.download_as_bytearray()

    if not magnet and not torrent_file:
        message.reply_text("❌ Please send a magnet link or .torrent file")
        return

    # Ask for service selection
    keyboard = [
        [
            InlineKeyboardButton("🚀 Real-Debrid", callback_data=f"service:rd:{magnet or 'file'}"),
            InlineKeyboardButton("📦 Seedbox", callback_data=f"service:sb:{magnet or 'file'}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message.reply_text("Select service:", reply_markup=reply_markup)

    # Store torrent file in context
    if torrent_file:
        context.user_data["pending_torrent"] = torrent_file


def handle_service_selection(update: Update, context: CallbackContext):
    """Handle service selection callback"""
    query = update.callback_query
    query.answer()

    if not check_auth(query.from_user.id):
        query.edit_message_text("❌ Unauthorized")
        return

    data = query.data.split(":", 2)
    service = data[1]
    magnet = data[2] if data[2] != "file" else None

    # Ask for upload destination
    keyboard = [
        [
            InlineKeyboardButton("☁️ Google Drive", callback_data=f"dest:{service}:gdrive:{magnet or 'file'}"),
            InlineKeyboardButton("📱 Telegram", callback_data=f"dest:{service}:telegram:{magnet or 'file'}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    query.edit_message_text("Upload to:", reply_markup=reply_markup)


def handle_destination_selection(update: Update, context: CallbackContext):
    """Handle upload destination selection"""
    query = update.callback_query
    query.answer()

    if not check_auth(query.from_user.id):
        query.edit_message_text("❌ Unauthorized")
        return

    data = query.data.split(":", 3)
    service = data[1]
    destination = data[2]
    magnet = data[3] if data[3] != "file" else None
    torrent_file = context.user_data.get("pending_torrent")

    user_id = query.from_user.id
    chat_id = query.message.chat_id

    # Validate chat_id for Telegram uploads
    upload_chat_id = None
    if destination == "telegram":
        upload_chat_id = TG_UPLOAD_TARGET if TG_UPLOAD_TARGET else str(chat_id)
        if not upload_chat_id:
            query.edit_message_text("❌ No Telegram chat configured for uploads")
            return

    query.edit_message_text("⏳ Processing...")

    try:
        # Add torrent
        if service == "rd":
            if not rd_client:
                query.edit_message_text("❌ Real-Debrid not configured")
                return

            if magnet:
                result = rd_client.add_magnet(magnet)
            else:
                query.edit_message_text("❌ .torrent file upload to Real-Debrid requires URL")
                return

            torrent_id = result.get("id")
            try:
                rd_client.select_files(torrent_id, "all")
            except Exception as e:
                logger.warning(f"Could not auto-select files: {e}")

            query.edit_message_text(f"✅ Added to Real\-Debrid\nID: `{torrent_id}`", parse_mode="MarkdownV2")
            state_manager.add_intent(f"rd:{torrent_id}", destination)

        elif service == "sb":
            if not sb_client:
                query.edit_message_text("❌ Seedbox not configured")
                return

            if magnet:
                result = sb_client.add_torrent(magnet)
            else:
                query.edit_message_text("❌ .torrent file upload to seedbox requires URL")
                return

            query.edit_message_text(f"✅ Added to Seedbox", parse_mode="MarkdownV2")

    except Exception as e:
        logger.error(f"Error adding torrent: {e}", exc_info=True)
        query.edit_message_text(f"❌ Error: {str(e)}")
    finally:
        context.user_data.pop("pending_torrent", None)


def status(update: Update, context: CallbackContext):
    """Show active torrents status"""
    if not check_auth(update.effective_user.id):
        update.message.reply_text("❌ Unauthorized")
        return

    tasks = downloader.get_active_tasks()

    if not tasks:
        update.message.reply_text("📭 No active downloads")
        return

    status_lines = ["📊 *Active Downloads:*\n"]

    for task_id, task_info in tasks.items():
        name = task_info.get("name", "Unknown")
        status_str = task_info.get("status", "unknown")
        progress = task_info.get("progress_percent", 0)
        uploaded = task_info.get("uploaded_files", 0)
        total = task_info.get("total_files", 0)

        name_escaped = name[:30].replace("_", "\_").replace("*", "\*").replace("[", "\[").replace("]", "\]")
        status_escaped = status_str.replace("_", "\_")

        status_lines.append(f"📁 *{name_escaped}*")
        status_lines.append(f"   Status: {status_escaped}")

        if total > 0:
            status_lines.append(f"   Files: {uploaded}/{total}")
        if progress > 0:
            status_lines.append(f"   Progress: {progress:.1f}%")

        status_lines.append("")

    status_text = "\n".join(status_lines)
    update.message.reply_text(status_text, parse_mode="MarkdownV2")


# ==================== RSS COMMANDS ====================

def cmd_add_feed(update: Update, context: CallbackContext):
    """Add RSS feed command"""
    if not check_auth(update.effective_user.id):
        update.message.reply_text("❌ Unauthorized")
        return

    args = context.args
    if not args:
        msg = (
            "Usage: `/add_feed <url> [service] [private] [delete]`\n\n"
            "Examples:\n"
            "`/add_feed https://example\.com/rss`\n"
            "`/add_feed https://example\.com/rss rd`\n"
            "`/add_feed https://example\.com/rss sb true`\n"
            "`/add_feed https://example\.com/rss sb false true`"
        )
        update.message.reply_text(msg, parse_mode="MarkdownV2")
        return

    url = args[0]
    service = args[1] if len(args) > 1 else None
    private = args[2].lower() == "true" if len(args) > 2 else False
    delete_after_upload = args[3].lower() == "true" if len(args) > 3 else RSS_DELETE_AFTER_UPLOAD

    try:
        rss_manager.add_feed(url, service=service, private_torrent=private, delete_after_upload=delete_after_upload)

        service_text = service if service else "auto"
        delete_text = "✅" if delete_after_upload else "❌"

        update.message.reply_text(
            f"✅ Added RSS feed\n"
            f"Service: {service_text}\n"
            f"Delete after upload: {delete_text}",
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        logger.error(f"Error adding feed: {e}", exc_info=True)
        update.message.reply_text(f"❌ Error: {str(e)}")


def cmd_list_feeds(update: Update, context: CallbackContext):
    """List all RSS feeds"""
    if not check_auth(update.effective_user.id):
        update.message.reply_text("❌ Unauthorized")
        return

    feeds = rss_manager.list_feeds()

    if not feeds:
        update.message.reply_text("📭 No RSS feeds configured")
        return

    lines = ["📰 *RSS Feeds:*\n"]
    for i, feed in enumerate(feeds, 1):
        url = feed["url"][:50]
        service = feed.get("service", "auto")
        delete = "🗑" if feed.get("delete_after_upload", False) else ""
        lines.append(f"{i}\. {service} {delete}")

    text = "\n".join(lines)
    update.message.reply_text(text, parse_mode="MarkdownV2")


def cmd_poll_feeds(update: Update, context: CallbackContext):
    """Manually poll all RSS feeds"""
    if not check_auth(update.effective_user.id):
        update.message.reply_text("❌ Unauthorized")
        return

    update.message.reply_text("🔄 Polling RSS feeds...")

    try:
        new_items = rss_manager.poll_feeds()

        if new_items == 0:
            update.message.reply_text("✅ No new items found")
        else:
            update.message.reply_text(f"✅ Found {new_items} new item(s)")
    except Exception as e:
        logger.error(f"Error polling feeds: {e}", exc_info=True)
        update.message.reply_text(f"❌ Error: {str(e)}")


def cmd_remove_feed(update: Update, context: CallbackContext):
    """Remove RSS feed command"""
    if not check_auth(update.effective_user.id):
        update.message.reply_text("❌ Unauthorized")
        return

    args = context.args
    if not args:
        msg = "Usage: `/remove_feed <index>`\n\nExample: `/remove_feed 1`"
        update.message.reply_text(msg, parse_mode="MarkdownV2")
        return

    identifier = " ".join(args)

    try:
        if identifier.isdigit():
            index = int(identifier) - 1
            feeds = rss_manager.list_feeds()
            if 0 <= index < len(feeds):
                url = feeds[index]["url"]
                rss_manager.remove_feed(url)
                update.message.reply_text(f"✅ Removed feed \#{index + 1}", parse_mode="MarkdownV2")
            else:
                update.message.reply_text("❌ Invalid feed index")
        else:
            rss_manager.remove_feed(identifier)
            update.message.reply_text(f"✅ Removed feed", parse_mode="MarkdownV2")

    except Exception as e:
        logger.error(f"Error removing feed: {e}", exc_info=True)
        update.message.reply_text(f"❌ Error: {str(e)}")


def cmd_rss_stats(update: Update, context: CallbackContext):
    """View RSS feed statistics"""
    if not check_auth(update.effective_user.id):
        update.message.reply_text("❌ Unauthorized")
        return

    feeds = rss_manager.list_feeds()

    if not feeds:
        update.message.reply_text("📭 No RSS feeds configured")
        return

    lines = ["📊 *RSS Feed Statistics:*\n"]

    for i, feed in enumerate(feeds, 1):
        url = feed["url"]
        stats = state_manager.get_rss_feed_stats(url)

        lines.append(f"*Feed {i}:*")
        lines.append(f"✅ Uploaded: {stats['uploaded']}")
        lines.append(f"⬇️ Downloading: {stats['downloading']}")
        lines.append(f"⬆️ Uploading: {stats['uploading']}")
        lines.append(f"❌ DL Failed: {stats['download_failed']}")
        lines.append(f"❌ UP Failed: {stats['upload_failed']}")
        lines.append(f"📦 Total: {stats['total']}\n")

    text = "\n".join(lines)
    update.message.reply_text(text, parse_mode="MarkdownV2")


def cmd_rss_failed(update: Update, context: CallbackContext):
    """View failed RSS items"""
    if not check_auth(update.effective_user.id):
        update.message.reply_text("❌ Unauthorized")
        return

    download_failed = state_manager.list_rss_items_by_status("download_failed")
    upload_failed = state_manager.list_rss_items_by_status("upload_failed")

    if not download_failed and not upload_failed:
        update.message.reply_text("✅ No failed items")
        return

    lines = ["❌ *Failed RSS Items:*\n"]

    if download_failed:
        lines.append("*Download Failed:*")
        for item in download_failed[:10]:  # Limit to 10
            title = item.get("title", "Unknown")[:40]
            error = item.get("error", "Unknown error")[:30]
            title_escaped = title.replace("_", "\_").replace("*", "\*")
            error_escaped = error.replace("_", "\_")
            lines.append(f"\- {title_escaped}")
            lines.append(f"  Error: {error_escaped}\n")

    if upload_failed:
        lines.append("*Upload Failed:*")
        for item in upload_failed[:10]:  # Limit to 10
            title = item.get("title", "Unknown")[:40]
            error = item.get("error", "Unknown error")[:30]
            title_escaped = title.replace("_", "\_").replace("*", "\*")
            error_escaped = error.replace("_", "\_")
            lines.append(f"\- {title_escaped}")
            lines.append(f"  Error: {error_escaped}\n")

    text = "\n".join(lines)
    update.message.reply_text(text, parse_mode="MarkdownV2")


# ==================== BACKGROUND TASKS ====================

def rss_poll_loop():
    """Background task to poll RSS feeds periodically (runs in thread)"""
    logger.info(f"Starting RSS poll loop (interval={RSS_POLL_INTERVAL}s)")

    while True:
        try:
            time.sleep(RSS_POLL_INTERVAL)
            new_items = rss_manager.poll_feeds()
            if new_items > 0:
                logger.info(f"RSS poll found {new_items} new item(s)")
        except Exception as e:
            logger.error(f"Error in RSS poll loop: {e}", exc_info=True)


def start_background_tasks():
    """Start background polling threads"""
    # Start monitor (has its own threading)
    monitor.start()

    # Start RSS polling thread
    rss_thread = threading.Thread(target=rss_poll_loop, daemon=True)
    rss_thread.start()

    logger.info("✅ Background tasks started")
    logger.info(f"📰 RSS auto-polling (interval: {RSS_POLL_INTERVAL}s)")
    logger.info(f"📤 RSS upload: {RSS_UPLOAD_DEST}")
    logger.info(f"⏱ API delay: {RSS_API_DELAY}s")


def main():
    """Start the bot"""
    if not TOKEN:
        logger.error("❌ BOT_TOKEN or TELEGRAM_BOT_TOKEN not set in Heroku config")
        logger.error("Run: heroku config:set BOT_TOKEN=your_token_here")
        return

    # Validate token format
    if not TOKEN or ":" not in TOKEN:
        logger.error("❌ Invalid BOT_TOKEN format. Should be: XXXXXXXXXX:XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
        logger.error(f"Current token format: {TOKEN[:20] if TOKEN else 'None'}...")
        return

    logger.info(f"Using python-telegram-bot v13")
    logger.info(f"Bot token: {TOKEN[:10]}...{TOKEN[-4:]}")
    logger.info(f"Token length: {len(TOKEN)} chars (should be ~45)")

    try:
        logger.info(f"🔧 Initializing Updater with token...")
        updater = Updater(TOKEN, use_context=True)
        dp = updater.dispatcher

        # Add handlers
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("status", status))
        dp.add_handler(CommandHandler("add_feed", cmd_add_feed))
        dp.add_handler(CommandHandler("list_feeds", cmd_list_feeds))
        dp.add_handler(CommandHandler("poll_feeds", cmd_poll_feeds))
        dp.add_handler(CommandHandler("remove_feed", cmd_remove_feed))
        dp.add_handler(CommandHandler("rss_stats", cmd_rss_stats))
        dp.add_handler(CommandHandler("rss_failed", cmd_rss_failed))

        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_magnet))
        dp.add_handler(MessageHandler(Filters.document, handle_magnet))

        dp.add_handler(CallbackQueryHandler(handle_service_selection, pattern="^service:"))
        dp.add_handler(CallbackQueryHandler(handle_destination_selection, pattern="^dest:"))

        # Start background tasks
        start_background_tasks()

        logger.info("🚀 Bot started (v13)")
        updater.start_polling()
        updater.idle()

    except Exception as e:
        logger.error(f"❌ Failed to initialize bot: {e}")
        logger.error(f"Token being used: {TOKEN[:15]}...{TOKEN[-6:]}")
        logger.error("Please verify your BOT_TOKEN with BotFather")
        raise


if __name__ == "__main__":
    main()
