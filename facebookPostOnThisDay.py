# facebookPostOnThisDay.py
import os, re, json, glob, requests
from datetime import datetime, timedelta, timezone

# === CONFIG ===
OUTPUT_DIR = "output"  # where your collage_*.jpg and screenshots_*.json are saved
PAGE_ID = os.getenv("FB_PAGE_ID", "110345971129305")

# Prefer env for security (GitHub Actions: add FB_PAGE_ACCESS_TOKEN_LIVE to Secrets)
ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN_TEST", "EAAQQDe5YQC4BPJPPsPMXxsPYJ3gblJs3SDsCYG25QTlhIgMj2lrjR6X9VP9kYxdX1PI3Ty01FNsviagC0UbxwvISknFb870L3NUZBQ6bL1EXR7YOT0ndsMfO2z1aNZAK2V8BVgKlrZAfuQZBDCMIVn2yRkcPdG4w8eR4HaReV4CUShxMHubyZBQoSAqGOngZCvAeA9lvTisnuEqSiiRlmq6TsZD")

# Optional local fallback (if you want). If present, should contain {"fb_access_token":"..."}
LOCAL_TOKEN_JSON = "fb_local.json"

# PH time (UTC+8) for timestamp in caption
PH_TZ = timezone(timedelta(hours=8))

# === Helpers ===
def load_access_token():
    if ACCESS_TOKEN:
        return ACCESS_TOKEN
    if os.path.exists(LOCAL_TOKEN_JSON):
        with open(LOCAL_TOKEN_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
            tok = data.get("fb_access_token") or data.get("access_token")
            if tok: return tok
    raise RuntimeError("No Facebook access token. Set FB_PAGE_ACCESS_TOKEN_LIVE env or create fb_local.json")

def newest_file(pattern):
    files = glob.glob(pattern)
    if not files:
        return None
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0]

def matching_json_for_collage(collage_path):
    # collage_<slug>.jpg  -> screenshots_<slug>.json
    m = re.match(r".*collage_(.+)\.jpe?g$", collage_path, re.IGNORECASE)
    if not m:
        return None
    slug = m.group(1)
    candidate = os.path.join(OUTPUT_DIR, f"screenshots_{slug}.json")
    return candidate if os.path.exists(candidate) else None

def clean_summary(text, max_len=500):
    if not text:
        return ""
    one_line = " ".join(str(text).split())
    return (one_line[:max_len] + "…") if len(one_line) > max_len else one_line

def build_caption(meta):
    """
    Builds a Facebook caption based on release date year vs today's PH year.
    """
    title     = meta.get("title", "").strip()
    platform  = meta.get("platform", "").strip()
    slug = meta.get("slug","").strip()
    summary   = clean_summary(meta.get("summary", ""))
    release_str = meta.get("source_release_date", "")
    matched_on = meta.get("matched_on", "")  # "MM-DD"

    # Parse release date
    release_year = None
    try:
        if release_str:
            release_year = int(str(release_str)[:4])
    except ValueError:
        release_year = None

    today_year = datetime.now(PH_TZ).year

    # Build date_str (pretty month/day)
    date_str = ""
    if matched_on and re.match(r"^\d{2}-\d{2}$", matched_on):
        month, day = matched_on.split("-")
        try:
            pretty = datetime(today_year, int(month), int(day)).strftime("%b %d")
            date_str = pretty
        except Exception:
            date_str = matched_on

    # Build main line
    if release_year and release_year < today_year:
        years_ago = today_year - release_year
        main_line = f"{years_ago} year{'s' if years_ago > 1 else ''} ago, on this day, {title} has been released for the {platform}!"
    elif release_year and release_year == today_year:
        main_line = f"{title} for the {platform} is releasing today!"
    else:
        main_line = f"{title} for the {platform}"

    # Assemble caption
    parts = []
    if date_str:
        parts.append("🎮 On This Day in Gaming Sale!")
    parts.append(main_line)
    if summary:
        parts.append(f"🕹️ Summary: {summary}")

    # Platform-specific link
    platform_lower = platform.strip().lower()
    if platform_lower == "nintendo switch":
        parts.append(f"🎯 On Sale Now! maysaleba.com/games/{slug}-switch")
    elif platform_lower == "nintendo switch 2":
        parts.append(f"🎯 On Sale Now! maysaleba.com/games/{slug}-switch-2")
    else:
        parts.append(f"🎯 On Sale Now! maysaleba.com/games/{slug}")

    parts.append("#OnThisDay #Gaming #NintendoSwitch")  # adjust hashtags as needed
    return "\n\n".join(parts).strip()

# === Main ===
def main():
    token = load_access_token()

    # 1) Find newest collage image in OUTPUT_DIR
    collage_path = newest_file(os.path.join(OUTPUT_DIR, "collage_*.jpg"))
    if not collage_path:
        print("❌ No collage_*.jpg found in output/")
        return

    # 2) Find matching JSON
    json_path = matching_json_for_collage(collage_path)
    if not json_path:
        print(f"⚠️ No matching screenshots_*.json for {os.path.basename(collage_path)} — posting with a simple caption.")
        meta = {}
    else:
        with open(json_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    caption = build_caption(meta)

    print(f"🖼️ Posting: {os.path.basename(collage_path)}")
    print(f"📝 Caption preview:\n{caption}\n")

    # 3) POST single photo (simplest, most reliable)
    url = f"https://graph.facebook.com/v23.0/{PAGE_ID}/photos"
    with open(collage_path, "rb") as img_file:
        resp = requests.post(
            url,
            files={"source": img_file},
            data={
                "caption": caption,
                "access_token": token,
            },
            timeout=90
        )
    try:
        data = resp.json()
    except Exception:
        print(f"❌ Facebook response (non-JSON): {resp.status_code} {resp.text}")
        return

    if "id" in data:
        print(f"✅ Posted image: {data['id']}")
    else:
        print(f"❌ Failed to post: {data}")

if __name__ == "__main__":
    main()
