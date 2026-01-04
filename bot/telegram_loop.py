import asyncio
import threading
import logging

logger = logging.getLogger(__name__)

_loop = None
_thread = None


def _run_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


def get_telegram_loop() -> asyncio.AbstractEventLoop:
    global _loop, _thread

    if _loop:
        return _loop

    _loop = asyncio.new_event_loop()
    _thread = threading.Thread(
        target=_run_loop,
        args=(_loop,),
        daemon=True,
        name="telethon-loop"
    )
    _thread.start()

    logger.info("Telethon asyncio loop started in dedicated thread")
    return _loop
