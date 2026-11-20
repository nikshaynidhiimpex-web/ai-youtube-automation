"""Free stock footage/photos for each scene.

Providers (whichever keys are set, in this order):
  PIXABAY_API_KEY  - https://pixabay.com/api/docs/ (free, videos + photos)
  PEXELS_API_KEY   - https://www.pexels.com/api/ (free, videos + photos)
Per scene: video -> photo -> none (animated gradient in render).
"""
import random
import re
import time

import requests

from .common import env

PEXELS = "https://api.pexels.com"
PIXABAY = "https://pixabay.com/api"
MAX_BYTES = 80 * 1024 * 1024


def _download(url, path, headers=None):
    for attempt in range(3):
        with requests.get(url, stream=True, timeout=60, headers=headers) as r:
            if r.status_code == 429 and attempt < 2:  # rate limited: wait and retry
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            size = 0
            with open(path, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise RuntimeError("media file too large")
                    f.write(chunk)
        return path
    raise RuntimeError("download rate limited")


def _query_variants(query):
    words = query.split()
    variants = [query, " ".join(words[:2]), words[0] if words else ""]
    seen, out = set(), []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


# ------------------------------------------------------------------ Pixabay
def _pixabay_video(query, key, dest, used):
    r = requests.get(f"{PIXABAY}/videos/", timeout=30, params={
        "key": key, "q": query[:100], "safesearch": "true", "per_page": 20,
    })
    r.raise_for_status()
    candidates = []
    for hit in r.json().get("hits", []):
        if ("xv", hit["id"]) in used or hit.get("duration", 0) < 4:
            continue
        versions = hit.get("videos", {})
        best = next((versions[k] for k in ("large", "medium")
                     if versions.get(k, {}).get("url") and versions[k].get("height", 0) >= 720),
                    None)
        if best:
            portrait = best["height"] > best["width"]
            candidates.append((0 if portrait else 1, hit, best))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])  # vertical videos first, keep relevance order
    _, hit, file = random.choice(candidates[:5])
    used.add(("xv", hit["id"]))
    path = _download(file["url"], dest.with_suffix(".mp4"))
    return {"type": "video", "path": path, "credit": hit.get("user", ""), "source": "Pixabay"}


def _pixabay_photo(query, key, dest, used):
    r = requests.get(f"{PIXABAY}/", timeout=30, params={
        "key": key, "q": query[:100], "image_type": "photo", "orientation": "vertical",
        "safesearch": "true", "per_page": 20,
    })
    r.raise_for_status()
    hits = [h for h in r.json().get("hits", []) if ("xp", h["id"]) not in used]
    if not hits:
        return None
    hit = random.choice(hits[:5])
    used.add(("xp", hit["id"]))
    path = _download(hit["largeImageURL"], dest.with_suffix(".jpg"))
    return {"type": "image", "path": path, "credit": hit.get("user", ""), "source": "Pixabay"}


# ------------------------------------------------------------------- Pexels
def _pexels_video(query, key, dest, used):
    r = requests.get(f"{PEXELS}/videos/search", headers={"Authorization": key}, timeout=30,
                     params={"query": query, "orientation": "portrait", "size": "medium",
                             "per_page": 15})
    r.raise_for_status()
    candidates = []
    for video in r.json().get("videos", []):
        if ("v", video["id"]) in used or video.get("duration", 0) < 4:
            continue
        files = [f for f in video.get("video_files", [])
                 if f.get("width") and f.get("height")
                 and f["height"] > f["width"] and f["height"] >= 1280]
        if files:
            candidates.append((video, min(files, key=lambda f: f["height"])))
    if not candidates:
        return None
    video, file = random.choice(candidates[:5])
    used.add(("v", video["id"]))
    path = _download(file["link"], dest.with_suffix(".mp4"))
    return {"type": "video", "path": path,
            "credit": video.get("user", {}).get("name", ""), "source": "Pexels"}


