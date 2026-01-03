
import sys
import os
import logging

# Ensure the project root is in sys.path
sys.path.append(os.getcwd())

from bot.config import load_dotenv
from bot.clients.realdebrid import RDClient, RealDebridNotConfigured, RDAPIError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_rd_downloads")

def fmt_bytes(b):
    """Format bytes to human readable."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if b < 1024.0: 
            return f"{b:.1f}{unit}"
        b /= 1024.0
    return f"{b:.1f}TB"

def main():
    print("Loading environment variables...")
    load_dotenv()
    
    token = os.getenv("RD_ACCESS_TOKEN")
    if not token:
        print("ERROR: RD_ACCESS_TOKEN not found in environment.")
        return
        
    try:
        print("Initializing RDClient...")
        client = RDClient(access_token=token)
        
        # Count total downloads by paginating through all pages
        print("\n--- Counting Total Downloads ---")
        total_count = 0
        page = 1
        all_downloads = []
        
        while True:
            downloads = client.get_downloads(page=page, limit=50)
            if not downloads:
                break
            
            all_downloads.extend(downloads)
            total_count += len(downloads)
            
            # If we got less than 50, we've reached the end
            if len(downloads) < 50:
                break
                
            page += 1
            print(f"Fetched page {page-1}: {len(downloads)} items...")
        
        print(f"\n✓ TOTAL DOWNLOADS IN ACCOUNT: {total_count}")
        
        # Display recent 10
        print(f"\n--- Recent 10 Downloads ---")
        print(f"{'Date':<20} | {'Size':<10} | Filename")
        print("-" * 80)
        
        for d in all_downloads[:10]:
            generated = d.get('generated', 'N/A')
            filename = d.get('filename', 'N/A')
            filesize = d.get('filesize', 0)
            
            print(f"{generated:<20} | {fmt_bytes(filesize):<10} | {filename}")
        
        print(f"\n{'='*80}")
        print(f"Total downloads in account: {total_count}")
        print(f"{'='*80}")
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
