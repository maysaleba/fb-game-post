import os
import sys
import json
import time
import math
import io
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont

# ========= CONFIG =========
INPUT_LOC   = "https://raw.githubusercontent.com/maysaleba/maysaleba.github.io/main/src/csvjson.json"
OUTPUT_DIR  = "output"

# Canvas/grid (fixed width; dynamic height)
CANVAS_WIDTH = 1242
GRID_COLS    = 2
CELL_W       = 621
CELL_H       = 387
GRID_MARGIN  = 0
GRID_GUTTER  = 0
GRID_BG      = (16, 16, 16)

# ========= TEXT OVERLAY CONFIG (match collage_bot_slug.py) =========
FONT_PATH         = "Axiforma-Black.otf"
BASE_FONT_SIZE_PX = 90
TEXT_CENTER_Y     = 1320
LINE_SPACING_PX   = 10
TITLE_COLOR       = (255, 186, 32)  # #ffba20
OTHER_COLOR       = (255, 255, 255)
MAX_TEXT_WIDTH_PX = 1126
STROKE_PX         = 0
STROKE_COLOR      = (0, 0, 0)

LINE1_MAX_WIDTH_PX = MAX_TEXT_WIDTH_PX
LINE2_MAX_WIDTH_PX = MAX_TEXT_WIDTH_PX
LINE3_MAX_WIDTH_PX = MAX_TEXT_WIDTH_PX
MIN_FONT_SIZE_PX   = 18

# ========= GRADIENT BAND (match collage_bot_slug.py) =========
BAND_HEIGHT  = 1000
MAX_OPACITY  = 0.9
SOLID_HEIGHT = 200
EASE         = "linear"  # "linear", "ease-in", "ease-out"

# IGDB creds
CLIENT_ID     = os.getenv("IGDB_CLIENT_ID", "jxnpf283ohcc4z1ou74w2vzkdew9vi")
CLIENT_SECRET = os.getenv("IGDB_CLIENT_SECRET", "q876s02axklhzfu740cznm498arxv2")

TOKEN_URL        = "https://id.twitch.tv/oauth2/token"
GAMES_URL        = "https://api.igdb.com/v4/games"
SCREENSHOTS_URL  = "https://api.igdb.com/v4/screenshots"

MIN_SCREENSHOTS = 5

# ========= HELPERS =========
def add_logo_overlay(image_path, logo_path="msb_logo.png", pos=(10,10)):
    try:
        img = Image.open(image_path).convert("RGBA")
        logo = Image.open(logo_path).convert("RGBA")
        img.paste(logo, pos, logo)
        img = img.convert("RGB")
        img.save(image_path, "JPEG", quality=90, optimize=True, progressive=True)
        return image_path
    except Exception as e:
        print(f"⚠️ Failed to overlay logo: {e}")
        return image_path

def slug_variants(slug: str) -> list:
    variants = [slug]
    if "-switch" in slug: variants.append(slug.replace("-switch", ""))
    if "-ps4" in slug:    variants.append(slug.replace("-ps4", ""))
    if "-ps5" in slug:    variants.append(slug.replace("-ps5", ""))
    if slug.endswith("-nintendo-switch"):
        variants.append(slug.replace("-nintendo-switch", ""))

    manual = {"doom": "doom--1", "survival-kids": "survival-kids--1", "blasphemous-2": "blasphemous-ii"}
    for v in list(variants):
        if v in manual:
            variants.insert(0, manual[v])

    seen, unique = set(), []
    for s in variants:
        if s not in seen:
            seen.add(s); unique.append(s)
    return unique

def safe_float(x, default=0.0):
    try:
        if x is None: return default
        if isinstance(x,(int,float)): return float(x)
        return float(str(x).replace(",","").strip())
    except: return default

def get_today_ph_date():
    try: return datetime.now(ZoneInfo("Asia/Manila")).date()
    except Exception: return datetime.now(timezone(timedelta(hours=8))).date()

def fetch_json(url, timeout=30):
    r = requests.get(url, timeout=timeout); r.raise_for_status()
    return r.json()

