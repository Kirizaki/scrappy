import shutil
import subprocess
import os
import re
import sys
from datetime import datetime

def backup_offers():
    source = "offers.csv"
    backup_dir = "backups"
    
    if not os.path.exists(source):
        print(f"Error: {source} not found.")
        return False
        
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        
    # Create a timestamped backup name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f"offers_{timestamp}.csv")
    
    # Also update the main backup file as requested
    main_backup = os.path.join(backup_dir, "offers.csv")
    
    try:
        shutil.copy2(source, backup_file)
        shutil.copy2(source, main_backup)
        print(f"Backup created: {backup_file}")
        print(f"Updated main backup: {main_backup}")
        return True
    except Exception as e:
        print(f"Error during backup: {e}")
        return False

def run_tunnel():
    print("Starting Cloudflare tunnel...")
    cmd = ["cloudflared", "tunnel", "--url", "http://localhost:8000", "--protocol", "http2"]
    
    try:
        # We use Popen to capture output in real-time or at least check for the URL
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        url_found = False
        for line in process.stdout:
            # Print the line to the console
            print(line, end="")
            
            # Look for the .trycloudflare.com URL
            if not url_found:
                match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if match:
                    url = match.group(0)
                    print("\n" + "="*50)
                    print(f"TUNNEL URL: {url}")
                    print("="*50 + "\n")
                    url_found = True
                    
    except KeyboardInterrupt:
        print("\nTunnel stopped by user.")
    except Exception as e:
        print(f"Error running tunnel: {e}")

if __name__ == "__main__":
    if backup_offers():
        run_tunnel()
    else:
        print("Backup failed. Tunnel will not start.")
