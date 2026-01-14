#!/usr/bin/env python3
"""
V13-Compatible bot with diagnostic logging to debug command handling
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
if TOKEN:
    TOKEN = TOKEN.strip().strip('"').strip("'").strip()
    logger.info(f"Bot token loaded: {TOKEN[:10]}...{TOKEN[-4:]}")

ALLOWED_USERS = [int(uid) for uid in os.getenv("ALLOWED_USER_IDS", "").split(",") if uid.strip()]
RD_API_KEY = os.getenv("RD_ACCESS_TOKEN")
SB_HOST = os.getenv("SEEDBOX_HOST")
SB_USER = os.getenv("RUTORRENT_USER")
SB_PASS = os.getenv("RUTORRENT_PASS") or os.getenv("SFTP_PASS")
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
RSS_UPLOAD_DEST = os.getenv("RSS_UPLOAD_DEST", "telegram")
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
    """Start command with diagnostic logging"""
    logger.info(f"📥 Received /start from user {update.effective_user.id}")

    if not check_auth(update.effective_user.id):
        logger.warning(f"❌ Unauthorized user: {update.effective_user.id}")
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
        "/remove\_feed \- Remove RSS feed"
    )

    update.message.reply_text(msg, parse_mode="MarkdownV2")
    logger.info("✅ Sent /start response")


def status(update: Update, context: CallbackContext):
    """Show active torrents status with diagnostic logging"""
    logger.info(f"📥 Received /status from user {update.effective_user.id}")

    if not check_auth(update.effective_user.id):
        logger.warning(f"❌ Unauthorized user: {update.effective_user.id}")
        update.message.reply_text("❌ Unauthorized")
        return

    try:
        tasks = downloader.get_active_tasks()
        logger.info(f"📊 Active tasks count: {len(tasks)}")

        if not tasks:
            logger.info("📭 No active tasks, sending empty message")
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
        logger.info(f"📤 Sending status response ({len(status_lines)} lines)")
        update.message.reply_text(status_text, parse_mode="MarkdownV2")
        logger.info("✅ Sent /status response")

    except Exception as e:
        logger.error(f"❌ Error in /status handler: {e}", exc_info=True)
        update.message.reply_text(f"❌ Error: {str(e)}")


def handle_magnet(update: Update, context: CallbackContext):
    """Handle magnet link or torrent file"""
    logger.info(f"📥 Received message from user {update.effective_user.id}")

    if not check_auth(update.effective_user.id):
        update.message.reply_text("❌ Unauthorized")
        return

    message = update.message
    magnet = message.text if message.text and message.text.startswith("magnet:") else None

    if not magnet:
        logger.debug("Not a magnet link, ignoring")
        return

    keyboard = [
        [
            InlineKeyboardButton("🚀 Real-Debrid", callback_data=f"service:rd:{magnet}"),
            InlineKeyboardButton("📦 Seedbox", callback_data=f"service:sb:{magnet}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message.reply_text("Select service:", reply_markup=reply_markup)


def handle_service_selection(update: Update, context: CallbackContext):
    """Handle service selection callback"""
    query = update.callback_query
    query.answer()

    logger.info(f"📥 Callback query: {query.data}")

    if not check_auth(query.from_user.id):
        query.edit_message_text("❌ Unauthorized")
        return

    data = query.data.split(":", 2)
    service = data[1]
    magnet = data[2]

    keyboard = [
        [
            InlineKeyboardButton("☁️ Google Drive", callback_data=f"dest:{service}:gdrive:{magnet}"),
            InlineKeyboardButton("📱 Telegram", callback_data=f"dest:{service}:telegram:{magnet}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("Upload to:", reply_markup=reply_markup)


def handle_destination_selection(update: Update, context: CallbackContext):
    """Handle upload destination selection"""
    query = update.callback_query
    query.answer()

    logger.info(f"📥 Destination callback: {query.data}")

    if not check_auth(query.from_user.id):
        query.edit_message_text("❌ Unauthorized")
        return

    data = query.data.split(":", 3)
    service = data[1]
    destination = data[2]
    magnet = data[3]

    query.edit_message_text("⏳ Processing...")

    try:
        if service == "rd":
            if not rd_client:
                query.edit_message_text("❌ Real-Debrid not configured")
                return

            result = rd_client.add_magnet(magnet)
            torrent_id = result.get("id")

            try:
                rd_client.select_files(torrent_id, "all")
            except Exception as e:
                logger.warning(f"Could not auto-select files: {e}")

            query.edit_message_text(f"✅ Added to Real-Debrid\nID: `{torrent_id}`", parse_mode="MarkdownV2")
            state_manager.add_intent(f"rd:{torrent_id}", destination)

        elif service == "sb":
            if not sb_client:
                query.edit_message_text("❌ Seedbox not configured")
                return

            result = sb_client.add_torrent(magnet)
            query.edit_message_text("✅ Added to Seedbox")

    except Exception as e:
        logger.error(f"Error adding torrent: {e}", exc_info=True)
        query.edit_message_text(f"❌ Error: {str(e)}")


# RSS Commands
def cmd_add_feed(update: Update, context: CallbackContext):
    """Add RSS feed"""
    logger.info(f"📥 Received /add_feed from user {update.effective_user.id}")

    if not check_auth(update.effective_user.id):
        update.message.reply_text("❌ Unauthorized")
        return

    args = context.args
    if not args:
        msg = "Usage: `/add_feed <url> [service] [private] [delete]`"
        update.message.reply_text(msg, parse_mode="MarkdownV2")
        return

    url = args[0]
    service = args[1] if len(args) > 1 else None
    private = args[2].lower() == "true" if len(args) > 2 else False
    delete_after_upload = args[3].lower() == "true" if len(args) > 3 else RSS_DELETE_AFTER_UPLOAD

    try:
        rss_manager.add_feed(url, service=service, private_torrent=private, delete_after_upload=delete_after_upload)
        update.message.reply_text(f"✅ Added RSS feed")
    except Exception as e:
        logger.error(f"Error adding feed: {e}", exc_info=True)
        update.message.reply_text(f"❌ Error: {str(e)}")


def cmd_list_feeds(update: Update, context: CallbackContext):
    """List all RSS feeds"""
    logger.info(f"📥 Received /list_feeds from user {update.effective_user.id}")

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
        lines.append(f"{i}\. {service}")

    text = "\n".join(lines)
    update.message.reply_text(text, parse_mode="MarkdownV2")


def cmd_poll_feeds(update: Update, context: CallbackContext):
    """Manually poll RSS feeds"""
    logger.info(f"📥 Received /poll_feeds from user {update.effective_user.id}")

    if not check_auth(update.effective_user.id):
        update.message.reply_text("❌ Unauthorized")
        return

    update.message.reply_text("🔄 Polling RSS feeds...")

    try:
        new_items = rss_manager.poll_feeds()
        update.message.reply_text(f"✅ Found {new_items} new item(s)")
    except Exception as e:
        logger.error(f"Error polling feeds: {e}", exc_info=True)
        update.message.reply_text(f"❌ Error: {str(e)}")


def rss_poll_loop():
    """Background RSS polling"""
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
    """Start background threads"""
    monitor.start()

    rss_thread = threading.Thread(target=rss_poll_loop, daemon=True)
    rss_thread.start()

    logger.info("✅ Background tasks started")
    logger.info(f"📰 RSS auto-polling (interval: {RSS_POLL_INTERVAL}s)")
    logger.info(f"📤 RSS upload: {RSS_UPLOAD_DEST}")


def error_handler(update: Update, context: CallbackContext):
    """Log errors caused by updates"""
    logger.error(f"❌ Update {update} caused error: {context.error}", exc_info=True)


def main():
    """Start the bot"""
    if not TOKEN:
        logger.error("❌ BOT_TOKEN not set")
        return

    if ":" not in TOKEN:
        logger.error("❌ Invalid BOT_TOKEN format")
        return

    logger.info(f"Using python-telegram-bot v13")
    logger.info(f"Bot token: {TOKEN[:10]}...{TOKEN[-4:]}")
    logger.info(f"Token length: {len(TOKEN)} chars")

    try:
        logger.info("🔧 Initializing Updater...")
        updater = Updater(TOKEN, use_context=True)
        dp = updater.dispatcher

        # Add handlers with logging
        logger.info("📋 Registering command handlers...")
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("status", status))
        dp.add_handler(CommandHandler("add_feed", cmd_add_feed))
        dp.add_handler(CommandHandler("list_feeds", cmd_list_feeds))
        dp.add_handler(CommandHandler("poll_feeds", cmd_poll_feeds))

        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_magnet))

        dp.add_handler(CallbackQueryHandler(handle_service_selection, pattern="^service:"))
        dp.add_handler(CallbackQueryHandler(handle_destination_selection, pattern="^dest:"))

        # Add error handler
        dp.add_error_handler(error_handler)

        logger.info("✅ All handlers registered")

        # Start background tasks
        start_background_tasks()

        logger.info("🚀 Bot started (v13) - Polling for updates...")
        updater.start_polling()
        logger.info("✅ Polling started successfully")
        updater.idle()

    except Exception as e:
        logger.error(f"❌ Failed to initialize bot: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
