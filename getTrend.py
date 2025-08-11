import json
import requests
import os
import sys
from datetime import datetime, timedelta, timezone

# ========= HELPERS =========
def now_utc():
    # Store as naive UTC for simple arithmetic, but consistently derived from UTC
    return datetime.now(timezone.utc).replace(tzinfo=None)

def clean_slug(slug: str, platform: str) -> str:
    if platform == "switch":
        return slug.replace("-switch-2", "").replace("-switch", "")
    elif platform == "ps":
        return slug.replace("-ps4", "").replace("-ps5", "")
    return slug  # default fallback

def safe_score(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return -1  # fallback for missing or invalid score

def get_base_price(game):
    try:
        value = game.get("Price", "").replace(",", "").strip()
        return float(value) if value else 0
    except ValueError:
        return 0

def parse_date_any(value: str) -> datetime:
    if not value:
        return datetime.min
    v = value.strip()
    # 1) Try simple date first (fast path)
    try:
        return datetime.strptime(v, "%Y-%m-%d")
    except Exception:
        pass
    # 2) Try ISO 8601 (handle trailing Z)
    try:
        iso = v.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        # Normalize offset-aware to naive UTC for consistent sorting
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        pass
    # 3) Try a few common fallbacks
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y/%m/%d",
    ):
        try:
            dt = datetime.strptime(v, fmt)
            return dt
        except Exception:
            continue
    # Last resort
    return datetime.min

# ========= CLI ARG =========
if len(sys.argv) != 2:
    print("Usage: python getTrend.py <platform>")
    sys.exit(1)

PLATFORM = sys.argv[1]
CONFIG_PATH = f"platforms/{PLATFORM}/config.json"

if not os.path.exists(CONFIG_PATH):
    print(f"❌ Config file not found: {CONFIG_PATH}")
    sys.exit(1)

with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = json.load(f)

# ========= CONFIG =========
INPUT_URL = config["input_url"]
OUTPUT_FILE = config["output_file"]
EXPORTED_TRACKER = config["exported_tracker"]
FORCE_INCLUDE_FILE = config["force_file"]
PRICE_FIELD_TO_EXCHANGE = config["fields_to_convert"]
USE_ARGENTINA_LOGIC = config.get("argentina_logic", False)

SORT_MODE = config.get("sort_mode", "popularity")
USE_EXPORTED_TRACKER = config.get("use_exported_tracker", True)

# ========= CONSTANTS =========
EXPIRY_DAYS = 7                    # fixed window length
MAX_GAMES = 50
CANDIDATE_POOL_LIMIT = 300

# ========= LOAD SOURCE =========
response = requests.get(INPUT_URL)
response.raise_for_status()
games = response.json()

# Filter out unwanted ESRB ratings
games = [g for g in games if g.get("ESRBRating") not in ["Bundle", "Individual"]]

# ========= SORTING =========
if SORT_MODE == "sale_started":
    games.sort(key=lambda g: (
        parse_date_any(g.get("SaleStarted", "")),  # Newer = better
        safe_score(g.get("SCORE")),                # Higher score = better
        get_base_price(g)                          # Higher base price = better
    ), reverse=True)
elif SORT_MODE == "release_date":
    games.sort(key=lambda g: (
        parse_date_any(g.get("ReleaseDate", "")),
        safe_score(g.get("SCORE")),
        get_base_price(g)
    ), reverse=True)
else:  # Default: popularity
    games.sort(key=lambda g: int(g.get("Popularity") or 0), reverse=True)

# ========= TRACKER (FIXED 7-DAY WINDOW) =========
exported_slugs = set()
period_start = None

if USE_EXPORTED_TRACKER and os.path.exists(EXPORTED_TRACKER):
    with open(EXPORTED_TRACKER, 'r', encoding='utf-8') as f:
        tracker_data = json.load(f)
        exported_slugs = set(tracker_data.get("slugs", []))
        # Back-compat: accept "period_start" or legacy "timestamp"
        ts = tracker_data.get("period_start") or tracker_data.get("timestamp")
        try:
            period_start = datetime.fromisoformat(ts) if ts else None
        except Exception:
            period_start = None

# First run or malformed -> start a new period
if period_start is None:
    period_start = now_utc()

# Expire if the fixed window elapsed
if (now_utc() - period_start) >= timedelta(days=EXPIRY_DAYS):
    print("🕒 7‑day period expired. Clearing tracker...")
    exported_slugs = set()
    period_start = now_utc()  # start a new 7-day window

# ========= FORCE INCLUDE =========
force_include_slugs = set()
if os.path.exists(FORCE_INCLUDE_FILE):
    with open(FORCE_INCLUDE_FILE, 'r', encoding='utf-8') as f:
        try:
            force_include_slugs = set(json.load(f))
        except json.JSONDecodeError:
            print("⚠️ force_include.json is not valid JSON. Skipping force inclusion.")
