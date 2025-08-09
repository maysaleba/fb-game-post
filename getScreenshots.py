import json
import requests
import sys
import os

# === Platform Argument ===
if len(sys.argv) != 2:
    print("Usage: python getScreenshots.py <platform>")
    sys.exit(1)

PLATFORM = sys.argv[1]
INPUT_FILE = f'output/cheapest_{PLATFORM}.json'
OUTPUT_FILE = f'output/games_with_screenshots_{PLATFORM}.json'

# === IGDB Credentials ===
CLIENT_ID = 'jxnpf283ohcc4z1ou74w2vzkdew9vi'
CLIENT_SECRET = 'q876s02axklhzfu740cznm498arxv2'
TOKEN_URL = 'https://id.twitch.tv/oauth2/token'
GAMES_URL = 'https://api.igdb.com/v4/games'
SCREENSHOTS_URL = 'https://api.igdb.com/v4/screenshots'

# Step 1: Load games from file
if not os.path.exists(INPUT_FILE):
    print(f"❌ Input file not found: {INPUT_FILE}")
    sys.exit(1)

with open(INPUT_FILE, 'r', encoding='utf-8') as f:
    games = json.load(f)

# Step 2: Get access token
token_response = requests.post(
    TOKEN_URL,
    data={
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'client_credentials'
    }
)
access_token = token_response.json().get('access_token')
headers = {
    'Client-ID': CLIENT_ID,
    'Authorization': f'Bearer {access_token}'
}

# Step 3: Loop through games
results = []
for game in games:
    slug = game['slug']
    game_query = f'where slug = "{slug}"; fields id;'
    game_res = requests.post(GAMES_URL, headers=headers, data=game_query)
    game_data = game_res.json()
    if not game_data:
        continue
    game_id = game_data[0]['id']

    # Get screenshots
    screenshot_query = f'where game = {game_id}; fields url;'
    screenshot_res = requests.post(SCREENSHOTS_URL, headers=headers, data=screenshot_query)
    screenshot_data = screenshot_res.json()

    if len(screenshot_data) < 3:
        continue

    # Build full URLs with t_720p
    screenshot_urls = [
        "https:" + s['url'].replace('t_thumb', 't_720p') for s in screenshot_data
    ]

    # Add screenshots to original game metadata
    game_entry = game.copy()
    game_entry['screenshots'] = screenshot_urls
    results.append(game_entry)

# Step 4: Save results
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2)

print(f"✅ Saved {len(results)} games with screenshots to {OUTPUT_FILE}")
