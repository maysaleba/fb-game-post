import json
import requests
import os
import sys
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import random

# === Platform Argument ===
if len(sys.argv) != 2:
    print("Usage: python generateImage.py <platform>")
    sys.exit(1)

PLATFORM = sys.argv[1]
CONFIG_PATH = f"platforms/{PLATFORM}/image_config.json"

if not os.path.exists(CONFIG_PATH):
    print(f"❌ Config not found: {CONFIG_PATH}")
    sys.exit(1)

with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = json.load(f)

# === Config values ===
INPUT_FILE = config["input_file"]
OUTPUT_FOLDER = config["output_folder"]
GRADIENT_PATH = config["gradient_path"]
BUTTON_MAP = config.get("button_map", {})
PS_BUTTON_MAP = config.get("ps_button_map", {})
BOTTOM_TEXT_PATH = config["bottom_text_path"]
FONT_PATH = config["font_path"]
CANVAS_WIDTH = config["canvas_width"]
CANVAS_HEIGHT = config["canvas_height"]
FONT_SIZE = config["font_size"]
TEXT_Y = config["text_y"]
MAX_TEXT_WIDTH = config["max_text_width"]

# === Prepare output ===
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# === Load data ===
with open(INPUT_FILE, 'r', encoding='utf-8') as f:
    games = json.load(f)

games.sort(key=lambda g: int(g.get('Popularity', 0)), reverse=True)

# === Helpers ===
def resize_keep_aspect(image, target_width):
    w_percent = target_width / float(image.width)
    new_height = int(float(image.height) * w_percent)
    return image.resize((target_width, new_height), Image.LANCZOS)

def paste_top_aligned(canvas, img, x, y):
    canvas.paste(img, (x, y))

def text_width(px_font, s: str) -> int:
    if not s:
        return 0
    bbox = px_font.getbbox(s)
    return bbox[2] - bbox[0]

def best_two_line_wrap(title: str, fnt, max_width: int, min_words_per_line: int = 2):
    """
    Try all word break positions and choose the split that:
      1) keeps BOTH lines <= max_width,
      2) minimizes |w1 - w2| (balance),
      3) penalizes splits with a 1-word line (orphans).
    Returns [line1, line2] or None if no valid split at this font size.
    """
    words = title.split()
    if len(words) <= 1:
        return None

    best = None
    best_score = None

    for k in range(1, len(words)):  # break between words[k-1] | words[k]
        line1 = " ".join(words[:k])
        line2 = " ".join(words[k:])

        # discourage orphaned 1-word lines
        orphan_penalty = 3000 if (len(words[:k]) < min_words_per_line or len(words[k:]) < min_words_per_line) else 0

        w1 = text_width(fnt, line1)
        w2 = text_width(fnt, line2)

        if w1 <= max_width and w2 <= max_width:
            balance_score = abs(w1 - w2)        # prefer similar widths
            total_score = w1 + w2               # tie-breaker: smaller total width
            score = (balance_score * 1000) + total_score + orphan_penalty
            if best_score is None or score < best_score:
                best_score = score
                best = [line1, line2]

    return best

