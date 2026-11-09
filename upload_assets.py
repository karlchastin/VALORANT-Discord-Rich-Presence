\
\
\

import os
import sys
import time
import base64
import getpass
import argparse
import requests

DEFAULT_APP_ID = "1567969518280773853"
API_BASE = "https://discord.com/api/v10"

def collect_assets(base_dir="assets"):

    assets = []
    subfolders = ["agents", "maps", "modes", "rank_icons"]
    for sub in subfolders:
        folder_path = os.path.join(base_dir, sub)
        if not os.path.isdir(folder_path):
            continue
        for filename in sorted(os.listdir(folder_path)):
            if filename.endswith(".png"):
                key = filename[:-4].lower()
                full_path = os.path.join(folder_path, filename)
                assets.append((key, full_path))

    root_files = [
        "game_icon.png",
        "game_icon_white.png",
        "game_icon_yellow.png",
    ]
    for rf in root_files:
        rp = os.path.join(base_dir, rf)
        if os.path.exists(rp):
            assets.append((rf[:-4].lower(), rp))

    return assets

def get_existing_assets(app_id, headers):

    url = f"{API_BASE}/oauth2/applications/{app_id}/assets"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            existing = {item["name"].lower(): item["id"] for item in resp.json()}
            return existing
        elif resp.status_code == 401:
            print("[ERROR] Authorization failed (HTTP 401). Please check your Discord token.")
            sys.exit(1)
        elif resp.status_code == 404:
            print(f"[ERROR] Application ID {app_id} not found (HTTP 404).")
            sys.exit(1)
        else:
            print(f"[WARNING] Could not fetch existing assets (HTTP {resp.status_code}): {resp.text}")
            return {}
    except Exception as e:
        print(f"[WARNING] Failed to connect to Discord API: {e}")
        return {}

def delete_single_asset(app_id, asset_id, headers):

    url = f"{API_BASE}/oauth2/applications/{app_id}/assets/{asset_id}"
    try:
        resp = requests.delete(url, headers=headers, timeout=15)
        return resp.status_code in (200, 204)
    except Exception:
        return False

def upload_single_asset(app_id, key, file_path, headers, max_retries=5):

    url = f"{API_BASE}/oauth2/applications/{app_id}/assets"

    with open(file_path, "rb") as f:
        b64_data = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "name": key,
        "type": 1,
        "image": f"data:image/png;base64,{b64_data}",
    }

    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            if resp.status_code in (200, 201):
                return True, "Uploaded successfully"
            elif resp.status_code == 429:

                data = resp.json()
                retry_after = float(data.get("retry_after", 3.0))
                wait_time = retry_after + 0.6
                print(f"  [RATE LIMITED] Pausing {wait_time:.2f}s before retrying '{key}'...")
                time.sleep(wait_time)
                continue
            elif resp.status_code == 400:
                return False, f"HTTP 400 Bad Request: {resp.text}"
            elif resp.status_code == 401:
                return False, "HTTP 401 Unauthorized: Invalid token"
            else:
                return False, f"HTTP {resp.status_code}: {resp.text}"
        except requests.RequestException as e:
            print(f"  [NETWORK RETRY] Error: {e}. Retrying in 3s...")
            time.sleep(3.0)

    return False, "Exceeded max retries"

def main():
    parser = argparse.ArgumentParser(description="Upload Rich Presence assets to Discord.")
    parser.add_argument("--app-id", default=DEFAULT_APP_ID, help="Discord Application ID")
    parser.add_argument("--token", default=os.environ.get("DISCORD_TOKEN"), help="Discord User Authorization Token")
    parser.add_argument("--assets-dir", default="assets", help="Path to assets folder")
    parser.add_argument("--delay", type=float, default=1.3, help="Delay in seconds between uploads to prevent rate limiting")
    parser.add_argument("--overwrite", action="store_true", help="Delete and re-upload assets if they already exist on Discord")
    parser.add_argument("--keys", nargs="+", help="Specific asset key(s) to upload or overwrite (e.g. splash_sunset)")
    args = parser.parse_args()

    print("=" * 60)
    print(" Discord Rich Presence Art Assets Uploader")
    print(f" Target Application ID: {args.app_id}")
    print("=" * 60)

    token = args.token
    if not token:
        print("\nTo upload assets, your Discord user authorization token is required.")
        print("How to get it:")
        print("  1. In your browser, open https://discord.com/developers/applications")
        print("  2. Press F12 to open Developer Tools -> click the 'Network' tab.")
        print("  3. Refresh the page or click 'Art Assets'.")
        print("  4. Click any request to discord.com/api and copy the 'Authorization' header value.")
        print()
        token = getpass.getpass("Enter your Discord Token (input hidden): ").strip()

    if not token:
        print("[ERROR] No authorization token provided. Exiting.")
        sys.exit(1)

    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    print("\n1. Scanning local assets...")
    all_assets = collect_assets(args.assets_dir)
    if args.keys:
        target_keys = {k.lower() for k in args.keys}
        all_assets = [(k, p) for (k, p) in all_assets if k.lower() in target_keys]
    print(f"   Found {len(all_assets)} local PNG asset(s) to process.")

    print("\n2. Checking existing assets on Discord...")
    existing = get_existing_assets(args.app_id, headers)
    print(f"   Application currently has {len(existing)} assets uploaded.")

    if args.overwrite:
        to_upload = all_assets
        already_done = 0
    else:
        to_upload = [(k, p) for (k, p) in all_assets if k not in existing]
        already_done = len(all_assets) - len(to_upload)

    print("\n3. Upload plan:")
    print(f"   - Already on Discord: {already_done}")
    print(f"   - To upload:         {len(to_upload)}")

    if not to_upload:
        print("\n[SUCCESS] All assets are already uploaded to Discord!")
        return

    print("\n4. Uploading assets (with automatic rate-limit backoff)...")
    success_count = 0
    fail_count = 0

    for idx, (key, path) in enumerate(to_upload, start=1):
        if key in existing and args.overwrite:
            print(f"[{idx}/{len(to_upload)}] Overwriting '{key}': deleting old asset...", end=" ", flush=True)
            delete_single_asset(args.app_id, existing[key], headers)
            time.sleep(1.0)
        print(f"[{idx}/{len(to_upload)}] Uploading '{key}' ({os.path.basename(path)})...", end=" ", flush=True)
        ok, msg = upload_single_asset(args.app_id, key, path, headers)
        if ok:
            print("OK")
            success_count += 1
        else:
            print(f"FAILED ({msg})")
            fail_count += 1
            if "HTTP 401" in msg:
                print("\n[FATAL] Token invalid. Aborting.")
                break

        time.sleep(args.delay)

    print("\n" + "=" * 60)
    print(" Upload Complete!")
    print(f"   Successfully uploaded: {success_count}")
    print(f"   Failed:                {fail_count}")
    print(f"   Total assets on App:   {already_done + success_count}/300")
    print("=" * 60)
    print("Note: Discord takes 5-10 minutes to propagate new assets to edge CDN servers.")

if __name__ == "__main__":
    main()
