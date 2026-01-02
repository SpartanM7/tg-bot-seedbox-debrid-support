"""Telegram bot scaffolding with explicit command handlers (minimal stubs).

Handlers follow v1 command names; the body is intentionally conservative: if a
backend isn't configured the handler returns a clear message. This scaffolding
lets the rest of the project call and test handlers early without full backend
implementations.
"""

import os
import logging
from typing import List

from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

from bot.config import BOT_TOKEN

try:
    from bot.clients.realdebrid import RDClient, RealDebridNotConfigured
except Exception:
    RDClient = None
    RealDebridNotConfigured = Exception

try:
    from bot.clients.seedbox import SeedboxClient, SeedboxNotConfigured
except Exception:
    SeedboxClient = None
    SeedboxNotConfigured = Exception

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def start(update: Update, context: CallbackContext):
    update.message.reply_text("WZML-X v1 — bot up. Use explicit commands per v1 spec.")


def rd_torrent(update: Update, context: CallbackContext):
    if not RDClient:
        update.message.reply_text("Real-Debrid client not available (module missing)")
        return
    if len(context.args) < 1:
        update.message.reply_text("Usage: /rd_torrent <magnet_or_torrent_url>")
        return
    magnet = context.args[0]
    try:
        rd = RDClient()
    except RealDebridNotConfigured as e:
        update.message.reply_text(str(e))
        return
    res = rd.add_magnet(magnet)
    update.message.reply_text(f"Real-Debrid: added magnet (id={res.get('id')})")


def rd_torrents(update: Update, context: CallbackContext):
    if not RDClient:
        update.message.reply_text("Real-Debrid client not available (module missing)")
        return
    try:
        rd = RDClient()
    except RealDebridNotConfigured as e:
        update.message.reply_text(str(e))
        return
    items = rd.list_torrents()
    if not items:
        update.message.reply_text("No torrents on Real-Debrid")
        return
    text = "\n".join([f"{i.get('id')}: {i.get('status')}" for i in items])
    update.message.reply_text(text)


def rd_delete(update: Update, context: CallbackContext):
    if not RDClient:
        update.message.reply_text("Real-Debrid client not available (module missing)")
        return
    if len(context.args) < 1:
        update.message.reply_text("Usage: /rd_delete <id>")
        return
    tid = context.args[0]
    try:
        rd = RDClient()
    except RealDebridNotConfigured as e:
        update.message.reply_text(str(e))
        return
    ok = rd.delete_torrent(tid)
    update.message.reply_text("Deleted" if ok else "Failed to delete")


def sb_torrent(update: Update, context: CallbackContext):
    if not SeedboxClient:
        update.message.reply_text("Seedbox client not available (module missing)")
        return
    if len(context.args) < 1:
        update.message.reply_text("Usage: /sb_torrent <magnet_or_torrent_url>")
        return
    torrent = context.args[0]
    try:
        sb = SeedboxClient()
    except SeedboxNotConfigured as e:
        update.message.reply_text(str(e))
        return
    res = sb.add_torrent(torrent)
    update.message.reply_text(f"Seedbox: added torrent (id={res.get('id')})")


def ytdl(update: Update, context: CallbackContext):
    if len(context.args) < 1:
        update.message.reply_text("Usage: /ytdl <url>")
        return
    url = context.args[0]
    # Explicit user request: we acknowledge and (for now) stub the background task.
    update.message.reply_text(f"Queued yt-dlp job for: {url} (stubbed)")


def create_app(token: str) -> Updater:
    updater = Updater(token)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("rd_torrent", rd_torrent))
    dp.add_handler(CommandHandler("rd_torrents", rd_torrents))
    dp.add_handler(CommandHandler("rd_delete", rd_delete))
    dp.add_handler(CommandHandler("sb_torrent", sb_torrent))
    dp.add_handler(CommandHandler("ytdl", ytdl))

    return updater


def run():
    token = BOT_TOKEN or os.getenv("BOT_TOKEN")
    if not token:
        logger.info("BOT_TOKEN not set; telegram bot disabled")
        return
    updater = create_app(token)
    logger.info("Starting telegram bot polling")
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    run()
