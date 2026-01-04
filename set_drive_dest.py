
import os
from pathlib import Path

env_path = Path(".env")
remote_name = "spartan22"

if not env_path.exists():
    print("❌ .env not found")
    exit(1)

lines = env_path.read_text().splitlines()
new_lines = []
found = False

for line in lines:
    if line.strip().startswith("DRIVE_DEST="):
        new_lines.append(f"DRIVE_DEST={remote_name}:/")
        found = True
    else:
        new_lines.append(line)

if not found:
    new_lines.append(f"\nDRIVE_DEST={remote_name}:/")

env_path.write_text("\n".join(new_lines) + "\n")
print(f"✅ Updated DRIVE_DEST to {remote_name}:/ in .env")
