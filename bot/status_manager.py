"""Live status message manager with auto-update."""

import asyncio
import logging
import time
import threading
from typing import Dict, Tuple, Optional, Callable
from telegram import Bot
from telegram.error import BadRequest, Unauthorized

logger = logging.getLogger(__name__)

class StatusManager:
    """Manages live auto-updating status messages."""

    def __init__(self, update_interval: int = 60):
        self.update_interval = update_interval
        # Map: user_id -> (message_id, thread)
        self.active_status_messages: Dict[int, Tuple[int, threading.Thread, threading.Event]] = {}
        self._bot: Optional[Bot] = None
        self._status_generator: Optional[Callable] = None
        self._lock = threading.Lock()

    def set_bot(self, bot: Bot):
        """Set the bot instance for message operations."""
        self._bot = bot

    def set_status_generator(self, func: Callable[[], str]):
        """Set the function that generates status text."""
        self._status_generator = func

    def start_live_status(self, user_id: int, chat_id: int, message_id: int):
        """Start auto-updating a status message."""
        # Cancel old task if exists
        self.stop_live_status(user_id, chat_id)

        # Create stop event
        stop_event = threading.Event()

        # Start new update thread
        thread = threading.Thread(
            target=self._auto_update_loop,
            args=(user_id, chat_id, message_id, stop_event),
            daemon=True
        )

        with self._lock:
            self.active_status_messages[user_id] = (message_id, thread, stop_event)

        thread.start()
        logger.info(f"Started live status for user {user_id}, message {message_id}")

    def stop_live_status(self, user_id: int, chat_id: int):
        """Stop auto-updating and delete old status message."""
        with self._lock:
            if user_id in self.active_status_messages:
                old_msg_id, old_thread, stop_event = self.active_status_messages.pop(user_id)

                # Signal thread to stop
                stop_event.set()

                # Try to delete old message
                try:
                    self._bot.delete_message(chat_id=chat_id, message_id=old_msg_id)
                    logger.debug(f"Deleted old status message {old_msg_id}")
                except (BadRequest, Unauthorized) as e:
                    logger.debug(f"Could not delete old status message: {e}")

    def _auto_update_loop(self, user_id: int, chat_id: int, message_id: int, stop_event: threading.Event):
        """Background loop that updates the status message every 60 seconds."""
        try:
            while not stop_event.is_set():
                # Sleep in small intervals to allow quick stopping
                for _ in range(self.update_interval):
                    if stop_event.is_set():
                        return
                    time.sleep(1)

                # Generate new status text
                if not self._status_generator:
                    logger.error("No status generator set!")
                    break

                try:
                    status_text = self._status_generator()
                except Exception as e:
                    logger.error(f"Error generating status text: {e}")
                    break

                # Update message
                try:
                    self._bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=status_text,
                        parse_mode="Markdown"
                    )
                    logger.debug(f"Updated status message {message_id}")
                except BadRequest as e:
                    if "message is not modified" in str(e).lower():
                        continue  # Content unchanged, skip
                    else:
                        logger.warning(f"Failed to update status: {e}")
                        break
                except Unauthorized:
                    logger.warning("Bot blocked by user, stopping updates")
                    break
                except Exception as e:
                    logger.error(f"Unexpected error updating status: {e}")
                    break

        except Exception as e:
            logger.error(f"Error in status update loop: {e}")
        finally:
            # Cleanup
            with self._lock:
                if user_id in self.active_status_messages:
                    self.active_status_messages.pop(user_id, None)
            logger.debug(f"Status update loop ended for user {user_id}")

# Global instance
_status_manager = None

def get_status_manager() -> StatusManager:
    """Get the global StatusManager instance."""
    global _status_manager
    if _status_manager is None:
        _status_manager = StatusManager(update_interval=60)
    return _status_manager
