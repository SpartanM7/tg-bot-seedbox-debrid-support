#!/usr/bin/env python3
"""
Unified Telegram bot for managing torrents via Real-Debrid and Seedbox.
Handles RSS feeds with smart polling and caching.
"""

import os
import sys
import time
import logging
import asyncio
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# Import bot modules
from bot.real_debrid import RealDebridClient
from bot.seedbox import SeedboxClient
from bot.monitor import TorrentMonitor
from bot.downloader import download_and_upload
from bot.state import StateManager
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
RD_API_KEY = os.getenv("RD_API_KEY")
SB_HOST = os.getenv("SB_HOST")
SB_USER = os.getenv("SB_USER")
SB_PASS = os.getenv("SB_PASS")
SB_PORT = int(os.getenv("SB_PORT", "22"))
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")
TG_UPLOAD_TARGET = os.getenv("TG_UPLOAD_TARGET")  # Default Telegram chat ID

# Initialize clients
rd_client = RealDebridClient(RD_API_KEY) if RD_API_KEY else None
sb_client = SeedboxClient(SB_HOST, SB_USER, SB_PASS, SB_PORT) if all([SB_HOST, SB_USER, SB_PASS]) else None
state_manager = StateManager()
status_manager = StatusMessageManager()

# RSS Configuration
RSS_POLL_INTERVAL = int(os.getenv("RSS_POLL_INTERVAL", "900"))  # 15 minutes
RSS_UPLOAD_DEST = os.getenv("RSS_UPLOAD_DEST", "gdrive")  # gdrive or telegram
RSS_API_DELAY = float(os.getenv("RSS_API_DELAY", "2.0"))  # 2 second delay between API calls
RSS_DELETE_AFTER_UPLOAD = os.getenv("RSS_DELETE_AFTER_UPLOAD", "false").lower() == "true"

