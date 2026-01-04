"""Telegram bot with full production-grade handlers.

Connects to real Real-Debrid, rTorrent, and yt-dlp implementations.
"""

import os
import logging
import threading
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

from bot.config import BOT_TOKEN
from bot.clients.realdebrid import RDClient, RealDebridNotConfigured, RDAPIError
from bot.clients.seedbox import SeedboxClient, SeedboxNotConfigured, SeedboxCommunicationError
from bot.jobs import enqueue_ytdl, job_status, set_updater as jobs_set_updater
from bot.rss import FeedManager, Router
from bot.monitor import Monitor
from bot.downloader import Downloader
from bot.state import get_state

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# --- Clients ---
try:
    rd_client = RDClient()
except RealDebridNotConfigured:
    rd_client = None

try:
    sb_client = SeedboxClient()
except SeedboxNotConfigured:
    sb_client = None

# --- RSS Manager ---
feed_manager = None
if rd_client or sb_client:
    router = Router(rd_client=rd_client, sb_client=sb_client)
    feed_manager = FeedManager(router)

# --- Monitor ---
monitor = None
if rd_client or sb_client:
    # Downloader needs updater, but we don't have it yet. 
    # We will attach it inside create_app or run.
    downloader = Downloader(telegram_updater=None)
    monitor = Monitor(downloader, rd_client=rd_client, sb_client=sb_client)


# --- Utils ---

