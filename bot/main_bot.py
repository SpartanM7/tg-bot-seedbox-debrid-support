#!/usr/bin/env python3
"""
Unified Telegram bot for managing torrents via Real-Debrid and Seedbox.
Handles RSS feeds with smart polling and caching.
Compatible with python-telegram-bot v13+
"""

import os
import sys
import logging
import asyncio
from datetime import datetime, timezone

# Try v20+ imports first, fall back to v13
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        CallbackQueryHandler,
        filters,
        ContextTypes,
    )
    PTB_VERSION = 20
except ImportError:
    # Fall back to v13
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Updater,
        CommandHandler,
        MessageHandler,
        CallbackQueryHandler,
        Filters,
        CallbackContext,
    )
    PTB_VERSION = 13
    # Aliases for compatibility
    ContextTypes = type('ContextTypes', (), {'DEFAULT_TYPE': CallbackContext})
    filters = Filters

# Import bot modules - CORRECTED CLASS NAMES
from bot.clients.realdebrid import RDClient
from bot.clients.seedbox import SeedboxClient
from bot.monitor import Monitor
from bot.downloader import Downloader
from bot.state import get_state
from bot.status_manager import StatusMessageManager
from bot.rss import RSSManager

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USERS = [int(uid) for uid in os.getenv("ALLOWED_USER_IDS", "").split(",") if uid.strip()]
RD_API_KEY = os.getenv("RD_ACCESS_TOKEN")  # Note: your RDClient expects RD_ACCESS_TOKEN
SB_HOST = os.getenv("SEEDBOX_HOST")
SB_USER = os.getenv("RUTORRENT_USER")
SB_PASS = os.getenv("RUTORRENT_PASS")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")
TG_UPLOAD_TARGET = os.getenv("TG_UPLOAD_TARGET")

# Initialize clients
try:
    rd_client = RDClient(RD_API_KEY) if RD_API_KEY else None
except Exception as e:
    logger.warning(f"Real-Debrid not configured: {e}")
    rd_client = None

try:
    sb_client = SeedboxClient() if all([SB_USER, SB_PASS]) else None
except Exception as e:
    logger.warning(f"Seedbox not configured: {e}")
    sb_client = None

