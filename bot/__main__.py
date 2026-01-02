
import asyncio
from bot.config import BOT_TOKEN


async def main():
    print("WZML-X v1 FINAL started")
    # Start telegram bot if configured
    if BOT_TOKEN:
        # Import lazily to avoid requiring telegram deps unless needed
        from bot.telegram import run as run_telegram
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, run_telegram)


if __name__ == "__main__":
    asyncio.run(main())
