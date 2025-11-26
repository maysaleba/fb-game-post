import json
import requests
import sys
import os
import time
from typing import Iterable, List

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

# === Settings ===
BATCH_SIZE = 100             # how many slugs/ids per batch request
RPS_BUDGET = 4               # IGDB cap is 4 req/sec
SAFETY_DELAY = 1.0 / (RPS_BUDGET - 0.5)  # ~0.33s between calls
MAX_RETRIES = 5

slug_overrides = {
    "survival-kids": "survival-kids--1",
    "doom": "doom--1",
    "blasphemous-2": "blasphemous-ii",
    "regalia-of-men-and-monarchs-royal-edition": "regalia-royal-edition", 
    "terra-nil": "terra-nil--1", 
    "disney-epic-mickey-rebrushed": "epic-mickey-rebrushed",
    "bladechimera": "blade-chimera",
    "climb": "climb--5",
    "unicorn-overlord": "unicorn-overlord--1",
    "rune-factory-guardians-of-azuma": "rune-factory-guardians-of-azuma--1",
    "atelier-arland-series-deluxe-pack": "atelier-alchemists-of-arland-1-2-3-dx",
    "sunseed-island-new-journey-collection": "sunseed-island",
    "fate-extella-link": "fate-slash-extella-link",
    "grand-theft-auto-the-trilogy-the-definitive-edition": "grand-theft-auto-the-trilogy-the-definitive-edition--1",
    "final-fantasy-x-x-2-hd-remaster": "final-fantasy-x-slash-x-2-hd-remaster",
    "fate-extella-the-umbral-star": "fate-slash-extella-the-umbral-star",
    "ni-no-kuni-ii-revenant-kingdom-princes-edition": "ni-no-kuni-ii-revenant-kingdom-the-princes-edition",
    "hades": "hades--1",
    "street-fighter-6": "street-fighter-6--1",
    "mega-man-zero-zx-legacy-collection": "mega-man-zero-slash-zx-legacy-collection",
    "live-a-live": "live-a-live--1",
    "ashen": "ashen--1",
    "no-mans-sky": "no-man-s-sky",
    "monster-hunter-rise-plus-sunbreak-deluxe": "monster-hunter-rise-plus-sunbreak-deluxe-edition",
    "the-witcher-3-wild-hunt-complete-edition": "the-witcher-3-wild-hunt-complete-edition--1",
    "outlast-2": "outlast-ii",
    "sniper-elite-3-ultimate-edition": "sniper-elite-iii-ultimate-edition",
    "potion-permit": "potion-permit--1",
    "devil-may-cry-3-special-edition": "devil-may-cry-3-dantes-awakening-special-edition",
    "resident-evil": "resident-evil--3",
    "the-legend-of-zelda-links-awakening": "the-legend-of-zelda-links-awakening--1",
    "wwe-2k25-standard-edition": "wwe-2k25",
    "groundskeeper2": "groundskeeper-2",
    "dont-starve-nintendo-edition": "don-t-starve",
    "reaper-tale-of-a-pale-swordsman": "reaper-tale-of-a-pale-swordsman--1",
    "valkyria-chronicles-plus-valkyria-chronicles-4-bundle": "valkyria-chronicles-bundle"
}

def chunked(iterable: List, n: int) -> Iterable[List]:
    for i in range(0, len(iterable), n):
        yield iterable[i:i+n]

