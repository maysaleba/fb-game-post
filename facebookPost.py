# facebookPost.py
import os
import sys
import json
import requests
from datetime import datetime
import time

# ===== CLI: platform =====
if len(sys.argv) != 2:
    print("Usage: python facebookPost.py <platform>")
    sys.exit(1)

PLATFORM = sys.argv[1].strip().lower()
CONFIG_PATH = f"platforms/{PLATFORM}/config.json"

# ===== Load platform-specific config =====
if not os.path.exists(CONFIG_PATH):
    print(f"❌ Config file not found: {CONFIG_PATH}")
    sys.exit(1)

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    cfg = json.load(f)

# ===== Facebook config pulled from platform config (with sensible fallbacks) =====
PAGE_ID = cfg.get("fb_page_id", "110345971129305")


# ==== TEST TOKEN ===
ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN") or cfg.get("fb_access_token") or \
    "EAAQQDe5YQC4BPJPPsPMXxsPYJ3gblJs3SDsCYG25QTlhIgMj2lrjR6X9VP9kYxdX1PI3Ty01FNsviagC0UbxwvISknFb870L3NUZBQ6bL1EXR7YOT0ndsMfO2z1aNZAK2V8BVgKlrZAfuQZBDCMIVn2yRkcPdG4w8eR4HaReV4CUShxMHubyZBQoSAqGOngZCvAeA9lvTisnuEqSiiRlmq6TsZD"


# ==== LIVE TOKEN ===
#ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN") or cfg.get("fb_access_token") or \
#   "EAAKiZA2yp9csBPLlAqZBP3vc8HZBZCyhZChHalUT4mUBrl7vDtZCjZC9ZCnZBx5G5dewt7LwcuSp74caWKz3RzbshTda4COlZB3p9ZCMp6fUuApVW3au43mfIafnKysyGC3joWGHyAtUDsQuMwZCnNg5QSP0scfyWy8iAZByuZBfw23bgzIS1C2AORoRaSskinwdohvG20NRLYZC2MZD"

IMAGE_FOLDER = cfg.get("fb_image_folder")
POST_TITLE = cfg.get("fb_post_title", "Trending Games On Sale")
COMMENTS = cfg.get("fb_comments", [])

# ===== Validate required fields =====
if not IMAGE_FOLDER:
    print("❌ 'fb_image_folder' missing in platform config.")
    sys.exit(1)

# ===== Read all image files =====
if not os.path.isdir(IMAGE_FOLDER):
    print(f"❌ Folder not found: {IMAGE_FOLDER}")
    sys.exit(1)

image_files = [
    os.path.join(IMAGE_FOLDER, f)
    for f in sorted(os.listdir(IMAGE_FOLDER))
    if f.lower().endswith(('.jpg', '.jpeg', '.png'))
]

if not image_files:
    print("⚠️ No image files found.")
    sys.exit(0)

print(f"🖼️ Found {len(image_files)} images in {IMAGE_FOLDER}")

# ===== Upload images with published=false =====
uploaded_media = []

for path in image_files:
    print(f'📤 Uploading: {path}')
    with open(path, 'rb') as img_file:
        upload_url = f'https://graph.facebook.com/v23.0/{PAGE_ID}/photos'
        response = requests.post(
            upload_url,
            files={'source': img_file},
            data={
                'published': 'false',
                'access_token': ACCESS_TOKEN
            },
            timeout=60
        )
    result = response.json()
    if 'id' in result:
        media_id = result['id']
        uploaded_media.append({'media_fbid': media_id})
        print(f'✅ Uploaded: {media_id}')
    else:
        print(f'❌ Upload failed: {result}')

# ===== Attempt to post all uploaded images =====
if not uploaded_media:
    print("⚠️ No images uploaded successfully.")
    sys.exit(0)

post_message = f"{POST_TITLE} - {datetime.now().strftime('%b %d %Y')}"
print(f"\n📝 Publishing post with {len(uploaded_media)} images...")

post_url = f'https://graph.facebook.com/v23.0/{PAGE_ID}/feed'
payload = {
    'message': post_message,
    'access_token': ACCESS_TOKEN,
    'attached_media': uploaded_media
}

response = requests.post(post_url, json=payload, timeout=60)
res_json = response.json()

if 'id' in res_json:
    post_id = res_json["id"]
    print(f'✅ Post published: {post_id}')

    # ===== Add multiple comments from config (can be empty) =====
    for text in COMMENTS:
        comment_url = f"https://graph.facebook.com/v23.0/{post_id}/comments"
        comment_payload = {
            'message': text,
            'access_token': ACCESS_TOKEN
        }

        comment_response = requests.post(comment_url, data=comment_payload, timeout=60)
        result = comment_response.json()

        if 'id' in result:
            print(f'💬 Comment added: {result["id"]}')
        else:
            print(f'❌ Failed to add comment: {result}')

        time.sleep(2)  # optional delay to mimic human behavior

else:
    print(f'❌ Failed to publish post:\n{res_json}')
