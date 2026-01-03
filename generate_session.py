"""Generate Telethon session string for Heroku deployment.

Run this script LOCALLY to generate a session string that can be
added to your .env file as TELEGRAM_SESSION.

This allows the bot to work on Heroku without interactive authentication.
"""

import asyncio
import sys
from telethon import TelegramClient
from telethon.sessions import StringSession

# Use bot's config which already has load_dotenv
from bot.config import load_dotenv, TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE

# Load .env file
load_dotenv()

if not (TELEGRAM_API_ID and TELEGRAM_API_HASH and TELEGRAM_PHONE):
    print("❌ Error: TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_PHONE must be set in .env")
    print("\nCurrent values:")
    print(f"  TELEGRAM_API_ID: {TELEGRAM_API_ID or 'NOT SET'}")
    print(f"  TELEGRAM_API_HASH: {TELEGRAM_API_HASH or 'NOT SET'}")
    print(f"  TELEGRAM_PHONE: {TELEGRAM_PHONE or 'NOT SET'}")
    sys.exit(1)

async def generate_session():
    """Generate and save session string."""
    print(f"📱 Generating session for {TELEGRAM_PHONE}...")
    print("You will receive a code on Telegram. Enter it when prompted.\n")
    
    # Create client with string session
    async with TelegramClient(StringSession(), int(TELEGRAM_API_ID), TELEGRAM_API_HASH) as client:
        await client.start(phone=TELEGRAM_PHONE)
        
        # Get session string
        session_string = client.session.save()
        
        print("\n✅ Session generated successfully!")
        print("\n" + "="*60)
        print("Add this to your .env file:")
        print("="*60)
        print(f'TELEGRAM_SESSION="{session_string}"')
        print("="*60)
        print("\nThen push to Heroku:")
        print("heroku config:set TELEGRAM_SESSION=\"<session_string>\"")
        print("\nOr add it via Heroku dashboard under Settings > Config Vars")

if __name__ == "__main__":
    asyncio.run(generate_session())