def parse_release_date_any(s: str):
    s = (s or "").strip()
    if not s: return None
    try: return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError: pass
    try:
        if s.endswith("Z"): s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).date()
    except ValueError: pass
    for fmt in ("%m/%d/%Y", "%d %B %Y", "%B %d, %Y"):
        try: return datetime.strptime(s, fmt).date()
        except ValueError: continue
    return None

def years_elapsed_until_today_ph(release_date):
    if release_date is None:
        return None
    today = get_today_ph_date()
    years = today.year - release_date.year
    if (today.month, today.day) < (release_date.month, release_date.day):
        years -= 1
    return max(0, years)

def filter_by_release_month_day(items, month, day):
    matched = []
    ph_year = get_today_ph_date().year
    for it in items:
        dt = parse_release_date_any(it.get("ReleaseDate"))
        if not dt: continue
        if dt.month == month and dt.day == day and dt.year <= ph_year:
            matched.append(it)
    return matched

def pick_entries_sorted_by_score_pop_year(entries, ph_year):
    def key(e):
        pop   = safe_float(e.get("Popularity"), -1.0)
        score = safe_float(e.get("SCORE"), -1.0)
        dt    = parse_release_date_any(e.get("ReleaseDate"))
        year_match = 1 if (dt and dt.year == ph_year) else 0
        return (pop, score, year_match)
    return sorted(entries, key=key, reverse=True)

def get_igdb_token(client_id, client_secret):
    data = {"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"}
    r = requests.post(TOKEN_URL, data=data, timeout=30); r.raise_for_status()
    return r.json()["access_token"]

def igdb_headers(token):
    return {"Client-ID": CLIENT_ID, "Authorization": f"Bearer {token}"}

def query_game_by_slug(token, slug, debug=True):
    headers = igdb_headers(token)
    variants = slug_variants(slug)
    or_parts = " | ".join([f'slug = "{s}"' for s in variants])
    body = f'fields id,name,slug,screenshots,summary; where {or_parts}; limit 5;'
    time.sleep(0.35)
    r = requests.post(GAMES_URL, data=body, headers=headers, timeout=30)
    r.raise_for_status()
    res = r.json()

    if debug:
        if not res:
            print(f"[IGDB] No results for slug '{slug}' (variants: {variants})")
        else:
            print(f"[IGDB] Results for slug '{slug}' (variants: {variants}):")
            for g in res:
                print(f"  - {g.get('name')} (slug={g.get('slug')}, id={g.get('id')})")

    exact = [g for g in res if g.get("slug") == slug]
    if exact:
        return exact[0]
    variant_match = [g for g in res if g.get("slug") in variants]
    if variant_match:
        return variant_match[0]
    return None

def query_screenshots(token, screenshot_ids):
    if not screenshot_ids: return []
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

# ======== IMAGE HELPERS ========
def _download_image(url, timeout=30):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")

