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

try:
    from bot.rss import FeedManager, Router
except Exception:
    FeedManager = None
    Router = None

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
    # If real RD is available and supports the link, the user probably should use RD
    try:
        if RDClient:
            rd = RDClient()
            if rd.is_cached(url):
                update.message.reply_text("Note: Real-Debrid reports this link is available; if you prefer RD, use appropriate RD commands.")
    except RealDebridNotConfigured:
        # RD not configured — proceed
        pass

    # Enqueue yt-dlp job
    try:
        from bot.jobs import enqueue_ytdl
    except Exception:
        update.message.reply_text("yt-dlp job runner not available")
        return
    jid = enqueue_ytdl(url)
    update.message.reply_text(f"yt-dlp job queued (id={jid}). Warning: running yt-dlp on Heroku may be unstable.")


# Initialize feed manager if rss module is present
_feed_manager = None
try:
    if FeedManager and Router:
        router = Router(rd_client=RDClient() if RDClient else None, sb_client=SeedboxClient() if SeedboxClient else None)
        _feed_manager = FeedManager(router)
except Exception:
    _feed_manager = None


def add_feed_cmd(update: Update, context: CallbackContext):
    if _feed_manager is None:
        update.message.reply_text("RSS support not available (missing dependencies)")
        return
    if len(context.args) < 1:
        update.message.reply_text("Usage: /add_feed <url> [forced_backend: rd|sb] [private]")
        return
    url = context.args[0]
    forced = None
    private = False
    if len(context.args) >= 2:
        forced = context.args[1]
        if forced not in ("rd", "sb"):
            forced = None
    if len(context.args) >= 3 and context.args[2].lower() in ("1", "true", "private"):
        private = True
    _feed_manager.add_feed(url, forced_backend=forced, private_torrents=private)
    update.message.reply_text(f"Added feed: {url} (forced={forced}, private={private})")


def list_feeds_cmd(update: Update, context: CallbackContext):
    if _feed_manager is None:
        update.message.reply_text("RSS support not available")
        return
    feeds = _feed_manager.list_feeds()
    if not feeds:
        update.message.reply_text("No feeds configured")
        return
    text = "\n".join([f"{f.url} (forced={f.forced_backend}, private={f.private_torrents})" for f in feeds])
    update.message.reply_text(text)


def remove_feed_cmd(update: Update, context: CallbackContext):
    if _feed_manager is None:
        update.message.reply_text("RSS support not available")
        return
    if len(context.args) < 1:
        update.message.reply_text("Usage: /remove_feed <url>")
        return
    url = context.args[0]
    _feed_manager.remove_feed(url)
    update.message.reply_text(f"Removed feed: {url}")


def poll_feeds_cmd(update: Update, context: CallbackContext):
    if _feed_manager is None:
        update.message.reply_text("RSS support not available")
        return
    # Run one poll and apply decisions (minimal: add torrents to backend stubs)
    decisions = []

    def on_decision(backend, entry):
        decisions.append((backend, entry))
        # perform minimal action: call add_magnet/add_torrent where applicable
        link = entry.get('link') or entry.get('guid') or ''
        if backend == 'rd' and RDClient:
            try:
                rd = RDClient()
                rd.add_magnet(link)
            except Exception as e:
                decisions.append(("error", str(e)))
        elif backend == 'sb' and SeedboxClient:
            try:
                sb = SeedboxClient()
                sb.add_torrent(link)
            except Exception as e:
                decisions.append(("error", str(e)))

    try:
        _feed_manager.poll_once(on_decision=on_decision)
    except Exception as exc:
        update.message.reply_text(f"Polling failed: {exc}")
        return
    if not decisions:
        update.message.reply_text("No new items")
        return
    text = "\n".join([f"{b}: { (e.get('title') or e.get('link') or '') }" for b, e in decisions if b in ('rd','sb')])
    update.message.reply_text(f"Decisions:\n{text}")


def create_app(token: str) -> Updater:
    updater = Updater(token)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("rd_torrent", rd_torrent))
    dp.add_handler(CommandHandler("rd_torrents", rd_torrents))
    dp.add_handler(CommandHandler("rd_delete", rd_delete))
    dp.add_handler(CommandHandler("sb_torrent", sb_torrent))
    dp.add_handler(CommandHandler("ytdl", ytdl))
    dp.add_handler(CommandHandler("add_feed", add_feed_cmd))
    dp.add_handler(CommandHandler("list_feeds", list_feeds_cmd))
    dp.add_handler(CommandHandler("remove_feed", remove_feed_cmd))
    dp.add_handler(CommandHandler("poll_feeds", poll_feeds_cmd))

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
