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

# Gradient band geometry (solid center + fades)
BAND_SOLID_HEIGHT = 200   # readable solid band height
BAND_FADE          = 200  # fade above and below the solid band
BAND_INNER_PADDING = 8    # small top/bottom padding inside the solid area


# Allow text to extend this many pixels outside the solid band
BAND_LEEWAY = 60   # try 60–80px; tweak until it looks good
BAND_OPACITY       = 0.9 # <--- NEW: 0.0 (transparent) → 1.0 (fully opaque)


# Text overlay
FONT_PATH          = "Axiforma-Black.otf"  # must exist in repo root
BASE_FONT_SIZE_PX  = 88
TITLE_MAX_WIDTH_PX = 1100
STROKE_PX          = 0
TEXT_CENTER_Y      = 774  # y-axis center for the ENTIRE block of three lines
LINE_SPACING_PX    = 10   # spacing between lines (visual gap)

# Per-line max widths + minimum font size (for per-line auto-fit)
LINE1_MAX_WIDTH_PX = 1100
LINE2_MAX_WIDTH_PX = TITLE_MAX_WIDTH_PX
LINE3_MAX_WIDTH_PX = 1100
MIN_FONT_SIZE_PX   = 18

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

    manual = {"doom": "doom--1", "survival-kids": "survival-kids--1", "blasphemous-2": "blasphemous-ii"}

    # 🔑 Check all generated variants against manual overrides
    for v in list(variants):  
        if v in manual:
            variants.insert(0, manual[v])  # add override at the front

    # Deduplicate while preserving order
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
    # return datetime(2025, 8, 20).date()  # <- handy for testing
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

# ======== TEXT OVERLAY / TYPOGRAPHY ========
def _load_font(size_px):
    try:
        return ImageFont.truetype(FONT_PATH, size_px)
    except Exception:
        return ImageFont.load_default()

def _text_size(draw, text, font, stroke):
    # textbbox returns (left, top, right, bottom); include stroke in measurement
    bbox = draw.textbbox((0,0), text, font=font, stroke_width=stroke, anchor="la")
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    return w, h

def _fit_font_to_width(draw, text, base_size, max_width, stroke, min_px=MIN_FONT_SIZE_PX, step=2):
    """
    Returns (font, size_px) such that 'text' fits within 'max_width' including stroke.
    If text is empty, returns base font immediately.
    """
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
        # if it's something like "70% OFF", normalize to "70%"
        digits = "".join(ch for ch in s if ch.isdigit())
        return f"{digits}%" if digits else ""