def _center_crop_cover(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    src_w, src_h = img.size
    src_aspect = src_w / src_h
    tgt_aspect = target_w / target_h
    if src_aspect > tgt_aspect:
        new_h = target_h
        new_w = int(round(new_h * src_aspect))
    else:
        new_w = target_w
        new_h = int(round(new_w / src_aspect))
    img_resized = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    return img_resized.crop((left, top, left + target_w, top + target_h))

# ======== COLLAGE LOGIC (no randomization) ========
def make_5tile_collage(urls, out_path):
    """
    2x2 on top + 1 wide on bottom (total canvas height = 4 * CELL_H).
    Uses first 5 URLs in order (no randomization).
    """
    urls = [u for u in urls if u]
    if len(urls) < 5:
        raise ValueError("Need at least 5 images for 5-tile collage")

    urls = urls[:5]

    canvas = Image.new("RGB", (CANVAS_WIDTH, 4 * CELL_H), GRID_BG)

    # top 2x2
    idx = 0
    y = GRID_MARGIN
    for r in range(2):
        for c in range(GRID_COLS):
            try:
                img = _download_image(urls[idx])
            except Exception:
                img = Image.new("RGB", (CELL_W, CELL_H), GRID_BG)
            tile = _center_crop_cover(img, CELL_W, CELL_H)
            x = GRID_MARGIN + c * (CELL_W + GRID_GUTTER)
            canvas.paste(tile, (x, y))
            idx += 1
        y += CELL_H + GRID_GUTTER

    # bottom wide (2 * CELL_H tall)
    try:
        last_img = _download_image(urls[4])
    except Exception:
        last_img = Image.new("RGB", (CANVAS_WIDTH, CELL_H * 2), GRID_BG)
    wide_tile = _center_crop_cover(last_img, CANVAS_WIDTH, CELL_H * 2)
    canvas.paste(wide_tile, (GRID_MARGIN, y))

    canvas.save(out_path, "JPEG", quality=90, optimize=True, progressive=True)
    return out_path

def make_2x4_collage(urls, out_path):
    """
    2 columns × 4 rows grid (8 tiles total), canvas height = 4 * CELL_H.
    Uses URLs in order; if fewer than 8, cycles from the beginning.
    """
    urls = [u for u in urls if u]
    if len(urls) < 6:
        raise ValueError("Need at least 6 images for 2x4 grid")

    if len(urls) >= 8:
        urls = urls[:8]
    else:
        # cycle through the list until we have 8
        needed = 8
        cycled = []
        idx = 0
        while len(cycled) < needed:
            cycled.append(urls[idx % len(urls)])
            idx += 1
        urls = cycled

    canvas = Image.new("RGB", (CANVAS_WIDTH, 4 * CELL_H), GRID_BG)

    idx = 0
    y = GRID_MARGIN
    for r in range(4):
        x = GRID_MARGIN
        for c in range(GRID_COLS):
            try:
                img = _download_image(urls[idx])
            except Exception:
                img = Image.new("RGB", (CELL_W, CELL_H), GRID_BG)
            tile = _center_crop_cover(img, CELL_W, CELL_H)
            canvas.paste(tile, (x, y))
            x += CELL_W + GRID_GUTTER
            idx += 1
        y += CELL_H + GRID_GUTTER

    canvas.save(out_path, "JPEG", quality=90, optimize=True, progressive=True)
    return out_path


# ======== TEXT OVERLAY / GRADIENT (from collage_bot_slug.py) ========
def _load_font(size_px):
    try:
        return ImageFont.truetype(FONT_PATH, size_px)
    except Exception:
        return ImageFont.load_default()

def _text_size(draw, text, font, stroke):
    bbox = draw.textbbox((0,0), text, font=font, stroke_width=stroke, anchor="la")
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    return w, h

def _fit_font_to_width(draw, text, base_size, max_width, stroke, min_px=MIN_FONT_SIZE_PX, step=2):
    if not text:
        return _load_font(base_size), base_size
    size = base_size
    while size > min_px:
        f = _load_font(size)
        w, _ = _text_size(draw, text, f, stroke)
        if w <= max_width:
            return f, size
        size -= step
    return _load_font(min_px), min_px

def _map_platform(raw):
    if not raw:
        return ""
    raw = str(raw).strip()
    if raw == "Nintendo Switch":
        return "Switch"
    if raw == "Nintendo Switch 2":
        return "Switch 2"
    return raw

def _format_percent_off(raw):
    s = (str(raw or "").strip()).replace("%","")
    if not s:
        return ""
    try:
        v = float(s)
        if v.is_integer():
            return f"{int(v)}%"
        return f"{v:.0f}%"
    except:
        digits = "".join(ch for ch in s if ch.isdigit())
        return f"{digits}%" if digits else ""

def add_gradient_background(
    img,
    center_y,                 # kept for signature compatibility (ignored)
    height=SOLID_HEIGHT,      # maps to SOLID_HEIGHT
    fade=None,                # ignored (we use BAND_HEIGHT - SOLID_HEIGHT)
    opacity=MAX_OPACITY
):
    """
    Bottom black gradient (same as collage_bot_slug.py):
      - Total band height = BAND_HEIGHT (clamped to image height)
      - Bottom SOLID_HEIGHT px fully opaque (scaled by MAX_OPACITY)
      - Above within the band fades 0 → MAX_OPACITY via EASE
    Returns (img_with_band, solid_top, solid_bottom).
    """
    img = img.convert("RGBA")
    band_h = max(1, min(BAND_HEIGHT, img.height))
    fade_h = max(0, band_h - SOLID_HEIGHT)

    alpha_col = Image.new("L", (1, band_h))

    def ease_ratio(y, denom, mode):
        if denom <= 0:
            return 1.0
        r = min(1.0, y / denom)
        if mode == "ease-in":  return r ** 2
        if mode == "ease-out": return 1 - (1 - r) ** 2
        return r  # linear

    for y in range(band_h):
        if y >= band_h - SOLID_HEIGHT and SOLID_HEIGHT > 0:
            a = int(MAX_OPACITY * 255)
        else:
            denom = (fade_h - 1) if fade_h > 1 else 1
            ratio = ease_ratio(y, denom, EASE)
            a = int(round(MAX_OPACITY * 255 * ratio))
        alpha_col.putpixel((0, y), a)

    alpha = alpha_col.resize((img.width, band_h))
    black = Image.new("RGBA", (img.width, band_h), (0,0,0,255))
    black.putalpha(alpha)

    top = img.height - band_h
    overlay = Image.new("RGBA", img.size, (0,0,0,0))
    overlay.paste(black, (0, top), black)
    out = Image.alpha_composite(img, overlay)

    # Solid region (bottom SOLID_HEIGHT px)
    solid_top = max(0, img.height - SOLID_HEIGHT)
    solid_bottom = img.height
    return out, solid_top, solid_bottom

def add_text_overlay(image_path, title, platform_raw, percent_off, source_release_date):
    """
    3-line format:
      If exact release date == today (including year):
        1) <title>                  (gold)
        2) "is releasing today on <platform>!"
        3) "now <percent_off> OFF!" (if discount present)

      If month/day matches but year differs:
        1) <title>                  (gold)
        2) "turns n years old today on <platform>!"
        3) "now <percent_off> OFF!" (if discount present)
    """
    base = Image.open(image_path).convert("RGBA")
    base, _, _ = add_gradient_background(base, center_y=TEXT_CENTER_Y)
    draw = ImageDraw.Draw(base)

    # --- data prep ---
    rd = parse_release_date_any(source_release_date)
    today = get_today_ph_date()
    releasing_today = (rd is not None and rd == today)
    years = years_elapsed_until_today_ph(rd)
    platform = _map_platform(platform_raw)
    po = _format_percent_off(percent_off)

    # --- lines per new spec ---
    line1 = title or ""  # highlighted (gold)

    if releasing_today:
        core = f"is releasing today"
    else:
        n = 0 if years is None else years
        year_word = "year" if n == 1 else "years"
        core = f"turns {n} {year_word} old today"

    line2 = f"{core} on {platform}" if platform else f"{core}"
    line3 = f"it is now on sale for {po} OFF!" if po else ""

    # --- fit fonts to width ---
    font1, _ = _fit_font_to_width(draw, line1, BASE_FONT_SIZE_PX, LINE1_MAX_WIDTH_PX, STROKE_PX)
    font2, _ = _fit_font_to_width(draw, line2, BASE_FONT_SIZE_PX, LINE2_MAX_WIDTH_PX, STROKE_PX)
    font3, _ = _fit_font_to_width(draw, line3, BASE_FONT_SIZE_PX, LINE3_MAX_WIDTH_PX, STROKE_PX)

    def wh(txt, fnt):
        if not txt:
            return (0, 0)
        bbox = draw.textbbox((0, 0), txt, font=fnt, stroke_width=STROKE_PX, anchor="la")
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])

    w1, h1 = wh(line1, font1)
    w2, h2 = wh(line2, font2)
    w3, h3 = wh(line3, font3)

    lines_present = [h for h in (h1, h2, h3) if h > 0]
    total_h = sum(lines_present) + LINE_SPACING_PX * (len(lines_present) - 1 if lines_present else 0)

    # --- center vertically ---
    cx = base.width // 2
    top_y = int(round(TEXT_CENTER_Y - total_h / 2))

    # --- draw (title gold; others white) ---
    y = top_y
    if line1:
        draw.text((cx, y), line1, font=font1, fill=TITLE_COLOR, anchor="ma")
        y += h1 + LINE_SPACING_PX
    if line2:
        draw.text((cx, y), line2, font=font2, fill=OTHER_COLOR, anchor="ma")
        y += h2 + LINE_SPACING_PX
    if line3:
        draw.text((cx, y), line3, font=font3, fill=OTHER_COLOR, anchor="ma")

    base.convert("RGB").save(image_path, "JPEG", quality=90, optimize=True, progressive=True)
    return image_path