def fit_title_to_two_lines(title, font_path, max_width, initial_size, min_size=10, min_words_per_line=2):
    """
    Fit title into up to 2 lines using a balanced split.
    - If it fits on one line, keep it single-line.
    - Else, try all split points at decreasing sizes until both lines fit under max_width.
    - If nothing fits by min_size, truncate line 2 with an ellipsis.
    Returns: (title_lines, title_font)
    """
    size = initial_size
    while size >= min_size:
        fnt = ImageFont.truetype(font_path, size)

        # if full title fits on one line, use it
        if text_width(fnt, title) <= max_width:
            return [title], fnt

        # otherwise try balanced two-line split
        split = best_two_line_wrap(title, fnt, max_width, min_words_per_line=min_words_per_line)
        if split:
            return split, fnt

        size -= 1

    # Force-fit with truncation at min_size
    fnt = ImageFont.truetype(font_path, min_size)
    words = title.split()

    # Greedily fill line 1
    line1 = ""
    i = 0
    while i < len(words):
        test = words[i] if not line1 else f"{line1} {words[i]}"
        if text_width(fnt, test) <= max_width:
            line1 = test
            i += 1
        else:
            break

    # Remaining to line 2 (with ellipsis if needed)
    remaining = " ".join(words[i:])
    line2 = ""
    for w in remaining.split():
        test2 = w if not line2 else f"{line2} {w}"
        if text_width(fnt, test2 + " …") <= max_width:
            line2 = test2
        else:
            line2 = (line2 + " …").strip()
            break

    if not line2 and remaining:
        # even a single word doesn't fit with ellipsis — just ellipsize the word
        line2 = (remaining.split()[0] + " …").strip()

    return ([line1] if not line2 else [line1, line2]), fnt

# === Load overlays and font ===
gradient = Image.open(GRADIENT_PATH).convert("RGBA")
bottom_text = Image.open(BOTTOM_TEXT_PATH).convert("RGBA")
font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

