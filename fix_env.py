"""Add Telegram credentials to .env file."""
from pathlib import Path

# Read existing .env
env_path = Path(".env")
if not env_path.exists():
    print("❌ .env file not found!")
    exit(1)

content = env_path.read_text()
lines = content.splitlines()

# Check if Telegram vars already exist
has_api_id = any("TELEGRAM_API_ID" in line for line in lines)
has_api_hash = any("TELEGRAM_API_HASH" in line for line in lines)
has_phone = any("TELEGRAM_PHONE" in line for line in lines)
has_drive = any("DRIVE_DEST" in line for line in lines)

if has_api_id and has_api_hash and has_phone and has_drive:
    print("✅ Telegram and GDrive credentials already in .env")
else:
    print("Updating .env...")
    
    # Remove any existing partial Telegram lines
    lines = [l for l in lines if not l.strip().startswith("TELEGRAM_")]
    
    # Add Telegram credentials
    lines.append("")
    lines.append("# Telegram API credentials")
    lines.append("TELEGRAM_API_ID=1411674")
    lines.append("TELEGRAM_API_HASH=5122514c8acb532040486d383b4674c7")
    lines.append("TELEGRAM_PHONE=+918368395994")
    
    lines.append("")
    lines.append("# Google Drive Configuration")
    lines.append("DRIVE_DEST=gdrive:/")
    
    # Write back
    env_path.write_text("\n".join(lines) + "\n")
    print("✅ Added Telegram credentials to .env")

# Verify
print("\nVerifying...")
from bot.config import load_dotenv, TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE
load_dotenv()

print(f"TELEGRAM_API_ID: {TELEGRAM_API_ID}")
print(f"TELEGRAM_API_HASH: {TELEGRAM_API_HASH}")
print(f"TELEGRAM_PHONE: {TELEGRAM_PHONE}")

if TELEGRAM_API_ID and TELEGRAM_API_HASH and TELEGRAM_PHONE:
    print("\n✅ All set! Now run: python generate_session.py")
else:
    print("\n❌ Still not working. Please manually add these lines to .env:")
    print("TELEGRAM_API_ID=1411674")
    print("TELEGRAM_API_HASH=5122514c8acb532040486d383b4674c7")
    print("TELEGRAM_PHONE=+918368395994")