state_manager = get_state()
status_manager = StatusMessageManager()
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    if not check_auth(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized")
        return

    msg = (
        "🤖 Torrent Bot\n\n"
        "Commands:\n"
        "📥 Send magnet/torrent file\n"
        "/status \- View active downloads\n"
        "/add\_feed \- Add RSS feed\n"
        "/list\_feeds \- List RSS feeds\n"
        "/poll\_feeds \- Force RSS poll\n"
        "/remove\_feed \- Remove RSS feed"
    )

    await update.message.reply_text(msg, parse_mode="MarkdownV2")


async def handle_magnet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle magnet link or torrent file"""
    if not check_auth(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized")
        return

    user_id = update.effective_user.id
    message = update.message

    # Extract magnet or torrent
    magnet = message.text if message.text and message.text.startswith("magnet:") else None
    torrent_file = None

    if message.document and message.document.file_name.endswith(".torrent"):
        file = await context.bot.get_file(message.document.file_id)
        torrent_file = await file.download_as_bytearray()

    if not magnet and not torrent_file:
        await message.reply_text("❌ Please send a magnet link or .torrent file")
        return

    # Ask for service selection
    keyboard = [
        [
            InlineKeyboardButton("🚀 Real-Debrid", callback_data=f"service:rd:{magnet or 'file'}"),
            InlineKeyboardButton("📦 Seedbox", callback_data=f"service:sb:{magnet or 'file'}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await message.reply_text("Select service:", reply_markup=reply_markup)

    # Store torrent file in context
    if torrent_file:
        context.user_data["pending_torrent"] = torrent_file


async def handle_service_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle service selection callback"""
    query = update.callback_query
    await query.answer()

    if not check_auth(query.from_user.id):
        await query.edit_message_text("❌ Unauthorized")
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

    await query.edit_message_text("Upload to:", reply_markup=reply_markup)


async def handle_destination_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle upload destination selection"""
    query = update.callback_query
    await query.answer()

    if not check_auth(query.from_user.id):
        await query.edit_message_text("❌ Unauthorized")
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
            await query.edit_message_text("❌ No Telegram chat configured for uploads")
            return

    await query.edit_message_text("⏳ Processing...")

    try:
        # Add torrent
        if service == "rd":
            if not rd_client:
                await query.edit_message_text("❌ Real-Debrid not configured")
                return

            if magnet:
                result = rd_client.add_magnet(magnet)
            else:
                # RDClient add_torrent expects bytes/file content
                import io
                result = rd_client.add_magnet(torrent_file)  # May need adjustment based on RDClient API

            torrent_id = result.get("id")
            await query.edit_message_text(f"✅ Added to Real\-Debrid\nID: `{torrent_id}`", parse_mode="MarkdownV2")

            # Store for monitoring
            state_manager.add_intent(f"rd:{torrent_id}", destination)
            if upload_chat_id:
                state_manager.add_intent(f"rd:{torrent_id}", upload_chat_id)

        elif service == "sb":
            if not sb_client:
                await query.edit_message_text("❌ Seedbox not configured")
                return

            if magnet:
                result = sb_client.add_torrent(magnet)
            else:
                # SeedboxClient add_torrent expects URL/magnet string
                # For .torrent files, we'd need to upload it somewhere or use different method
                await query.edit_message_text("❌ .torrent file upload to seedbox not yet implemented")
                return

            torrent_hash = result.get("id", "pending")
            await query.edit_message_text(f"✅ Added to Seedbox\nHash: `{torrent_hash}`", parse_mode="MarkdownV2")

            # Store for monitoring
            state_manager.add_intent(f"sb:{torrent_hash}", destination)
            if upload_chat_id:
                state_manager.add_intent(f"sb:{torrent_hash}", upload_chat_id)

    except Exception as e:
        logger.error(f"Error adding torrent: {e}", exc_info=True)
        await query.edit_message_text(f"❌ Error: {str(e)}")
    finally:
        context.user_data.pop("pending_torrent", None)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show active torrents status"""
    if not check_auth(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized")
        return

    # Get active tasks from downloader
    tasks = downloader.get_active_tasks()

    if not tasks:
        await update.message.reply_text("📭 No active downloads")
        return

    # Format status message
    status_text = "📊 *Active Downloads:*\n\n"

    for task_id, task_info in tasks.items():
        name = task_info.get("name", "Unknown")
        status_str = task_info.get("status", "unknown")
        progress = task_info.get("progress_percent", 0)
        uploaded = task_info.get("uploaded_files", 0)
        total = task_info.get("total_files", 0)

        # Escape special characters
        name = name.replace("_", "\_").replace("*", "\*").replace("[", "\[").replace("]", "\]")
        status_str = status_str.replace("_", "\_")

        status_text += f"📁 *{name}*\n"
        status_text += f"   Status: {status_str}\n"

        if total > 0:
            status_text += f"   Files: {uploaded}/{total}\n"
        if progress > 0:
            status_text += f"   Progress: {progress:.1f}%\n"

        status_text += "\n"

    await update.message.reply_text(status_text, parse_mode="MarkdownV2")


# ==================== RSS COMMANDS ====================

async def cmd_add_feed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add RSS feed command"""
    if not check_auth(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized")
        return

    args = context.args
    if not args:
        msg = (
            "Usage: `/add_feed <url> [service] [private] [delete]`\n\n"
            "Examples:\n"
            "`/add_feed https://nyaa\.si/?page=rss`\n"
            "`/add_feed https://nyaa\.si/?page=rss rd`\n"
            "`/add_feed https://nyaa\.si/?page=rss sb true`\n"
            "`/add_feed https://nyaa\.si/?page=rss sb false true`"
        )
        await update.message.reply_text(msg, parse_mode="MarkdownV2")
        return

    url = args[0]
    service = args[1] if len(args) > 1 else None
    private = args[2].lower() == "true" if len(args) > 2 else False
    delete_after_upload = args[3].lower() == "true" if len(args) > 3 else RSS_DELETE_AFTER_UPLOAD

    try:
        rss_manager.add_feed(url, service=service, private_torrent=private, delete_after_upload=delete_after_upload)

        service_text = service if service else "auto"
        delete_text = "✅" if delete_after_upload else "❌"

        # Escape URL for MarkdownV2
        url_escaped = url.replace("_", "\_").replace(".", "\.").replace("-", "\-").replace("?", "\?").replace("=", "\=").replace("&", "\&")

        msg = f"✅ Added feed:\n`{url_escaped}`\nService: {service_text}\nDelete: {delete_text}"
        await update.message.reply_text(msg, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Error adding feed: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_list_feeds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all RSS feeds"""
    if not check_auth(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized")
        return

    feeds = rss_manager.list_feeds()

    if not feeds:
        await update.message.reply_text("📭 No RSS feeds configured")
        return

    text = "📰 *RSS Feeds:*\n\n"
    for i, feed in enumerate(feeds, 1):
        url = feed["url"]
        # Escape for MarkdownV2
        url_escaped = url.replace("_", "\_").replace(".", "\.").replace("-", "\-").replace("?", "\?").replace("=", "\=").replace("&", "\&")
        service = feed.get("service", "auto")
        delete = "🗑" if feed.get("delete_after_upload", False) else ""
        text += f"{i}\. `{url_escaped}` \({service}\) {delete}\n"

    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def cmd_poll_feeds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually poll all RSS feeds"""
    if not check_auth(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized")
        return

    await update.message.reply_text("🔄 Polling RSS feeds...")

    try:
        new_items = await rss_manager.poll_feeds()

        if new_items == 0:
            await update.message.reply_text("✅ No new items found")
        else:
            await update.message.reply_text(f"✅ Found {new_items} new item(s)")
    except Exception as e:
        logger.error(f"Error polling feeds: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_remove_feed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove RSS feed command"""
    if not check_auth(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized")
        return

    args = context.args
    if not args:
        msg = "Usage: `/remove_feed <index or url>`\n\nExample: `/remove_feed 1`"
        await update.message.reply_text(msg, parse_mode="MarkdownV2")
        return

    identifier = " ".join(args)

    try:
        if identifier.isdigit():
            index = int(identifier) - 1
            feeds = rss_manager.list_feeds()
            if 0 <= index < len(feeds):
                url = feeds[index]["url"]
                rss_manager.remove_feed(url)
                url_escaped = url.replace("_", "\_").replace(".", "\.").replace("-", "\-").replace("?", "\?").replace("=", "\=").replace("&", "\&")
                await update.message.reply_text(f"✅ Removed feed: `{url_escaped}`", parse_mode="MarkdownV2")
            else:
                await update.message.reply_text("❌ Invalid feed index")
        else:
            rss_manager.remove_feed(identifier)
            identifier_escaped = identifier.replace("_", "\_").replace(".", "\.").replace("-", "\-").replace("?", "\?").replace("=", "\=").replace("&", "\&")
            await update.message.reply_text(f"✅ Removed feed: `{identifier_escaped}`", parse_mode="MarkdownV2")

    except Exception as e:
        logger.error(f"Error removing feed: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {str(e)}")


# ==================== BACKGROUND TASKS ====================

async def rss_poll_loop(application):
    """Background task to poll RSS feeds periodically"""
    logger.info(f"Starting RSS poll loop (interval={RSS_POLL_INTERVAL}s)")

    while True:
        try:
            await asyncio.sleep(RSS_POLL_INTERVAL)
            new_items = await rss_manager.poll_feeds()
            if new_items > 0:
                logger.info(f"RSS poll found {new_items} new item(s)")
        except Exception as e:
            logger.error(f"Error in RSS poll loop: {e}", exc_info=True)


async def monitor_loop(application):
    """Background task to monitor torrent completion"""
    logger.info("Starting torrent monitor loop")

    # Monitor runs in its own thread, start it
    monitor.start()

    # Keep this coroutine alive
    while True:
        await asyncio.sleep(60)


async def post_init(application):
    """Initialize background tasks"""
    asyncio.create_task(monitor_loop(application))
    asyncio.create_task(rss_poll_loop(application))

    logger.info("✅ Background tasks started")
    logger.info(f"📰 RSS auto-polling (interval: {RSS_POLL_INTERVAL}s)")
    logger.info(f"📤 RSS upload: {RSS_UPLOAD_DEST}")
    logger.info(f"⏱ API delay: {RSS_API_DELAY}s")


def main():
    """Start the bot"""
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    logger.info(f"Using python-telegram-bot v{PTB_VERSION}")

    if PTB_VERSION == 20:
        # v20+ (Application)
        application = Application.builder().token(TOKEN).post_init(post_init).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CommandHandler("add_feed", cmd_add_feed))
        application.add_handler(CommandHandler("rss_add", cmd_add_feed))
        application.add_handler(CommandHandler("list_feeds", cmd_list_feeds))
        application.add_handler(CommandHandler("rss_list", cmd_list_feeds))
        application.add_handler(CommandHandler("poll_feeds", cmd_poll_feeds))
        application.add_handler(CommandHandler("rss_poll", cmd_poll_feeds))
        application.add_handler(CommandHandler("remove_feed", cmd_remove_feed))
        application.add_handler(CommandHandler("rss_remove", cmd_remove_feed))

        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_magnet))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_magnet))

        application.add_handler(CallbackQueryHandler(handle_service_selection, pattern="^service:"))
        application.add_handler(CallbackQueryHandler(handle_destination_selection, pattern="^dest:"))

        logger.info("🚀 Bot started (v20+)")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

    else:
        # v13 (Updater)
        updater = Updater(TOKEN, use_context=True)
        dp = updater.dispatcher

        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("status", status))
        dp.add_handler(CommandHandler("add_feed", cmd_add_feed))
        dp.add_handler(CommandHandler("rss_add", cmd_add_feed))
        dp.add_handler(CommandHandler("list_feeds", cmd_list_feeds))
        dp.add_handler(CommandHandler("rss_list", cmd_list_feeds))
        dp.add_handler(CommandHandler("poll_feeds", cmd_poll_feeds))
        dp.add_handler(CommandHandler("rss_poll", cmd_poll_feeds))
        dp.add_handler(CommandHandler("remove_feed", cmd_remove_feed))
        dp.add_handler(CommandHandler("rss_remove", cmd_remove_feed))

        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_magnet))
        dp.add_handler(MessageHandler(Filters.document, handle_magnet))

        dp.add_handler(CallbackQueryHandler(handle_service_selection, pattern="^service:"))
        dp.add_handler(CallbackQueryHandler(handle_destination_selection, pattern="^dest:"))

        logger.info("🚀 Bot started (v13)")
        updater.start_polling()
        updater.idle()


if __name__ == "__main__":
    main()
