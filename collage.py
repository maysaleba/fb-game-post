import os, math, time
from io import BytesIO
import requests
from PIL import Image, ImageOps

DEFAULT_BG = (16, 16, 16)

def _download_image(url, timeout=20):
    try:
        r = requests.get(url, timeout=timeout, stream=True)
        r.raise_for_status()
        return Image.open(BytesIO(r.content)).convert("RGB")
    except Exception:
        return None

def _resize_into_cell(img, target_w, target_h, mode="cover", bg=DEFAULT_BG):
    if img is None:
        return Image.new("RGB", (target_w, target_h), (32, 32, 32))
    if mode == "cover":
        img_aspect = img.width / img.height
        cell_aspect = target_w / target_h
        if img_aspect > cell_aspect:
            new_h = target_h
            new_w = int(round(new_h * img_aspect))
        else:
            new_w = target_w
            new_h = int(round(new_w / img_aspect))
        img_resized = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        return img_resized.crop((left, top, left + target_w, top + target_h))
    else:
        img_fit = ImageOps.contain(img, (target_w, target_h), Image.LANCZOS)
        canvas = Image.new("RGB", (target_w, target_h), bg)
        x = (target_w - img_fit.width) // 2
        y = (target_h - img_fit.height) // 2
        canvas.paste(img_fit, (x, y))
        return canvas

def make_collage(
    urls,
    out_path,
    *,
    canvas_w=1820,
    cols=2,
    aspect_ratio=(16, 9),
    mode="cover",
    margin=0,
    gutter=0,
    bg=DEFAULT_BG,
    # Back-compat (accepted/ignored):
    canvas_h=None, rows=None, allow_duplicates=False, auto_fit=True,
    polite_delay=0.0, **_ignored
):
    """
    Fixed width, dynamic per-row height. If the last row has 1 image, it spans
    full width and its height is recomputed to keep the target aspect ratio.

    Examples (cols=2, 16:9):
      5 images -> rows: [2,2,1], heights: [512,512,1024]
      3 images -> rows: [2,1],   heights: [512,1024]
      8 images -> rows: [2,2,2,2], heights: [512,512,512,512]
    """
    if not urls:
        raise ValueError("No images provided.")

    n = len(urls)
    if cols < 1: cols = 1
    row_count = math.ceil(n / cols)

    # First pass: compute widths per row (items_in_row) and corresponding row heights.
    rows_meta = []  # list of (items_in_row, cell_w, cell_h, x_start)
    idx = 0
    for r in range(row_count):
        remaining = n - idx
        items_in_row = min(cols, remaining)

        if items_in_row == cols:
            # full row
            cell_w = (canvas_w - 2*margin - (cols - 1)*gutter) // cols
            x_start = margin
        else:
            if items_in_row == 1:
                cell_w = canvas_w - 2*margin               # spans full width
                x_start = margin
            else:
                # split evenly across width and center the row
                cell_w = (canvas_w - 2*margin - (items_in_row - 1)*gutter) // items_in_row
                row_w = items_in_row * cell_w + (items_in_row - 1) * gutter
                x_start = (canvas_w - row_w) // 2

        cell_h = int(round(cell_w * aspect_ratio[1] / aspect_ratio[0]))
        rows_meta.append((items_in_row, cell_w, cell_h, x_start))
        idx += items_in_row

    # Total canvas height = sum of row heights + vertical gutters + top/bottom margins
    canvas_h_dyn = sum(h for _, _, h, _ in rows_meta) + (len(rows_meta) - 1) * gutter + 2 * margin
    collage = Image.new("RGB", (canvas_w, canvas_h_dyn), bg)

    # Second pass: paste tiles using per-row height
    idx = 0
    y = margin
    for items_in_row, cell_w, cell_h, x_start in rows_meta:
        x = x_start
        for _ in range(items_in_row):
            if polite_delay > 0:
                time.sleep(polite_delay)
            img = _download_image(urls[idx]); idx += 1
            tile = _resize_into_cell(img, cell_w, cell_h, mode=mode, bg=bg)
            collage.paste(tile, (x, y))
            x += cell_w + gutter
        y += cell_h + gutter

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    collage.save(out_path, "JPEG", quality=92, subsampling=1)
    return out_path