# ========= MAIN =========
def main():
    data = fetch_json(INPUT_LOC)
    if not isinstance(data, list) or not data:
        print("Source JSON is empty or not a list. Exiting.")
        return
    
    data = [item for item in data if not str(item.get("ESRBRating", "")).strip()]
    if not data:
        print("No entries with empty ESRBRating. Exiting.")
        return

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
        print(f"No entries with ReleaseDate matching {month:02d}-{day:02d}. Exiting.")
        return

    ph_year = get_today_ph_date().year
    candidates = pick_entries_sorted_by_score_pop_year(todays, ph_year)
    print(f"Matched {len(candidates)} candidate(s) for {month:02d}-{day:02d}.")

    token = get_igdb_token(CLIENT_ID, CLIENT_SECRET); time.sleep(0.35)

    chosen = None
    for idx, best in enumerate(candidates, start=1):
        slug = (best.get("Slug") or "").strip()
        title = best.get("Title")
        if not slug:
            print(f"[{idx}/{len(candidates)}] Skipping '{title}' (no slug).")
            continue

        print(f"[{idx}/{len(candidates)}] Trying: {title} | Slug={slug}")

        game = query_game_by_slug(token, slug, debug=True)
        if not game:
            print(f"[{idx}/{len(candidates)}] No IGDB match. Next…")
            continue

        screenshot_ids = game.get("screenshots") or []
        urls = query_screenshots(token, screenshot_ids) if screenshot_ids else []
        if len(urls) < MIN_SCREENSHOTS:
            print(f"[{idx}/{len(candidates)}] Only {len(urls)} screenshot(s) (<{MIN_SCREENSHOTS}). Skipping.")
            continue

        chosen = {"best": best, "game": game, "slug": slug, "urls": urls}
        print(f"[{idx}/{len(candidates)}] ✅ Selected: {title} ({len(urls)} screenshots)")
        break

    if not chosen:
        print(f"No IGDB game with ≥{MIN_SCREENSHOTS} screenshots found. Exiting.")
        return

    best = chosen["best"]
    game = chosen["game"]
    slug = chosen["slug"]
    urls = chosen["urls"]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    matched_on = f"{month:02d}-{day:02d}"

    out_json = os.path.join(OUTPUT_DIR, f"screenshots_{slug}.json")
    payload = {
        "title": game.get("name"),
        "slug": game.get("slug"),
        "igdb_id": game.get("id"),
        "platform": best.get("platform", ""),
        "percent_off": best.get("PercentOff", ""),
        "screenshot_urls": urls,
        "summary": game.get("summary", ""),
        "source_release_date": best.get("ReleaseDate"),
        "picked_by": "SCORE>Popularity>YearMatch (min screenshots rule)",
        "matched_on": matched_on
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Saved JSON to: {out_json}")

    out_jpg = os.path.join(OUTPUT_DIR, f"collage_{slug}.jpg")
    try:
        if len(urls) >= 6:
            make_2x4_collage(urls, out_jpg)
        elif len(urls) == 5:
            make_5tile_collage(urls, out_jpg)
        else:
            print(f"Skipping {slug}, not enough screenshots ({len(urls)}).")
            return
        print(f"Saved collage to: {out_jpg}")
    except Exception as e:
        print(f"Failed to create collage: {e}")
        return

    # ----- Add text overlay -----
    try:
        add_text_overlay(
            out_jpg,
            title=payload["title"],
            platform_raw=payload["platform"],
            percent_off=payload["percent_off"],
            source_release_date=payload["source_release_date"]
        )
        print("Applied text overlay.")
    except Exception as e:
        print(f"Failed to add text overlay: {e}")

    try:
        add_logo_overlay(out_jpg, "msb_logo.png", (10,10))
        print("Applied logo overlay.")
    except Exception as e:
        print(f"Failed to add logo overlay: {e}")

if __name__ == "__main__":
    main()
