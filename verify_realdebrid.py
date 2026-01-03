
import sys
import os
import logging
import json

# Ensure the project root is in sys.path
sys.path.append(os.getcwd())

from bot.config import load_dotenv
from bot.clients.realdebrid import RDClient, RealDebridNotConfigured, RDAPIError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_rd")

def main():
    print("Loading environment variables...")
    load_dotenv()
    
    token = os.getenv("RD_ACCESS_TOKEN")
    if not token:
        print("ERROR: RD_ACCESS_TOKEN not found in environment.")
        return
        
    print(f"Token found: {token[:6]}...{token[-4:]}")
    
    try:
        print("Initializing RDClient...")
        client = RDClient(access_token=token)
        
        print("\n--- Checking User Info ---")
        user = client.get_user_info()
        print(f"Username: {user.get('username')}")
        print(f"Type: {user.get('type')} (Premium: {user.get('premium')})")
        print(f"Expiration: {user.get('expiration')}")
        
        print("\n--- Listing Recent Torrents (Limit 5) ---")
        torrents = client.list_torrents(limit=5)
        print(f"Found {len(torrents)} torrents:")
        
        print(f"{'Status':<12} | {'Progress':<8} | Filename")
        print("-" * 60)
        
        for t in torrents:
            status = t.get('status')
            progress = t.get('progress', 0)
            filename = t.get('filename')
            print(f"{status:<12} | {progress:>6}% | {filename}")
            
        print("\nSUCCESS! Real-Debrid is connected.")
            
    except RealDebridNotConfigured as e:
        print(f"CONFIGURATION ERROR: {e}")
    except RDAPIError as e:
        print(f"API ERROR: {e}")
    except Exception as e:
        print(f"UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