def add_gradient_background(
    img,
    center_y,
    height=BAND_SOLID_HEIGHT,
    fade=BAND_FADE,
    opacity=BAND_OPACITY,   # <-- accept opacity
):
    """
    Paint a horizontal black band centered at center_y with transparent fades above/below.
    Returns (img_with_band, solid_top, solid_bottom) so caller can keep text inside.
    """
    # Clamp opacity defensively
    try:
        opacity = float(opacity)
    except Exception:
        opacity = 1.0
    opacity = max(0.0, min(1.0, opacity))

    img = img.convert("RGBA")
    band_h = height + 2*fade

    # Vertical alpha gradient: fade-in -> solid -> fade-out
    alpha_col = Image.new("L", (1, band_h))
    for y in range(band_h):
        if y < fade:
            a = int(255 * (y / max(1, fade)))
        elif y < fade + height:
            a = 255
        else:
            a = int(255 * (1 - (y - fade - height) / max(1, fade)))
        a = int(a * opacity)  # apply opacity scaling
        alpha_col.putpixel((0, y), a)
    alpha = alpha_col.resize((img.width, band_h))

    black_band = Image.new("RGBA", (img.width, band_h), (0, 0, 0, 255))
    black_band.putalpha(alpha)

    # Overall band placement (includes fades)
    band_top = center_y - (height // 2 + fade)
    band_bottom = band_top + band_h

    # Clamp band to image; crop if needed
    top = max(0, band_top)
    bottom = min(img.height, band_bottom)
    if bottom <= top:
        solid_top = center_y - height // 2
        solid_bottom = solid_top + height
        return img, max(0, solid_top), min(img.height, solid_bottom)

    crop_top = top - band_top
    crop_bottom = crop_top + (bottom - top)
    band_cropped = black_band.crop((0, crop_top, img.width, crop_bottom))

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay.paste(band_cropped, (0, top), band_cropped)
    img = Image.alpha_composite(img, overlay)

    # Solid readable region
    solid_top = max(0, center_y - height // 2)
    solid_bottom = min(img.height, solid_top + height)
    return img, solid_top, solid_bottom



def add_text_overlay(image_path, title, platform_raw, percent_off, source_release_date):
    """
    Draws up to three centered lines; each line auto-fits its own max width.
    The stack is visually centered on the SOLID band, but can extend up to
    BAND_LEEWAY pixels into the fades above/below (bounded spill).
    """
    # 1) Paint gradient and get solid band bounds
    img = Image.open(image_path).convert("RGBA")
    img, solid_top, solid_bottom = add_gradient_background(
        img, center_y=TEXT_CENTER_Y, height=BAND_SOLID_HEIGHT, fade=BAND_FADE
    )
    draw = ImageDraw.Draw(img)

    # 2) Build the three lines
    rd = parse_release_date_any(source_release_date)
    today = get_today_ph_date()
    n = years_elapsed_until_today_ph(rd)

    if rd and rd == today:
        # 🎉 Release date is exactly today (including year)
        line1 = "Today..."
        releasing_now = True
    elif n == 0:
        line1 = "Today..."
        releasing_now = False
    else:
        year_word = "year" if n == 1 else "years"
        line1 = f"{n} {year_word} ago today..."
        releasing_now = False

    line2 = title or ""

    platform = _map_platform(platform_raw)
    po = _format_percent_off(percent_off)

    # Choose verb depending on whether it's a same-year release
    verb = "is releasing" if releasing_now else "released"

    if platform and po:
        line3 = f"{verb} on {platform}, now {po} OFF!"
    elif platform:
        line3 = f"{verb} on {platform}"
    elif po:
        line3 = f"{verb}, now {po} OFF!"
    else:
        line3 = verb

    # 3) Width-fit each line independently
    font_line1, size1 = _fit_font_to_width(draw, line1, BASE_FONT_SIZE_PX, LINE1_MAX_WIDTH_PX, STROKE_PX)
    font_line2, size2 = _fit_font_to_width(draw, line2, BASE_FONT_SIZE_PX, LINE2_MAX_WIDTH_PX, STROKE_PX)
    font_line3, size3 = _fit_font_to_width(draw, line3, BASE_FONT_SIZE_PX, LINE3_MAX_WIDTH_PX, STROKE_PX)

    def wh(txt, fnt):
        if not txt:
            return (0, 0)
        return _text_size(draw, txt, fnt, STROKE_PX)

    w1, h1 = wh(line1, font_line1)
    w2, h2 = wh(line2, font_line2)
    w3, h3 = wh(line3, font_line3)

    lines = []
    if line1: lines.append(("line1", line1, font_line1, size1, h1, LINE1_MAX_WIDTH_PX))
    if line2: lines.append(("line2", line2, font_line2, size2, h2, LINE2_MAX_WIDTH_PX))
    if line3: lines.append(("line3", line3, font_line3, size3, h3, LINE3_MAX_WIDTH_PX))

    gaps = max(len(lines) - 1, 0)
    total_h = sum(hh for (_, _, _, _, hh, _) in lines) + gaps * LINE_SPACING_PX

    # 4) Allow bounded spill into fades (solid height + leeway)
    #    (We still CENTER on the solid band; leeway only affects scaling threshold.)
    available_h = max(
        0,
        (solid_bottom - solid_top) + 2 * BAND_LEEWAY - 2 * BAND_INNER_PADDING
    )

    if total_h > available_h and available_h > 0:
        # Scale all font sizes proportionally first
        scale = available_h / total_h
        new_sizes = [max(MIN_FONT_SIZE_PX, int(sz * scale)) for (_, _, _, sz, _, _) in lines]

        # Refit each line by width using the new bases
        new_lines = []
        for (entry, new_base) in zip(lines, new_sizes):
            key, txt, _, _, _, max_w = entry
            fnt, final_sz = _fit_font_to_width(draw, txt, new_base, max_w, STROKE_PX)
            _, hh = wh(txt, fnt)
            new_lines.append((key, txt, fnt, final_sz, hh, max_w))
        lines = new_lines

        # Recompute total height
        gaps = max(len(lines) - 1, 0)
        total_h = sum(hh for (_, _, _, _, hh, _) in lines) + gaps * LINE_SPACING_PX

        # Final squeeze if still one or two pixels over
        while total_h > available_h and any(sz > MIN_FONT_SIZE_PX for (_, _, _, sz, _, _) in lines):
            squeezed = []
            for (key, txt, fnt, sz, hh, max_w) in lines:
                next_base = max(MIN_FONT_SIZE_PX, sz - 1)
                fnt2, sz2 = _fit_font_to_width(draw, txt, next_base, max_w, STROKE_PX)
                _, hh2 = wh(txt, fnt2)
                squeezed.append((key, txt, fnt2, sz2, hh2, max_w))
            lines = squeezed
            gaps = max(len(lines) - 1, 0)
            total_h = sum(hh for (_, _, _, _, hh, _) in lines) + gaps * LINE_SPACING_PX

    # 5) Placement — center on the SOLID band, then clamp to +- leeway
    center_x = img.width // 2
    band_center = (solid_top + solid_bottom) // 2
    top_y = int(round(band_center - total_h / 2))

    # Bounded spill: keep the block within [solid_top - leeway, solid_bottom + leeway]
    upper = solid_top - BAND_LEEWAY + BAND_INNER_PADDING
    lower = solid_bottom + BAND_LEEWAY - BAND_INNER_PADDING
    if top_y < upper:
        top_y = upper
    if top_y + total_h > lower:
        top_y = lower - total_h

    # 6) Draw
    title_color = (255, 185, 18)  # #ffb912
    other_color = (255, 255, 255)
    stroke_color = (0, 0, 0)

    y = top_y
    for key, txt, fnt, sz, hh, _ in lines:
        fill = title_color if key == "line2" else other_color
        draw.text(
            (center_x, y),
            txt,
            font=fnt,
            fill=fill,
            stroke_width=STROKE_PX,
            stroke_fill=stroke_color,
            anchor="ma",
        )
        y += hh + LINE_SPACING_PX

    # 7) Save
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
            percent_off=payload["percent_off"],
            source_release_date=payload["source_release_date"]
        )
        print("Applied text overlay.")
    except Exception as e:
        print(f"Failed to add text overlay: {e}")

if __name__ == "__main__":
    main()