def _pexels_photo(query, key, dest, used):
    r = requests.get(f"{PEXELS}/v1/search", headers={"Authorization": key}, timeout=30,
                     params={"query": query, "orientation": "portrait", "per_page": 15})
    r.raise_for_status()
    photos = [p for p in r.json().get("photos", []) if ("p", p["id"]) not in used]
    if not photos:
        return None
    photo = random.choice(photos[:5])
    used.add(("p", photo["id"]))
    path = _download(photo["src"]["large2x"], dest.with_suffix(".jpg"))
    return {"type": "image", "path": path, "credit": photo.get("photographer", ""),
            "source": "Pexels"}


# --------------------------------------------------------- Wikimedia Commons
# No key needed. Free-licensed photos; author + licence go into the description.
COMMONS = "https://commons.wikimedia.org/w/api.php"
COMMONS_HEADERS = {"User-Agent": "HindiFactsShortsBot/1.0 (personal educational project)"}
OK_LICENSES = ("public domain", "pd", "cc0", "cc by")  # "cc by" also matches CC BY-SA
NOT_PHOTO = re.compile(r"diagram|chart|graph|map|logo|schematic|plot|scheme|icon|"
                       r"bulletin|book|page|text|table|screenshot|flag|seal", re.I)


def _strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _commons_photo(query, _key, dest, used):
    r = requests.get(COMMONS, headers=COMMONS_HEADERS, timeout=30, params={
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6, "gsrlimit": 25,
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1600,
    })
    r.raise_for_status()
    pages = sorted(r.json().get("query", {}).get("pages", {}).values(),
                   key=lambda p: p.get("index", 0))
    candidates = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        license_name = _strip_html(meta.get("LicenseShortName", {}).get("value"))
        if (("c", page["pageid"]) in used
                or NOT_PHOTO.search(page.get("title", ""))
                or info.get("mime") not in ("image/jpeg", "image/png")
                or info.get("width", 0) < 1000 or info.get("height", 0) < 800
                or not license_name.lower().startswith(OK_LICENSES)):
            continue
        artist = _strip_html(meta.get("Artist", {}).get("value"))[:80] or "Unknown"
        candidates.append((page, info, license_name, artist))
    if not candidates:
        return None
    page, info, license_name, artist = random.choice(candidates[:5])
    used.add(("c", page["pageid"]))
    ext = ".png" if info["mime"] == "image/png" else ".jpg"
    path = _download(info.get("thumburl") or info["url"], dest.with_suffix(ext),
                     headers=COMMONS_HEADERS)
    return {"type": "image", "path": path, "source": "Wikimedia Commons",
            "attribution": f"{artist}, {license_name}, via Wikimedia Commons"}


def _fetchers():
    fetchers = []
    pixabay, pexels = env("PIXABAY_API_KEY"), env("PEXELS_API_KEY")
    if pixabay:
        fetchers += [(_pixabay_video, pixabay), (_pixabay_photo, pixabay)]
    if pexels:
        fetchers += [(_pexels_video, pexels), (_pexels_photo, pexels)]
    if env("USE_WIKIMEDIA", "1") == "1":
        fetchers.append((_commons_photo, ""))
    return fetchers


def fetch_scene_media(scenes, workdir):
    fetchers = _fetchers()
    if not fetchers:
        print("No image sources enabled: using animated gradient backgrounds.")
        return [{"type": "none"} for _ in scenes]

    used, media = set(), []
    for i, scene in enumerate(scenes):
        found = None
        multi_word = len(scene["query"].split()) > 1
        for query in _query_variants(scene["query"]):
            for fetch, key in fetchers:
                # A single generic word ("deep") gives unrelated Commons results
                if fetch is _commons_photo and multi_word and len(query.split()) == 1:
                    continue
                try:
                    found = fetch(query, key, workdir / f"media_{i}", used)
                except Exception as error:
                    message = str(error)
                    if key:
                        message = message.replace(key, "***")
                    message = message[:200]
                    print(f"{fetch.__name__} failed for '{query}':", message)
                if found:
                    break
            if found:
                break
        found = found or {"type": "none"}
        print(f"SCENE {i + 1}: '{scene['query']}' -> {found['type']} "
              f"{found.get('source', '')}")
        media.append(found)
    return media
