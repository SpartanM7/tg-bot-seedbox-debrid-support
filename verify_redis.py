
import os
import sys
import logging

# Ensure the project root is in sys.path
sys.path.append(os.getcwd())

from bot.config import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_redis")

def main():
    print("Loading environment variables...")
    load_dotenv()
    
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("ERROR: REDIS_URL not found in environment.")
        print("If you are using Upstash, it should look like: rediss://default:password@endpoint:port")
        return
        
    print(f"Connecting to Redis at: {redis_url.split('@')[-1]} (password hidden)")
    
    try:
        import redis
    except ImportError:
        print("ERROR: redis-py not installed. Run: pip install redis")
        return

    try:
        # Initializing Redis client
        # For Upstash (SSL), rediss:// handles it automatically
        r = redis.from_url(redis_url, decode_responses=True)
        
        print("\n--- Testing Connection ---")
        # Pinging the server
        if r.ping():
            print("✅ SUCCESS: Ping successful! Connected to Redis.")
        else:
            print("❌ ERROR: Connected but ping failed.")
            return

        print("\n--- Testing Data Persistence (SET/GET) ---")
        test_key = "bot_verify_test"
        test_val = "working_fine"
        
        r.set(test_key, test_val, ex=60) # expires in 60s
        val = r.get(test_key)
        
        if val == test_val:
            print(f"✅ SUCCESS: Data SET and GET verified ('{val}')")
        else:
            print(f"❌ ERROR: Data mismatch. Expected '{test_val}', got '{val}'")
            return

        print("\n--- Database Info ---")
        info = r.info()
        print(f"Redis Version: {info.get('redis_version')}")
        print(f"Connected Clients: {info.get('connected_clients')}")
        print(f"Used Memory: {info.get('used_memory_human')}")
        
        print("\n🎉 CONNECTION VERIFIED! Your Upstash Redis is ready for Heroku.")
            
    except redis.ConnectionError as e:
        print(f"\n❌ CONNECTION ERROR: {e}")
        print("\nPossible reasons:")
        print("1. Incorrect password or username.")
        print("2. Endpoint URL is wrong.")
        print("3. If using Upstash, ensure the URL starts with 'rediss://' (with two 's') for SSL.")
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
