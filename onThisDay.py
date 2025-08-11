import os
import sys
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from collage import make_collage  # uses canvas_w, cols, aspect_ratio, ...

# ========= CONFIG =========
INPUT_LOC = "https://raw.githubusercontent.com/maysaleba/maysaleba.github.io/main/src/csvjson.json"
OUTPUT_DIR = "output"

# Collage (fixed width, dynamic height)
CANVAS_WIDTH = 1820
GRID_COLS = 2
GRID_MODE = "cover"  # 'fit' or 'cover'
GRID_MARGIN = 0
GRID_GUTTER = 0
GRID_BG = (16, 16, 16)

# IGDB creds (use GitHub Actions secrets ideally)
CLIENT_ID = os.getenv("IGDB_CLIENT_ID", "jxnpf283ohcc4z1ou74w2vzkdew9vi")
CLIENT_SECRET = os.getenv("IGDB_CLIENT_SECRET", "q876s02axklhzfu740cznm498arxv2")

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
GAMES_URL = "https://api.igdb.com/v4/games"
SCREENSHOTS_URL = "https://api.igdb.com/v4/screenshots"

# ========= HELPERS =========
def slug_variants(slug: str) -> list:
    variants = [slug]
    if "-switch" in slug:
        variants.append(slug.replace("-switch", ""))
    if "-ps4" in slug:
        variants.append(slug.replace("-ps4", ""))
    if "-ps5" in slug:
        variants.append(slug.replace("-ps5", ""))
    if slug.endswith("-nintendo-switch"):
        variants.append(slug.replace("-nintendo-switch", ""))
    manual = {"doom": "doom--1", "survival-kids": "survival-kids--1"}
    if slug in manual:
        variants.insert(0, manual[slug])
    seen, unique = set(), []
    for s in variants:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique

def safe_float(x, default=0.0):
    try:
        if x is None: return default
        if isinstance(x, (int, float)): return float(x)
        return float(str(x).replace(",", "").strip())
    except:
        return default

def select_screenshots(urls):
    n = len(urls)
    if n > 8: return urls[:8]
    if n in (6, 7): return urls[:5]
    return urls

def get_today_ph_date():
    try:
        return datetime.now(ZoneInfo("Asia/Manila")).date()
    except Exception:
        return datetime.now(timezone(timedelta(hours=8))).date()

def fetch_json(url, timeout=30):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()

def parse_release_date_any(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        pass
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).date()
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None

def filter_by_release_month_day(items, month, day):
    """Keep items with same month/day and year <= current PH year."""
    matched = []
    ph_year = get_today_ph_date().year
    for it in items:
        dt = parse_release_date_any(it.get("ReleaseDate"))
        if not dt:
            continue
        if dt.month == month and dt.day == day and dt.year <= ph_year:
            matched.append(it)
    return matched

def pick_entry_score_pop_year(entries, ph_year):
    """Sort by SCORE desc, Popularity desc, then prefer current-year matches."""
    def key(e):
        score = safe_float(e.get("SCORE"), -1.0)
        pop   = safe_float(e.get("Popularity"), -1.0)
        dt    = parse_release_date_any(e.get("ReleaseDate"))
        year_match = 1 if (dt and dt.year == ph_year) else 0
        return (score, pop, year_match)
    if not entries:
        return None
    # Sort descending for all three criteria
    return sorted(entries, key=key, reverse=True)[0]

def get_igdb_token(client_id, client_secret):
    data = {"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"}
    r = requests.post(TOKEN_URL, data=data, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]

def igdb_headers(token):
    return {"Client-ID": CLIENT_ID, "Authorization": f"Bearer {token}"}

def query_game_by_slug(token, slug):
    headers = igdb_headers(token)
    variants = slug_variants(slug)
    or_parts = " | ".join([f'slug = "{s}"' for s in variants])
    body = f'fields id,name,slug,screenshots,summary; where {or_parts}; limit 5;'
    time.sleep(0.35)
    r = requests.post(GAMES_URL, data=body, headers=headers, timeout=30)
    r.raise_for_status()
    res = r.json()
    exact = [g for g in res if g.get("slug") == slug]
    if exact:
        return exact[0]
    return res[0] if res else None

