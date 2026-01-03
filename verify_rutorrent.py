
import sys
import os
import logging
from pathlib import Path

# Ensure the project root is in sys.path
sys.path.append(os.getcwd())

import bot.config
from bot.config import load_dotenv
from bot.clients.seedbox import SeedboxClient, SeedboxCommunicationError, SeedboxNotConfigured

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_rutorrent")

def main():
    print("Loading environment variables...")
    load_dotenv()
    
    print("Checking Rutorrent configuration...")
    url = os.getenv("RUTORRENT_URL")
    user = os.getenv("RUTORRENT_USER")
    password = os.getenv("RUTORRENT_PASS")
    
    if not url:
        print("ERROR: RUTORRENT_URL not found in environment.")
        return
    if not user:
        print("ERROR: RUTORRENT_USER not found in environment.")
        return
        
    print(f"URL: {url}")
    print(f"User: {user}")
    
    # Try multiple URL variations
    # Common variations for rutorrent/xmlrpc
    # Try current URL first, then variations
    variations = [url]
    
    # Generate variations only if we need them or want to be robust
    base_url = url.rstrip('/')
    if "action.php" not in base_url and "RPC2" not in base_url:
        variations.append(f"{base_url}/plugins/httprpc/action.php")
        variations.append(f"{base_url}/RPC2")
    
    # De-duplicate
    variations = list(dict.fromkeys(variations))

    success = False

    for try_url in variations:
        try:
            print(f"\n--- Testing URL: {try_url} ---")
            # We must init client with this specific URL
            client = SeedboxClient(url=try_url, user=user, password=password)
            
            print("Attempting to list torrents...")
            torrents = client.list_torrents()
            
            print("SUCCESS! Connected to Rutorrent.")
            print(f"Found {len(torrents)} torrents.\n")
            
            print(f"{'Name':<50} | {'Size':<10} | {'Progress':<8} | {'Status':<12} | {'Down':<10} | {'Up':<10}")
            print("-" * 110)
            
            for t in torrents:
                # Calculate details
                size_bytes = int(t['size'])
                done_bytes = int(t['bytes_done'])
                down_rate = int(t['down_rate'])
                up_rate = int(t['up_rate'])
                is_active = t['active']
                
                # Progress
                progress = 0.0
                if size_bytes > 0:
                    progress = (done_bytes / size_bytes) * 100
                
                # State inference
                state = "Unknown"
                if not is_active:
                    state = "Paused/Stop"
                elif done_bytes >= size_bytes:
                    state = "Seeding"
                else:
                    state = "Downloading"
                
                # Formatting helpers
                def fmt_bytes(b):
                    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                        if b < 1024.0:
                            return f"{b:.1f}{unit}"
                        b /= 1024.0
                    return f"{b:.1f}PB"

                name_short = t['name'][:48] + ".." if len(t['name']) > 50 else t['name']
                
                print(f"{name_short:<50} | {fmt_bytes(size_bytes):<10} | {progress:>6.1f}% | {state:<12} | {fmt_bytes(down_rate)}/s  | {fmt_bytes(up_rate)}/s")
            
            print("-" * 110)
            print(f"\n*** CORRECT URL FOUND: {try_url} ***")
            print("You should update your .env with this URL if it differs.")
            success = True
            break
            
        except SeedboxCommunicationError as e:
            print(f"Failed with {try_url}: {e}")
        except Exception as e:
            print(f"Failed with {try_url}: {e}")
            
    if not success:
        print("\nAll URL variations failed.")

if __name__ == "__main__":
    main()