def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram Markdown v1."""
    # Characters that need escaping in Markdown: _ * [ `
    # However, since we use backticks for the table part, we mostly care about name
    chars = ['_', '*', '[', '`']
    for c in chars:
        text = text.replace(c, f"\\{c}")
    return text

# --- Handlers ---

def start(update: Update, context: CallbackContext):
    msg = "WZML-X v1 (Production)\n\n"
    msg += f"Real-Debrid: {'✅' if rd_client else '❌'}\n"
    msg += f"Seedbox: {'✅' if sb_client else '❌'}\n"
    msg += f"RSS Manager: {'✅' if feed_manager else '❌'}"
    update.message.reply_text(msg)

# Real-Debrid Commmands

def rd_torrent(update: Update, context: CallbackContext):
    if not rd_client: return update.message.reply_text("RD not configured")
    if not context.args: return update.message.reply_text("Usage: /rd_torrent <magnet_or_link>")
    magnet = context.args[0]
    try:
        res = rd_client.add_magnet(magnet)
        update.message.reply_text(f"Added to RD: {res.get('id', 'unknown')}")
    except Exception as e:
        update.message.reply_text(f"Error: {e}")

def rd_torrents(update: Update, context: CallbackContext):
    if not rd_client: return update.message.reply_text("RD not configured")
    try:
        # Default limit 20 for telegram
        items = rd_client.list_torrents(limit=20)
        if not items:
            return update.message.reply_text("No active RD torrents")
        
        lines = []
        lines.append(f"`{'Status':<12} | {'Progress':<8} | Filename`")
        lines.append(f"`{'-'*12}-|-{'-'*8}-|{'-'*20}`")
        
        for i in items:
            status = i.get('status', 'unknown')
            progress = i.get('progress', 0)
            filename = i.get('filename', 'N/A')
            
            # Truncate filename if too long
            if len(filename) > 35:
                filename = filename[:33] + ".."
            
            # Status icons
            icon = "❓"
            if status == "downloaded":
                icon = "✅"
            elif status == "downloading":
                icon = "⬇️"
            elif status == "waiting_files_selection":
                icon = "⏳"
            elif status == "magnet_conversion":
                icon = "🧲"
            elif status == "error":
                icon = "❌"
            
            # Format status for display
            display_status = f"{icon} {status.replace('_', ' ').title()}"
            
            line = f"`{display_status:<12} | {progress:>6}% |` {filename}"
            lines.append(line)
        
        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\n...truncated..."
        update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        update.message.reply_text(f"Error: {e}")

def rd_delete(update: Update, context: CallbackContext):
    if not rd_client: return update.message.reply_text("RD not configured")
    if not context.args: return update.message.reply_text("Usage: /rd_delete <id>")
    try:
        rd_client.delete_torrent(context.args[0])
        update.message.reply_text("Deleted.")
    except Exception as e:
        update.message.reply_text(f"Error: {e}")

def rd_downloads(update: Update, context: CallbackContext):
    """List unrestricted downloads history from Real-Debrid."""
    if not rd_client: return update.message.reply_text("RD not configured")
    try:
        items = rd_client.get_downloads(limit=15)
        if not items:
            return update.message.reply_text("No downloads history")
        
        lines = []
        lines.append(f"`{'Date':<12} | {'Size':<8} | Filename`")
        lines.append(f"`{'-'*12}-|-{'-'*8}-|{'-'*20}`")
        
        for i in items:
            generated = i.get('generated', 'N/A')[:10]  # Just date part
            filename = i.get('filename', 'N/A')
            filesize = i.get('filesize', 0)
            
            # Format bytes
            def fmt_bytes(b):
                for unit in ['B', 'KB', 'MB', 'GB']:
                    if b < 1024.0: return f"{b:.0f}{unit}"
                    b /= 1024.0
                return f"{b:.0f}TB"
            
            # Truncate and escape filename
            if len(filename) > 30:
                filename = filename[:28] + ".."
            filename = escape_markdown(filename)
            
            line = f"`{generated:<12} | {fmt_bytes(filesize):<8} |` {filename}"
            lines.append(line)
        
        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\n...truncated..."
        update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        update.message.reply_text(f"Error: {e}")


def rd_unrestrict(update: Update, context: CallbackContext):
    if not rd_client: return update.message.reply_text("RD not configured")
    if not context.args: return update.message.reply_text("Usage: /rd_unrestrict <link>")
    try:
        res = rd_client.unrestrict_link(context.args[0])
        dl = res.get('download')
        update.message.reply_text(f"Download Link: {dl}")
    except Exception as e:
        update.message.reply_text(f"Error: {e}")

# Seedbox Commands

def sb_torrent(update: Update, context: CallbackContext):
    if not sb_client: return update.message.reply_text("Seedbox not configured")
    if not context.args: return update.message.reply_text("Usage: /sb_torrent <magnet_link>")
    try:
        sb_client.add_torrent(context.args[0])
        update.message.reply_text("Added torrent to Seedbox.")
    except Exception as e:
        update.message.reply_text(f"Error: {e}")

def sb_torrents(update: Update, context: CallbackContext):
    if not sb_client: return update.message.reply_text("Seedbox not configured")
    try:
        items = sb_client.list_torrents()
        if not items:
            return update.message.reply_text("No torrents in Seedbox")
        lines = []
        lines.append(f"`{'State':<10} | {'Progress':<6} | Name`")
        lines.append(f"`{'-'*10}-|-{'-'*6}-|{'-'*20}`")
        
        for i in items:
            name = i.get('name', 'N/A')
            # Truncate and escape name
            if len(name) > 30:
                name = name[:28] + ".."
            name = escape_markdown(name)
            
            state = i.get('state', 'unknown').title()
            progress = i.get('progress', 0.0)
            
            icon = "❓"
            if state == "Seeding": icon = "🟢"
            elif state == "Downloading": icon = "Rx"
            elif state == "Paused": icon = "⏸️"
            
            # Format: [Icon State] Name - 50.5%
            # line = f"{icon} `{state:<10}`: {name} *({progress:.1f}%)*" # Old style alternative
            
            # Table style
            line = f"`{state:<10} | {progress:>5.1f}% |` {name}"
            lines.append(line)
        
        # Split if too long
        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\n...truncated..."
        update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        update.message.reply_text(f"Error: {e}")

def sb_stop(update: Update, context: CallbackContext):
    if not sb_client: return update.message.reply_text("Seedbox not configured")
    if not context.args: return update.message.reply_text("Usage: /sb_stop <hash>")
    try:
        sb_client.stop_torrent(context.args[0])
        update.message.reply_text("Stopped.")
    except Exception as e:
        update.message.reply_text(f"Error: {e}")

def sb_start(update: Update, context: CallbackContext):
    if not sb_client: return update.message.reply_text("Seedbox not configured")
    if not context.args: return update.message.reply_text("Usage: /sb_start <hash>")
    try:
        sb_client.start_torrent(context.args[0])
        update.message.reply_text("Started.")
    except Exception as e:
        update.message.reply_text(f"Error: {e}")

def sb_delete(update: Update, context: CallbackContext):
    if not sb_client: return update.message.reply_text("Seedbox not configured")
    if not context.args: return update.message.reply_text("Usage: /sb_delete <hash>")
    try:
        sb_client.delete_torrent(context.args[0])
        update.message.reply_text("Deleted.")
    except Exception as e:
        update.message.reply_text(f"Error: {e}")

# Helper functions for new commands
def _get_arg(context: CallbackContext) -> str | None:
    return context.args[0] if context.args else None

def _check_rd(update: Update) -> bool:
    if not rd_client:
        update.message.reply_text("RD not configured")
        return False
    return True

def _check_sb(update: Update) -> bool:
    if not sb_client:
        update.message.reply_text("Seedbox not configured")
        return False
    return True

def rd_download(update: Update, context: CallbackContext):
    """Manually trigger download for an existing RD torrent ID."""
    if not _check_rd(update): return
    tid = _get_arg(context)
    if not tid:
        update.message.reply_text("Usage: /rd_download <torrent_id>")
        return
    
    try:
        update.message.reply_text(f"Fetching info for RD torrent `{tid}`...", parse_mode="Markdown")
        info = rd_client.get_torrent_info(tid)
        links = info.get('links', [])
        if not links:
            return update.message.reply_text("No links found in this torrent.")
        
        chat_id = update.effective_chat.id
        filename = info.get('filename', 'Unknown')
        
        # Determine intent (default to telegram)
        dest = context.args[1] if len(context.args) > 1 else "telegram"
        if dest not in ["telegram", "gdrive"]:
             dest = "telegram"

        update.message.reply_text(f"Enqueuing {len(links)} link(s) for `{filename}` to `{dest}`...")
        
        for link in links:
            try:
                unrestricted = rd_client.unrestrict_link(link)
                dl_url = unrestricted['download']
                name = unrestricted['filename']
                file_size = unrestricted.get('filesize', 0)
                
                downloader.process_item(dl_url, name, dest=dest, chat_id=chat_id, size=file_size)
            except Exception as e:
                logger.error(f"Failed to unrestrict/process RD link {link}: {e}")
                update.message.reply_text(f"Failed to process link: {e}")
                
    except Exception as e:
        update.message.reply_text(f"Error: {e}")

def sb_download(update: Update, context: CallbackContext):
    """Manually trigger download for an existing Seedbox torrent hash."""
    if not _check_sb(update): return
    shash = _get_arg(context)
    if not shash:
        update.message.reply_text("Usage: /sb_download <hash>")
        return
    
    try:
        items = sb_client.list_torrents()
        t = next((i for i in items if i['hash'] == shash), None)
        if not t:
            return update.message.reply_text(f"Torrent with hash `{shash}` not found on Seedbox.", parse_mode="Markdown")
        
        base_path = t.get('base_path')
        if not base_path:
            return update.message.reply_text("Could not find base_path for this torrent.")
        
        chat_id = update.effective_chat.id
        name = t.get('name', 'Unknown')
        file_size = t.get('size', 0)
        
        # Determine intent
        dest = context.args[1] if len(context.args) > 1 else "telegram"
        if dest not in ["telegram", "gdrive"]:
             dest = "telegram"

        dl_url = f"sftp://{base_path}"
        update.message.reply_text(f"Enqueuing `{name}` to `{dest}` via SFTP...", parse_mode="Markdown")
        downloader.process_item(dl_url, name, dest=dest, chat_id=chat_id, size=file_size)
        
    except Exception as e:
        update.message.reply_text(f"Error: {e}")

def status(update: Update, context: CallbackContext):
    """Unified status of all active tasks."""
    import time
    from bot.jobs import job_status
    try:
        lines = ["📡 *System Status*"]
        
        # 1. Downloader (Active Transfers)
        active = downloader.get_active_tasks()
        if active:
            lines.append("\n⬇️ *Active Transfers:*")
            for tid, t in active.items():
                start_ago = int(time.time() - t['start_time'])
                lines.append(f"• `{t['name'][:25]}`\n  └ {t['status'].title()} | {start_ago}s ago")
        
        # 2. Seedbox (rtorrent)
        if sb_client:
            sbt = sb_client.list_torrents()
            active_sb = [t for t in sbt if t.get('state') in ['downloading', 'hashing']]
            if active_sb:
                lines.append("\n📦 *Seedbox:*")
                for t in active_sb:
                    lines.append(f"• `{t['name'][:25]}`\n  └ {t['state'].title()} | {t['progress']:.1f}%")
        
        # 3. Real-Debrid
        if rd_client:
            rdt = rd_client.list_torrents()
            active_rd = [t for t in rdt if t['status'] not in ['downloaded', 'dead']]
            if active_rd:
                lines.append("\n☁️ *Real-Debrid:*")
                for t in active_rd:
                    lines.append(f"• `{t['filename'][:25]}`\n  └ {t['status'].replace('_', ' ').title()} | {t['progress']}%")
        
        # 4. yt-dlp Queue
        # Note: job_status is a dict of all jobs. We want active ones.
        active_jobs = {jid: jinfo for jid, jinfo in job_status.items() if jinfo['status'] in ['queued', 'processing']}
        if active_jobs:
            lines.append("\n🎬 *yt-dlp Jobs:*")
            for jid, jinfo in active_jobs.items():
                 lines.append(f"• `{jid}`\n  └ {jinfo['status'].title()} | {jinfo['dest'].upper()}")

        if len(lines) == 1:
            lines.append("\n✅ Everything is idle.")
            
        text = "\n".join(lines)
        update.message.reply_text(text, parse_mode="Markdown")
        
    except Exception as e:
        update.message.reply_text(f"Error getting status: {e}")

# yt-dlp Commands

def ytdl(update: Update, context: CallbackContext):
    """Download video from YouTube/URL to Telegram."""
    _ytdl_generic(update, context, dest="telegram")

def ytdl_gdrive(update: Update, context: CallbackContext):
    """Download video from YouTube/URL to Google Drive."""
    _ytdl_generic(update, context, dest="gdrive")

def _ytdl_generic(update: Update, context: CallbackContext, dest: str):
    url = _get_arg(context)
    if not url:
        update.message.reply_text(f"Usage: /ytdl_{dest} <url>")
        return
    
    # Check if RD has it cached? (Optional logic, skipping for now to keep simple)
    
    chat_id = update.effective_chat.id
    job_id = enqueue_ytdl(url, dest=dest, chat_id=chat_id)
    update.message.reply_text(f"Job queued: `{job_id}` (Dest: {dest})", parse_mode="Markdown")

def rd_torrent_gdrive(update: Update, context: CallbackContext):
    """Add magnet to RD and upload to GDrive."""
    if not _check_rd(update): return
    magnet = _get_arg(context)
    if not magnet:
        update.message.reply_text("Usage: /rd_torrent_gdrive <magnet>")
        return
    
    try:
        resp = rd_client.add_magnet(magnet)
        tid = resp.get('id')
        if tid:
            get_state().set_intent(f"rd_{tid}", "gdrive")
            update.message.reply_text(f"Added to RD (Dest: GDrive). ID: {tid}")
        else:
            update.message.reply_text(f"Added to RD but no ID returned: {resp}")
    except Exception as e:
        update.message.reply_text(f"Error: {e}")

def sb_torrent_gdrive(update: Update, context: CallbackContext):
    """Add magnet to Seedbox and upload to GDrive."""
    import re
    if not _check_sb(update): return
    magnet = _get_arg(context)
    if not magnet:
        update.message.reply_text("Usage: /sb_torrent_gdrive <magnet>")
        return
    
    # Extract hash from magnet for intent
    # magnet:?xt=urn:btih:HASH&...
    match = re.search(r'xt=urn:btih:([a-zA-Z0-9]+)', magnet)
    if match:
        thash = match.group(1).upper()
        get_state().set_intent(f"sb_{thash}", "gdrive")
    else:
        update.message.reply_text("Warning: Could not extract hash from magnet. Intent might fail.")

    try:
        sb_client.add_torrent(magnet)
        update.message.reply_text(f"Added to Seedbox (Dest: GDrive).")
    except Exception as e:
        update.message.reply_text(f"Error: {e}")

def check_job(update: Update, context: CallbackContext):
    if not context.args: return update.message.reply_text("Usage: /job <job_id>")
    info = job_status(context.args[0])
    update.message.reply_text(f"Job Status: {info}")

# RSS Commands

def add_feed(update: Update, context: CallbackContext):
    if not feed_manager: return update.message.reply_text("RSS Manager disabled")
    if not context.args: return update.message.reply_text("Usage: /add_feed <url> [force:rd|sb] [private:true|false]")
    url = context.args[0]
    forced = context.args[1] if len(context.args) > 1 and context.args[1] in ('rd', 'sb') else None
    private = context.args[2].lower() == 'true' if len(context.args) > 2 else False
    
    feed_manager.add_feed(url, forced_backend=forced, private_torrents=private)
    update.message.reply_text(f"Added feed {url}")

def list_feeds(update: Update, context: CallbackContext):
    if not feed_manager: return update.message.reply_text("RSS Manager disabled")
    feeds = feed_manager.list_feeds()
    if not feeds: return update.message.reply_text("No feeds.")
    lines = [f"• {f.url} (force={f.forced_backend}, priv={f.private_torrents})" for f in feeds]
    update.message.reply_text("\n".join(lines))

def poll_feeds(update: Update, context: CallbackContext):
    if not feed_manager: return update.message.reply_text("RSS Manager disabled")
    
    results = []
    def on_decide(backend, entry):
        title = entry.get('title', 'Unknown')
        link = entry.get('link') or entry.get('guid')
        results.append(f"Route {title} -> {backend}")
        
        # Action!
        try:
            if backend == 'rd' and rd_client:
                rd_client.add_magnet(link)
            elif backend == 'sb' and sb_client:
                sb_client.add_torrent(link)
        except Exception as e:
            results.append(f"Error adding {title}: {e}")

    update.message.reply_text("Polling...")
    feed_manager.poll_once(on_decision=on_decide)
    
    if results:
        update.message.reply_text("\n".join(results))
    else:
        update.message.reply_text("No new items routed.")

# --- App ---

def create_app(token: str) -> Updater:
    updater = Updater(token)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    
    # RD
    dp.add_handler(CommandHandler("rd_torrent", rd_torrent))
    dp.add_handler(CommandHandler("rd_torrents", rd_torrents))
    dp.add_handler(CommandHandler("rd_delete", rd_delete))
    dp.add_handler(CommandHandler("rd_downloads", rd_downloads))
    dp.add_handler(CommandHandler("rd_unrestrict", rd_unrestrict))
    dp.add_handler(CommandHandler("rd_download", rd_download)) # New

    
    # Seedbox
    dp.add_handler(CommandHandler("sb_torrent", sb_torrent))
    dp.add_handler(CommandHandler("sb_torrents", sb_torrents))
    dp.add_handler(CommandHandler("sb_stop", sb_stop))
    dp.add_handler(CommandHandler("sb_start", sb_start))
    dp.add_handler(CommandHandler("sb_delete", sb_delete))
    dp.add_handler(CommandHandler("sb_download", sb_download)) # New
    
    # yt-dlp
    dp.add_handler(CommandHandler("rd_torrent_gdrive", rd_torrent_gdrive))
    dp.add_handler(CommandHandler("sb_torrent_gdrive", sb_torrent_gdrive))
    dp.add_handler(CommandHandler("ytdl", ytdl))
    dp.add_handler(CommandHandler("ytdl_gdrive", ytdl_gdrive))
    dp.add_handler(CommandHandler("job", check_job))
    dp.add_handler(CommandHandler("status", status)) # New
    
    # RSS
    dp.add_handler(CommandHandler("add_feed", add_feed))
    dp.add_handler(CommandHandler("list_feeds", list_feeds))
    dp.add_handler(CommandHandler("poll_feeds", poll_feeds))
    
    return updater

def run():
    token = (BOT_TOKEN or os.getenv("BOT_TOKEN", "")).strip()
    if not token:
        logger.error("BOT_TOKEN not set")
        return
    
    # Debug info (safe part only)
    logger.info(f"DEBUG: Token loaded. Length: {len(token)} | Starts with: {token[:4]}... | Ends with: ...{token[-4:]} | Hidden chars check: {repr(token) == repr(token.strip())}")

    updater = create_app(token)
    logger.info("Starting Bot...")
    
    # Attach updater to downloader
    if monitor:
        monitor.downloader.updater = updater
        monitor.start()
    
    # Inject updater into jobs
    jobs_set_updater(updater)

    # Start RSS loop in background if manager exists
    if feed_manager:
        t = threading.Thread(target=feed_manager.run_polling, daemon=True)
        t.start()
    
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    run()