def query_screenshots(token, screenshot_ids):
    if not screenshot_ids:
        return []
    headers = igdb_headers(token)
    id_list = ",".join(str(i) for i in screenshot_ids)
    body = f"fields id,image_id,width,height; where id = ({id_list}); limit 50;"
    time.sleep(0.35)
    r = requests.post(SCREENSHOTS_URL, data=body, headers=headers, timeout=30)
    r.raise_for_status()
    rows = r.json() or []
    urls = []
    for row in rows:
        image_id = row.get("image_id")
        if image_id:
            urls.append(f"https://images.igdb.com/igdb/image/upload/t_1080p/{image_id}.jpg")
    return urls

# ========= MAIN =========
def main():
    data = fetch_json(INPUT_LOC)
    if not isinstance(data, list) or not data:
        print("Source JSON is empty or not a list. Exiting.")
        return

    # Month-day input
    if len(sys.argv) >= 2:
        try:
            month, day = map(int, sys.argv[1].split("-"))
            print(f"Using override date: {month:02d}-{day:02d}")
        except ValueError:
            print("Invalid date format. Use MM-DD (e.g., 08-21).")
            return
    else:
        today = get_today_ph_date()
        month, day = today.month, today.day
        print(f"Using today's PH date: {month:02d}-{day:02d}")

    todays = filter_by_release_month_day(data, month, day)
    if not todays:
        print(f"No entries with ReleaseDate matching month/day == {month:02d}-{day:02d}. Exiting.")
        return

    ph_today = get_today_ph_date()
    ph_year  = ph_today.year
    print(f"Matched {len(todays)} entries for {month:02d}-{day:02d} (<= {ph_year}).")

    # === NEW PRIORITY: SCORE -> Popularity -> Year match ===
    best = pick_entry_score_pop_year(todays, ph_year)
    if not best:
        print("No eligible entry found after selection rules. Exiting.")
        return

    slug = (best.get("Slug") or "").strip()
    if not slug:
        print("Chosen entry has no Slug. Exiting.")
        return

    dt = parse_release_date_any(best.get("ReleaseDate"))
    print(f"Chosen Title: {best.get('Title')}")
    print(f"Platform: {best.get('platform')}")
    print(f"Slug: {slug}")
    print(f"Picked by: SCORE→Popularity→YearMatch (ReleaseDate={best.get('ReleaseDate')})")

    # IGDB lookups
    token = get_igdb_token(CLIENT_ID, CLIENT_SECRET)
    time.sleep(0.35)
    game = query_game_by_slug(token, slug)
    if not game:
        print("No IGDB game found for slug variants. Exiting.")
        return

    screenshot_ids = game.get("screenshots") or []
    urls = query_screenshots(token, screenshot_ids) if screenshot_ids else []
    if not urls:
        print("IGDB returned no screenshots for this game.")

    # Outputs
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    matched_on = f"{month:02d}-{day:02d}"

    out_json = os.path.join(OUTPUT_DIR, f"screenshots_{slug}.json")
    payload = {
        "title": game.get("name"),
        "slug": game.get("slug"),
        "igdb_id": game.get("id"),
        "platform": best.get("platform", ""),
        "screenshot_urls": urls,
        "summary": game.get("summary", ""),
        "source_release_date": best.get("ReleaseDate"),
        "picked_by": "SCORE>Popularity>YearMatch",
        "matched_on": matched_on
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Saved JSON to: {out_json}")

    # Limit screenshots per your rule
    urls = select_screenshots(urls)

    # Collage output (fixed width, dynamic height; last row spans full width if needed)
    out_jpg = os.path.join(OUTPUT_DIR, f"collage_{slug}.jpg")
    try:
        make_collage(
            urls,
            out_jpg,
            canvas_w=CANVAS_WIDTH,
            cols=GRID_COLS,
            aspect_ratio=(16, 9),
            mode=GRID_MODE,
            margin=GRID_MARGIN,
            gutter=GRID_GUTTER,
            bg=GRID_BG
        )
        print(f"Saved collage to: {out_jpg}")
    except Exception as e:
        print(f"Failed to create collage: {e}")

if __name__ == "__main__":
    main()