def igdb_post(session: requests.Session, url: str, headers: dict, body: str) -> requests.Response:
    """POST with simple pacing + 429 backoff (uses reset headers if present)."""
    for attempt in range(1, MAX_RETRIES + 1):
        resp = session.post(url, headers=headers, data=body)
        if resp.status_code == 200:
            time.sleep(SAFETY_DELAY)
            return resp

        if resp.status_code == 429:
            # Try to honor reset headers if provided
            reset_after = resp.headers.get("x-ratelimit-reset") or resp.headers.get("ratelimit-reset")
            if reset_after:
                try:
                    reset_after = float(reset_after)
                    now = time.time()
                    # Some APIs send epoch seconds, others seconds-to-reset — handle both heuristically
                    sleep_for = reset_after - now if reset_after > now else reset_after
                    sleep_for = max(0.5, min(10, sleep_for))
                except Exception:
                    sleep_for = 2.0
            else:
                sleep_for = 2.0 * attempt  # backoff
            print(f"⏳ 429 Too Many Requests. Sleeping {sleep_for:.2f}s (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(sleep_for)
            continue

        if resp.status_code >= 500:
            # transient server error
            sleep_for = 1.0 * attempt
            print(f"⚠️ {resp.status_code} server error. Sleeping {sleep_for:.2f}s (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(sleep_for)
            continue

        # Non-retryable
        try:
            print(f"❌ {resp.status_code} error: {resp.text[:300]}")
        finally:
            resp.raise_for_status()

    raise RuntimeError(f"IGDB request failed after {MAX_RETRIES} retries: {url}")

# === Load input ===
if not os.path.exists(INPUT_FILE):
    print(f"❌ Input file not found: {INPUT_FILE}")
    sys.exit(1)

with open(INPUT_FILE, 'r', encoding='utf-8') as f:
    games = json.load(f)

# === Get access token ===
token_response = requests.post(
    TOKEN_URL,
    data={
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'client_credentials'
    }
)
token_response.raise_for_status()
access_token = token_response.json().get('access_token')
headers = {
    'Client-ID': CLIENT_ID,
    'Authorization': f'Bearer {access_token}'
}

session = requests.Session()

# === Build slug list (with overrides) ===
input_slugs = []
for g in games:
    s = g.get('slug', '')
    s = slug_overrides.get(s, s)
    if s:
        input_slugs.append(s)

if not input_slugs:
    print("⚠️ No slugs found in input.")
    sys.exit(0)

# === 1) Resolve many slugs -> ids in batches ===
slug_to_id = {}  # slug -> id
print(f"🔎 Resolving {len(input_slugs)} slugs to IGDB IDs ...")
for group in chunked(input_slugs, BATCH_SIZE):
    in_list = ",".join(f'"{s}"' for s in group)
    q = f'fields id,slug; where slug = ({in_list}); limit {BATCH_SIZE};'
    r = igdb_post(session, GAMES_URL, headers, q)
    data = r.json()
    for item in data:
        slug_to_id[item['slug']] = item['id']

# (Optional) warn about any missing slugs
missing = [s for s in input_slugs if s not in slug_to_id]
if missing:
    print(f"⚠️ {len(missing)} slugs not found in IGDB: {missing[:10]}{' ...' if len(missing)>10 else ''}")

# === 2) Fetch screenshots for many IDs in batches ===
id_to_screens = {}  # game_id -> [urls]
ids = [gid for gid in slug_to_id.values() if gid is not None]
print(f"🖼️ Fetching screenshots for {len(ids)} IGDB IDs ...")
for group in chunked(ids, BATCH_SIZE):
    in_list = ",".join(str(x) for x in group)
    q = f'fields url,game; where game = ({in_list}); limit 500;'
    r = igdb_post(session, SCREENSHOTS_URL, headers, q)
    data = r.json()
    # Accumulate screenshots per game
    for item in data:
        game_id = item['game']
        url = "https:" + item['url'].replace('t_thumb', 't_720p')
        id_to_screens.setdefault(game_id, []).append(url)

# === 3) Merge back into your results (require >= 3 screenshots) ===
results = []
for g in games:
    s = slug_overrides.get(g.get('slug', ''), g.get('slug', ''))
    gid = slug_to_id.get(s)
    if not gid:
        continue
    urls = id_to_screens.get(gid, [])
    if len(urls) < 3:
        continue
    entry = g.copy()
    entry['screenshots'] = urls
    results.append(entry)

# === Save results ===
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"✅ Saved {len(results)} games with screenshots to {OUTPUT_FILE}")
