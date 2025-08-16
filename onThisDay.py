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

# Text overlay
FONT_PATH          = "Axiforma-Black.otf"  # must exist in repo root
BASE_FONT_SIZE_PX  = 88
TITLE_MAX_WIDTH_PX = 1100
STROKE_PX          = 8
TEXT_CENTER_Y      = 774  # y-axis center for the ENTIRE block of three lines
LINE_SPACING_PX    = 10   # spacing between lines (visual gap)

# IGDB creds
CLIENT_ID     = os.getenv("IGDB_CLIENT_ID", "jxnpf283ohcc4z1ou74w2vzkdew9vi")
CLIENT_SECRET = os.getenv("IGDB_CLIENT_SECRET", "q876s02axklhzfu740cznm498arxv2")

TOKEN_URL        = "https://id.twitch.tv/oauth2/token"
GAMES_URL        = "https://api.igdb.com/v4/games"
SCREENSHOTS_URL  = "https://api.igdb.com/v4/screenshots"

# Minimum screenshots required to accept a game
MIN_SCREENSHOTS = 5

# ========= HELPERS =========
def slug_variants(slug: str) -> list:
    variants = [slug]
    if "-switch" in slug: variants.append(slug.replace("-switch", ""))
    if "-ps4" in slug:    variants.append(slug.replace("-ps4", ""))
    if "-ps5" in slug:    variants.append(slug.replace("-ps5", ""))
    if slug.endswith("-nintendo-switch"):
        variants.append(slug.replace("-nintendo-switch", ""))
    manual = {"doom": "doom--1", "survival-kids": "survival-kids--1"}
    if slug in manual: variants.insert(0, manual[slug])
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
    #return datetime(2025, 8, 20).date()
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
    """
    Whole years elapsed (like human anniversary logic).
    Subtract one if today's MM-DD hasn't reached the release MM-DD yet.
    """
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

# ======== IMAGE / COLLAGE HELPERS ========
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

def _fit_keep_aspect(img: Image.Image, target_w: int) -> Image.Image:
    w, h = img.size
    new_w = target_w
    new_h = int(round(h * (new_w / w)))
    return img.resize((new_w, new_h), Image.LANCZOS)

def make_collage_1242(urls, out_path,
                      canvas_w=CANVAS_WIDTH,
                      cols=GRID_COLS,
                      cell_w=CELL_W,
                      cell_h=CELL_H,
                      margin=GRID_MARGIN,
                      gutter=GRID_GUTTER,
                      bg=GRID_BG):
    urls = [u for u in urls if u]
    if not urls:
        raise ValueError("No image URLs provided")

    if len(urls) == 1:
        img = _download_image(urls[0])
        fitted = _fit_keep_aspect(img, canvas_w)
        canvas_h = fitted.height
        canvas = Image.new("RGB", (canvas_w, canvas_h), bg)
        canvas.paste(fitted, (0, 0))
        canvas.save(out_path, "JPEG", quality=90, optimize=True, progressive=True)
        return out_path

    n = len(urls)
    last_wide = (n % cols == 1)
    rows_base = n // cols

    if last_wide:
        base_height  = rows_base * cell_h
        base_gutters = max(rows_base - 1, 0) * gutter
        join_gutter  = gutter if rows_base > 0 else 0
        total_h = 2 * margin + base_height + base_gutters + join_gutter + (2 * cell_h)
    else:
        rows = rows_base
        total_h = 2 * margin + rows * cell_h + max(rows - 1, 0) * gutter

    canvas = Image.new("RGB", (canvas_w, total_h), bg)
    x0 = margin
    y  = margin
    col = 0

    for idx, url in enumerate(urls):
        try:
            img = _download_image(url)
        except Exception:
            img = Image.new("RGB", (cell_w, cell_h), bg)
        is_last = (idx == n - 1)
        if last_wide and is_last:
            target_w = (canvas_w - 2 * margin)
            target_h = cell_h * 2
            tile = _center_crop_cover(img, target_w, target_h)
            canvas.paste(tile, (margin, y))
            break
        else:
            tile = _center_crop_cover(img, cell_w, cell_h)
            x = x0 + col * (cell_w + gutter)
            canvas.paste(tile, (x, y))
            col += 1
            if col >= cols:
                col = 0
                y += cell_h + gutter

    canvas.save(out_path, "JPEG", quality=90, optimize=True, progressive=True)
    return out_path

# ======== TEXT OVERLAY ========
def _load_font(size_px):
    try:
        return ImageFont.truetype(FONT_PATH, size_px)
    except Exception:
        # Fallback if font file isn't available; keeps the pipeline alive
        return ImageFont.load_default()

def _text_size(draw, text, font, stroke):
    # textbbox returns (left, top, right, bottom); include stroke in measurement
    bbox = draw.textbbox((0,0), text, font=font, stroke_width=stroke, anchor="la")
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    return w, h

def _fit_title_font(draw, title, base_size, max_width, stroke):
    size = base_size
    while size > 8:  # hard floor to avoid zero/negative sizes
        f = _load_font(size)
        w, _ = _text_size(draw, title, f, stroke)
        if w <= max_width:
            return f, size
        size -= 2
    return _load_font(8), 8

def _map_platform(raw):
    if not raw:
        return ""
    raw = str(raw).strip()
    if raw == "Nintendo Switch":
        return "Switch"
    if raw == "Nintendo Switch 2":
        return "Switch 2"
    return raw