else:
    print("ℹ️ force_include.json not found. Skipping force inclusion.")

force_included_games = []
seen_force_slugs = set()
matched_slugs = set()

for game in games:
    slug = clean_slug(game.get("Slug", ""), PLATFORM)
    if slug in force_include_slugs and slug not in seen_force_slugs:
        game["slug_clean"] = slug
        force_included_games.append(game)
        seen_force_slugs.add(slug)
        matched_slugs.add(slug)

# Warn about unmatched forced slugs
unmatched_slugs = force_include_slugs - matched_slugs
for slug in unmatched_slugs:
    print(f"⚠️ Forced slug not found in source data: {slug}")

# Save updated force include (remove matched)
try:
    with open(FORCE_INCLUDE_FILE, 'w', encoding='utf-8') as f:
        json.dump(sorted(list(unmatched_slugs)), f, indent=2)
    if matched_slugs:
        print(f"📌 Force-included {len(matched_slugs)} games and removed them from {FORCE_INCLUDE_FILE}")
except Exception as e:
    print(f"⚠️ Could not update {FORCE_INCLUDE_FILE}: {e}")

# ========= BUILD CANDIDATES =========
new_candidates = force_included_games.copy()

for game in games[:CANDIDATE_POOL_LIMIT]:
    slug = clean_slug(game.get("Slug", ""), PLATFORM)
    if slug in seen_force_slugs or slug in exported_slugs:
        continue
    game["slug_clean"] = slug
    new_candidates.append(game)
    if len(new_candidates) >= MAX_GAMES:
        break

# ========= EXCHANGE RATES =========
exchange_url = "https://cdn.jsdelivr.net/gh/ismartcoding/currency-api@main/latest/data.json"
exchange_data = requests.get(exchange_url).json()
datam = exchange_data["quotes"]
php_base = float(datam['PHP'])
# e.g., "usd" -> value to multiply with amount in USD to get PHP
conversion_rates = {k.lower() + "Exchange": php_base / float(v) for k, v in datam.items()}

# ========= BUILD EXPORT =========
export_data = []

for game in new_candidates:
    lowest_php_price = None
    cheapest_region = None

    for field, rate_key in PRICE_FIELD_TO_EXCHANGE.items():
        raw = str(game.get(field, "") or "")
        value = raw.replace(",", "").strip()
        if not value:
            continue

        try:
            price = float(value)

            if field == 'ArgentinaPrice' and USE_ARGENTINA_LOGIC:
                # Convert ARS to PHP
                ars_price_php = price * conversion_rates['arsExchange']
                # Regionality tax heuristic from your original
                regionality_tax = ars_price_php * 1.21 * (
                    (1500 - (12100 * conversion_rates['arsExchange'])) / (12100 * conversion_rates['arsExchange'])
                )
                argentina_tax = round((ars_price_php * 1.21) - ars_price_php)
                php_price = ars_price_php + regionality_tax + argentina_tax
            else:
                php_price = price * conversion_rates[rate_key]

            if lowest_php_price is None or php_price < lowest_php_price:
                lowest_php_price = php_price
                cheapest_region = field
        except ValueError:
            continue

    if lowest_php_price is not None:
        entry = {
            "title": game.get("Title", "Unknown"),
            "slug": game.get("slug_clean", ""),
            "release_date": game.get("ReleaseDate", ""),
            "sale_ends": game.get("SaleEnds", ""),
            "popularity": int(game.get("Popularity") or 0),
            "cheapest_region": cheapest_region,
            "lowest_php_price": int(round(lowest_php_price))
        }

        # PS/Switch specific fields passthrough
        if PLATFORM == "ps":
            entry["IsPS4"] = game.get("IsPS4", 0)
            entry["IsPS5"] = game.get("IsPS5", 0)
        elif PLATFORM == "switch":
            entry["platform"] = game.get("platform", "")

        export_data.append(entry)
        # Track as exported for this fixed window
        exported_slugs.add(game.get("slug_clean", ""))

# ========= SAVE FILES =========
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
os.makedirs(os.path.dirname(EXPORTED_TRACKER), exist_ok=True)

with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    json.dump(export_data, f, indent=2, ensure_ascii=False)

print(f"✅ Exported {len(export_data)} games to {OUTPUT_FILE}")

if USE_EXPORTED_TRACKER:
    with open(EXPORTED_TRACKER, 'w', encoding='utf-8') as f:
        json.dump({
            "period_start": period_start.isoformat(),   # <-- fixed window anchor
            "slugs": sorted(list(exported_slugs)),
            "last_run": now_utc().isoformat()           # optional/informational
        }, f, indent=2)
    print(f"📝 Tracker updated: {EXPORTED_TRACKER}")
else:
    print("ℹ️ Export tracker disabled by config.")
