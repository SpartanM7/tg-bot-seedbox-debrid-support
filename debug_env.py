"""Debug script to check .env file contents."""
import os
from pathlib import Path

env_path = Path(".env")
if not env_path.exists():
    print("❌ .env file not found!")
else:
    print("✅ .env file found")
    print("\nRaw .env contents:")
    print("="*60)
    content = env_path.read_text()
    print(content)
    print("="*60)
    
    print("\nParsing .env manually:")
    for i, line in enumerate(content.splitlines(), 1):
        line_stripped = line.strip()
        print(f"Line {i}: {repr(line_stripped)}")
        if line_stripped and not line_stripped.startswith("#") and "=" in line_stripped:
            key, val = line_stripped.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if "TELEGRAM" in key:
                print(f"  -> {key} = {repr(val)}")
    
    print("\nNow loading via bot.config:")
    from bot.config import load_dotenv, TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE
    load_dotenv()
    print(f"TELEGRAM_API_ID: {repr(TELEGRAM_API_ID)}")
    print(f"TELEGRAM_API_HASH: {repr(TELEGRAM_API_HASH)}")
    print(f"TELEGRAM_PHONE: {repr(TELEGRAM_PHONE)}")