rss_manager = RSSManager(
    rd_client=rd_client,
    sb_client=sb_client,
    state_manager=state_manager,
    upload_dest=RSS_UPLOAD_DEST,
    api_delay=RSS_API_DELAY,
    default_chat_id=TG_UPLOAD_TARGET,  # Pass default chat ID
    delete_after_upload=RSS_DELETE_AFTER_UPLOAD
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

    await update.message.reply_text(
        "🤖 **Torrent Bot**\n\n"
        "*Commands:*\n"
        "📥 Send magnet/torrent file\n"
        "/status - View active downloads\n"
        "/feeds - Manage RSS feeds\n"
        "/add\_feed - Add RSS feed\n"
        "/list\_feeds - List RSS feeds\n"
        "/poll\_feeds - Force RSS poll\n"
        "/remove\_feed - Remove RSS feed",
        parse_mode="MarkdownV2"
    )


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
    torrent_file = context.user_data.get("pending_torrent")

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
                result = rd_client.add_torrent(torrent_file)

            torrent_id = result.get("id")
            await query.edit_message_text(f"✅ Added to Real-Debrid\nID: `{torrent_id}`", parse_mode="MarkdownV2")

            # Store for monitoring
            state_manager.add_torrent(
                torrent_id=str(torrent_id),
                service="rd",
                user_id=user_id,
                upload_intent=destination,
                chat_id=upload_chat_id
            )

        elif service == "sb":
            if not sb_client:
                await query.edit_message_text("❌ Seedbox not configured")
                return

            if magnet:
                result = sb_client.add_magnet(magnet)
            else:
                result = sb_client.add_torrent(torrent_file)

            torrent_hash = result.get("hash")
            await query.edit_message_text(f"✅ Added to Seedbox\nHash: `{torrent_hash}`", parse_mode="MarkdownV2")

            # Store for monitoring
            state_manager.add_torrent(
                torrent_id=torrent_hash,
                service="sb",
                user_id=user_id,
                upload_intent=destination,
                chat_id=upload_chat_id,
                delete_after_upload=False  # Manual adds don't auto-delete
            )

    except Exception as e:
        logger.error(f"Error adding torrent: {e}", exc_info=True)
        await query.edit_message_text(f"❌ Error: {str(e)}")
    finally:
        # Cleanup
        context.user_data.pop("pending_torrent", None)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show active torrents status"""
    if not check_auth(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized")
        return

    user_id = update.effective_user.id
    torrents = state_manager.get_user_torrents(user_id)

    if not torrents:
        await update.message.reply_text("📭 No active torrents")
        return

    # Create live status message
    status_msg = await update.message.reply_text("⏳ Loading status...")

    # Register for live updates
    await status_manager.start_status(
        user_id=user_id,
        message_id=status_msg.message_id,
        chat_id=update.effective_chat.id,
        context=context
    )


# ==================== RSS COMMANDS ====================

async def rss_feeds_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show RSS feeds management menu"""
    if not check_auth(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized")
        return

    feeds = rss_manager.list_feeds()

    if not feeds:
        text = "📰 *RSS Feeds*\n\nNo feeds configured\."
    else:
        text = "📰 *RSS Feeds*\n\n"
        for i, feed in enumerate(feeds, 1):
            url = feed["url"].replace(".", "\.").replace("-", "\-")
            service = feed.get("service", "rd")
            text += f"{i}\. `{url}` \({service}\)\n"

    keyboard = [
        [InlineKeyboardButton("➕ Add Feed", callback_data="rss:add")],
        [InlineKeyboardButton("🔄 Poll Now", callback_data="rss:poll")],
        [InlineKeyboardButton("🗑 Remove Feed", callback_data="rss:remove")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="MarkdownV2")


async def cmd_add_feed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Add RSS feed command
    Usage: /add_feed <url> [service] [private]
    Example: /add_feed https://nyaa.si/?page=rss&u=tsuna69 rd true
    """
    if not check_auth(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/add_feed <url> [service] [private] [delete_after_upload]`\n\n"
            "Examples:\n"
            "`/add_feed https://nyaa\.si/?page=rss&u=tsuna69`\n"
            "`/add_feed https://nyaa\.si/?page=rss&u=tsuna69 rd`\n"
            "`/add_feed https://nyaa\.si/?page=rss&u=tsuna69 sb true`\n"
            "`/add_feed https://nyaa\.si/?page=rss&u=tsuna69 sb false true`",
            parse_mode="MarkdownV2"
        )
        return

    url = args[0]
    service = args[1] if len(args) > 1 else None
    private = args[2].lower() == "true" if len(args) > 2 else False
    delete_after_upload = args[3].lower() == "true" if len(args) > 3 else RSS_DELETE_AFTER_UPLOAD

    try:
        rss_manager.add_feed(url, service=service, private_torrent=private, delete_after_upload=delete_after_upload)

        service_text = service if service else "auto"
        delete_text = "✅" if delete_after_upload else "❌"

        await update.message.reply_text(
            f"✅ Added feed:\n"
            f"`{url}`\n"
            f"Service: {service_text}\n"
            f"Delete after upload: {delete_text}",
            parse_mode="MarkdownV2"
        )
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
        url = feed["url"].replace(".", "\.").replace("-", "\-").replace("_", "\_")
        service = feed.get("service", "auto")
        delete = "🗑" if feed.get("delete_after_upload", False) else ""
        text += f"{i}\. `{url}` \({service}\) {delete}\n"

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
    """
    Remove RSS feed command
    Usage: /remove_feed <index or url>
    """
    if not check_auth(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/remove_feed <index or url>`\n\n"
            "Example: `/remove_feed 1` or `/remove_feed https://example\.com/rss`",
            parse_mode="MarkdownV2"
        )
        return

    identifier = " ".join(args)

    try:
        # Try as index first
        if identifier.isdigit():
            index = int(identifier) - 1
            feeds = rss_manager.list_feeds()
            if 0 <= index < len(feeds):
                url = feeds[index]["url"]
                rss_manager.remove_feed(url)
                await update.message.reply_text(f"✅ Removed feed: `{url}`", parse_mode="MarkdownV2")
            else:
                await update.message.reply_text("❌ Invalid feed index")
        else:
            rss_manager.remove_feed(identifier)
            await update.message.reply_text(f"✅ Removed feed: `{identifier}`", parse_mode="MarkdownV2")

    except Exception as e:
        logger.error(f"Error removing feed: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def rss_poll_loop(application: Application):
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


async def monitor_loop(application: Application):
    """Background task to monitor torrent completion"""
    logger.info("Starting torrent monitor loop")

    monitor = TorrentMonitor(
        rd_client=rd_client,
        sb_client=sb_client,
        state_manager=state_manager
    )

    while True:
        try:
            completed = monitor.check_completions()

            for torrent in completed:
                logger.info(f"⏳ Ready for download: {torrent['name']}")

                # Download and upload
                asyncio.create_task(
                    download_and_upload(
                        torrent=torrent,
                        rd_client=rd_client,
                        sb_client=sb_client,
                        state_manager=state_manager,
                        bot=application.bot,
                        gdrive_folder_id=GDRIVE_FOLDER_ID
                    )
                )

            await asyncio.sleep(30)  # Check every 30 seconds

        except Exception as e:
            logger.error(f"Error in monitor loop: {e}", exc_info=True)
            await asyncio.sleep(60)


async def post_init(application: Application):
    """Initialize background tasks"""
    # Start monitor loop
    asyncio.create_task(monitor_loop(application))

    # Start RSS poll loop
    asyncio.create_task(rss_poll_loop(application))

    logger.info("✅ Background tasks started")
    logger.info(f"📰 RSS auto-polling started (interval: {RSS_POLL_INTERVAL}s)")
    logger.info(f"📤 RSS upload destination: {RSS_UPLOAD_DEST}")
    logger.info(f"⏱ RSS API delay: {RSS_API_DELAY}s")
    logger.info(f"🗑 RSS delete after upload: {RSS_DELETE_AFTER_UPLOAD}")


def main():
    """Start the bot"""
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    # Create application
    application = Application.builder().token(TOKEN).post_init(post_init).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("feeds", rss_feeds_menu))
    application.add_handler(CommandHandler("add_feed", cmd_add_feed))
    application.add_handler(CommandHandler("rss_add", cmd_add_feed))  # Alias
    application.add_handler(CommandHandler("list_feeds", cmd_list_feeds))
    application.add_handler(CommandHandler("rss_list", cmd_list_feeds))  # Alias
    application.add_handler(CommandHandler("poll_feeds", cmd_poll_feeds))
    application.add_handler(CommandHandler("rss_poll", cmd_poll_feeds))  # Alias
    application.add_handler(CommandHandler("remove_feed", cmd_remove_feed))
    application.add_handler(CommandHandler("rss_remove", cmd_remove_feed))  # Alias

    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_magnet))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_magnet))

    # Callback handlers
    application.add_handler(CallbackQueryHandler(handle_service_selection, pattern="^service:"))
    application.add_handler(CallbackQueryHandler(handle_destination_selection, pattern="^dest:"))

    # Start bot
    logger.info("🚀 Bot started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