# === Process each game ===
for i, game in enumerate(games):
    screenshots = game.get('screenshots', [])
    if len(screenshots) < 3:
        continue

    selected = random.sample(screenshots, 3)
    slug = game['slug']

    # --- Text data (UPPERCASED) ---
    raw_title = game.get('title', '').strip().upper()

    region = game.get('cheapest_region', '')
    region = (region.replace('Price', '')
                    .replace('NewZealand', 'NEW ZEALAND')
                    .replace('Southafrica', 'SOUTH AFRICA')
                    .strip()
                    .upper())

    price = int(game.get('lowest_php_price', 0))
    formatted_price = f"{price:,}"

    sale_ends_raw = game.get('sale_ends', '')
    try:
        sale_ends = datetime.strptime(sale_ends_raw, '%Y-%m-%d').strftime('%b %d').upper()
    except Exception:
        sale_ends = (sale_ends_raw or 'N/A').upper()

    # === Title: balanced fit + wrap to max 2 lines ===
    title_lines, title_font = fit_title_to_two_lines(
        raw_title, FONT_PATH, MAX_TEXT_WIDTH, FONT_SIZE, min_size=10, min_words_per_line=2
    )
    TITLE_LINES_COUNT = len(title_lines)

    # === Store label (UPPERCASED) ===
    if PLATFORM == "ps" and game.get("cheapest_region") == "SalePrice":
        store_label = "TURKEY PSN"
    elif PLATFORM == "switch" and game.get("cheapest_region") == "SalePrice":
        store_label = "US ESHOP"
    else:
        store_label = f"{region} ESHOP"

    # === Build segments (UPPERCASE) ===
    segments = [
        ("IS ON SALE ON", (255, 255, 255), True),
        (store_label, (149, 239, 255), False),
        ("FOR", (255, 255, 255), True),
        (f"PHP {formatted_price}.00", (149, 239, 255), False),
        ("UNTIL", (255, 255, 255), True),
        (sale_ends, (149, 239, 255), False)
    ]

    # === Colorized word wrapping for sale-info ===
    words_colored = []
    for text, color, should_split in segments:
        if should_split:
            for word in text.split(" "):
                words_colored.append((word, color))
        else:
            words_colored.append((text, color))

    space_width = font.getbbox(" ")[2] - font.getbbox(" ")[0]
    wrapped_lines = []
    current_line = []
    current_width = 0

    for word, color in words_colored:
        word_width = font.getbbox(word)[2] - font.getbbox(word)[0]
        if current_width + word_width > MAX_TEXT_WIDTH and current_line:
            wrapped_lines.append(current_line)
            current_line = [(word, color)]
            current_width = word_width + space_width
        else:
            current_line.append((word, color))
            current_width += word_width + space_width

    if current_line:
        wrapped_lines.append(current_line)

    # === Assemble final lines: 1–2 title lines, then wrapped sale-info ===
    lines = [(t, (255, 185, 18)) for t in title_lines]  # gold title lines
    lines.extend(wrapped_lines)

    # === Load images ===
    try:
        top_left = resize_keep_aspect(Image.open(BytesIO(requests.get(selected[0]).content)), 500)
        top_right = resize_keep_aspect(Image.open(BytesIO(requests.get(selected[1]).content)), 500)
        bottom = resize_keep_aspect(Image.open(BytesIO(requests.get(selected[2]).content)), 1000)
    except Exception as e:
        print(f"❌ Failed to process {slug}: {e}")
        continue

    # === Compose canvas ===
    canvas = Image.new('RGB', (CANVAS_WIDTH, CANVAS_HEIGHT), color=(0, 0, 0))
    paste_top_aligned(canvas, top_left, 0, 0)
    paste_top_aligned(canvas, top_right, 500, 0)
    top_row_height = max(top_left.height, top_right.height)
    paste_top_aligned(canvas, bottom, 0, top_row_height)

    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(gradient, dest=(0, 0))
    canvas_rgba.alpha_composite(bottom_text, dest=(0, 0))
    button_path = None

    # === Platform button overlays ===
    if PLATFORM == "ps":
        is_ps4 = game.get("IsPS4", 0)
        is_ps5 = game.get("IsPS5", 0)

        if is_ps4 == 1 and is_ps5 == 0:
            button_path = PS_BUTTON_MAP.get("ps4_only")
        elif is_ps4 == 0 and is_ps5 == 1:
            button_path = PS_BUTTON_MAP.get("ps5_only")
        elif is_ps4 == 1 and is_ps5 == 1:
            button_path = PS_BUTTON_MAP.get("ps4_ps5")
    else:
        game_platform = game.get("platform", "")
        button_path = BUTTON_MAP.get(game_platform)

    if button_path and os.path.exists(button_path):
        try:
            button_overlay = Image.open(button_path).convert("RGBA")
            canvas_rgba.alpha_composite(button_overlay, dest=(0, 0))
        except Exception as e:
            print(f"⚠️ Failed to load button overlay: {e}")
    else:
        print(f"⚠️ No button overlay found for game: {game.get('title')} ({button_path})")

    # === Draw text (same layout behavior as your current script) ===
    draw = ImageDraw.Draw(canvas_rgba)
    line_spacing = 10
    line_height = font.getbbox("Ay")[3] - font.getbbox("Ay")[1]
    y = TEXT_Y

    for line_index, line in enumerate(lines):
        if isinstance(line, tuple):
            # Title lines (use title_font for however many title lines we have)
            text, color = line
            dynamic_font = title_font if line_index < TITLE_LINES_COUNT else font
            text_width_px = dynamic_font.getbbox(text)[2] - dynamic_font.getbbox(text)[0]
            x = (CANVAS_WIDTH - text_width_px) // 2
            draw.text((x, y), text, font=dynamic_font, fill=color)
        else:
            # Wrapped sale-info line (list of (word, color))
            total_width = sum(font.getbbox(word)[2] - font.getbbox(word)[0] + space_width for word, _ in line) - space_width
            x = (CANVAS_WIDTH - total_width) // 2
            for word, color in line:
                draw.text((x, y), word, font=font, fill=color)
                x += font.getbbox(word)[2] - font.getbbox(word)[0] + space_width

        y += line_height + line_spacing

    # === Save ===
    final_image = canvas_rgba.convert("RGB")
    index = str(i + 1).zfill(3)
    output_path = os.path.join(OUTPUT_FOLDER, f"{index}_{slug}.jpg")
    final_image.save(output_path, 'JPEG')

print(f"✅ All images saved in '{OUTPUT_FOLDER}' with balanced, UPPERCASE titles and colorized sale text.")