def add_gradient_background(img, center_y, height=200, fade=200):
    """
    Add a horizontal black band centered at center_y with transparent gradients
    above and below. Works even if the band extends beyond the image bounds.
    """
    img = img.convert("RGBA")
    band_h = height + 2*fade

    # Build vertical alpha gradient: 0..255 (fade in), 255 (solid), 255..0 (fade out)
    alpha_col = Image.new("L", (1, band_h))
    for y in range(band_h):
        if y < fade:
            a = int(255 * (y / max(1, fade)))                      # fade in
        elif y < fade + height:
            a = 255                                                # solid
        else:
            a = int(255 * (1 - (y - fade - height) / max(1, fade)))  # fade out
        alpha_col.putpixel((0, y), a)
    alpha = alpha_col.resize((img.width, band_h))

    # Full-width black band with gradient alpha
    black_band = Image.new("RGBA", (img.width, band_h), (0, 0, 0, 255))
    black_band.putalpha(alpha)

    # Target placement
    band_top = center_y - (height // 2 + fade)
    band_bottom = band_top + band_h

    # Clamp to image bounds (crop the band if it overflows)
    top = max(0, band_top)
    bottom = min(img.height, band_bottom)
    if bottom <= top:
        return img  # nothing to draw

    crop_top = top - band_top
    crop_bottom = crop_top + (bottom - top)
    band_cropped = black_band.crop((0, crop_top, img.width, crop_bottom))

    # Composite onto a same-size overlay, then onto img
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay.paste(band_cropped, (0, top), band_cropped)  # ✅ 2-item box is fine when pasting an image
    img = Image.alpha_composite(img, overlay)
    return img

def add_text_overlay(image_path, title, platform_raw, source_release_date):
    """
    Draws three centered lines on the collage.
    Center of the WHOLE block is at y = TEXT_CENTER_Y.
    """
    img = Image.open(image_path).convert("RGBA")
    img = add_gradient_background(img, center_y=TEXT_CENTER_Y, height=200, fade=200)
    draw = ImageDraw.Draw(img)

    # Compute <n>
    rd = parse_release_date_any(source_release_date)
    n = years_elapsed_until_today_ph(rd)
    # Lines
    if n == 0:
        line1 = "Today..."
    else:
        year_word = "year" if n == 1 else "years"
        line1 = f"{n} {year_word} ago today..."
    line2 = title or ""
    platform = _map_platform(platform_raw)
    line3 = f"released on the {platform}" if platform else "released"

    # Fonts
    font_line1 = _load_font(BASE_FONT_SIZE_PX)
    font_line3 = _load_font(BASE_FONT_SIZE_PX)
    # Title font may shrink to fit width ≤ TITLE_MAX_WIDTH_PX
    font_line2, title_size = _fit_title_font(draw, line2, BASE_FONT_SIZE_PX, TITLE_MAX_WIDTH_PX, STROKE_PX)

    # Measure all lines (including stroke)
    w1, h1 = _text_size(draw, line1, font_line1, STROKE_PX)
    w2, h2 = _text_size(draw, line2, font_line2, STROKE_PX)
    w3, h3 = _text_size(draw, line3, font_line3, STROKE_PX)

    total_h = h1 + LINE_SPACING_PX + h2 + LINE_SPACING_PX + h3
    # Center of the block should be at TEXT_CENTER_Y
    top_y = int(round(TEXT_CENTER_Y - total_h / 2))

    # Horizontal center
    center_x = img.width // 2

    # Colors
    title_color = (255, 185, 18)  # #ffb912
    other_color = (255, 255, 255)
    stroke_color = (0, 0, 0)

    # Draw lines centered
    # Line 1
    draw.text(
        (center_x, top_y),
        line1,
        font=font_line1,
        fill=other_color,
        stroke_width=STROKE_PX,
        stroke_fill=stroke_color,
        anchor="ma"  # middle baseline horizontally centered
    )
    # Line 2 (title)
    y2 = top_y + h1 + LINE_SPACING_PX
    draw.text(
        (center_x, y2),
        line2,
        font=font_line2,
        fill=title_color,
        stroke_width=STROKE_PX,
        stroke_fill=stroke_color,
        anchor="ma"
    )
    # Line 3
    y3 = y2 + h2 + LINE_SPACING_PX
    draw.text(
        (center_x, y3),
        line3,
        font=font_line3,
        fill=other_color,
        stroke_width=STROKE_PX,
        stroke_fill=stroke_color,
        anchor="ma"
    )

    img = img.convert("RGB")
    img.save(image_path, "JPEG", quality=90, optimize=True, progressive=True)
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
        platform = best.get("platform")
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
        # cap to 5 for the collage layout
        make_collage_1242(urls[:5], out_jpg)
        print(f"Saved collage to: {out_jpg}")
    except Exception as e:
        print(f"Failed to create collage: {e}")
        return

    # ----- Add text overlay on top of the collage -----
    try:
        add_text_overlay(
            out_jpg,
            title=payload["title"],
            platform_raw=payload["platform"],
            source_release_date=payload["source_release_date"]
        )
        print("Applied text overlay.")
    except Exception as e:
        print(f"Failed to add text overlay: {e}")

if __name__ == "__main__":
    main()
