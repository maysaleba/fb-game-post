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

def fit_title_font(title, font_path, max_width, initial_size):
    size = initial_size
    while size > 10:
        trial_font = ImageFont.truetype(font_path, size)
        width = trial_font.getbbox(title)[2] - trial_font.getbbox(title)[0]
        if width <= max_width:
            return trial_font
        size -= 1
    return ImageFont.truetype(font_path, 10)

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

    raw_title = game.get('title', '').strip()
    region = game.get('cheapest_region', '').replace('Price', '').replace('NewZealand', 'New Zealand').replace('Southafrica', 'South Africa').strip()
    price = int(game.get('lowest_php_price', 0))
    formatted_price = f"{price:,}"
    sale_ends_raw = game.get('sale_ends', '')

    try:
        sale_ends = datetime.strptime(sale_ends_raw, '%Y-%m-%d').strftime('%b %d')
    except Exception:
        sale_ends = sale_ends_raw or 'N/A'

    # === Dynamically adjust font size for title ===
    title_font = fit_title_font(raw_title, FONT_PATH, MAX_TEXT_WIDTH, FONT_SIZE)
    title_line = (raw_title, (255, 185, 18))

    if PLATFORM == "ps" and game.get("cheapest_region") == "SalePrice":
        store_label = "Turkey PSN"
    elif PLATFORM == "switch" and game.get("cheapest_region") == "SalePrice":
        store_label = "US eShop"
    else:
        store_label = region + " eShop"

    segments = [
        ("is on sale on", (255, 255, 255), True),
        (store_label, (149, 239, 255), False),
        ("for", (255, 255, 255), True),
        (f"PHP {formatted_price}.00", (149, 239, 255), False),
        ("until", (255, 255, 255), True),
        (sale_ends, (149, 239, 255), False)
    ]

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

    lines = [title_line]
    lines.extend(wrapped_lines)

    try:
        top_left = resize_keep_aspect(Image.open(BytesIO(requests.get(selected[0]).content)), 500)
        top_right = resize_keep_aspect(Image.open(BytesIO(requests.get(selected[1]).content)), 500)
        bottom = resize_keep_aspect(Image.open(BytesIO(requests.get(selected[2]).content)), 1000)
    except Exception as e:
        print(f"❌ Failed to process {slug}: {e}")
        continue

    canvas = Image.new('RGB', (CANVAS_WIDTH, CANVAS_HEIGHT), color=(0, 0, 0))
    paste_top_aligned(canvas, top_left, 0, 0)
    paste_top_aligned(canvas, top_right, 500, 0)
    top_row_height = max(top_left.height, top_right.height)
    paste_top_aligned(canvas, bottom, 0, top_row_height)

    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(gradient, dest=(0, 0))
    canvas_rgba.alpha_composite(bottom_text, dest=(0, 0))
    button_path = None

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

    draw = ImageDraw.Draw(canvas_rgba)
    line_spacing = 10
    line_height = font.getbbox("Ay")[3] - font.getbbox("Ay")[1]
    y = TEXT_Y

    for line_index, line in enumerate(lines):
        if isinstance(line, tuple):
            text, color = line
            dynamic_font = title_font if line_index == 0 else font
            text_width = dynamic_font.getbbox(text)[2] - dynamic_font.getbbox(text)[0]
            x = (CANVAS_WIDTH - text_width) // 2
            draw.text((x, y), text, font=dynamic_font, fill=color)
        else:
            total_width = sum(font.getbbox(word)[2] - font.getbbox(word)[0] + space_width for word, _ in line) - space_width
            x = (CANVAS_WIDTH - total_width) // 2
            for word, color in line:
                draw.text((x, y), word, font=font, fill=color)
                x += font.getbbox(word)[2] - font.getbbox(word)[0] + space_width
        y += line_height + line_spacing

    final_image = canvas_rgba.convert("RGB")
    index = str(i + 1).zfill(3)
    output_path = os.path.join(OUTPUT_FOLDER, f"{index}_{slug}.jpg")
    final_image.save(output_path, 'JPEG')

print(f"✅ All images saved in '{OUTPUT_FOLDER}' with colored text and overlays.")
