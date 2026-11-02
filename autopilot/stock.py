"""Free stock footage from Pixabay (default) or Pexels, with a relevance check on every clip."""
import re
import time
from pathlib import Path

import requests

STOP = {"a", "an", "the", "of", "and", "in", "on", "at", "with", "to", "for", "by", "from", "old", "new", "vintage"}


def log(msg):
    print(f"[stock] {msg}", flush=True)


def _get(url, params=None, headers=None, name="stock"):
    for i in range(4):
        r = requests.get(url, params=params, headers=headers, timeout=60)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(8 * (i + 1))
            continue
        raise RuntimeError(f"{name} error {r.status_code}: {r.text[:200]}")
    raise RuntimeError(f"{name} rate limit reached")


def _words(text):
    out = set()
    for w in re.findall(r"[a-z]+", str(text).lower()):
        if w in STOP or len(w) < 3:
            continue
        out.add(w)
        if w.endswith("s") and len(w) > 4:
            out.add(w[:-1])          # sneakers → sneaker
    return out


def _score(query, text):
    """How many meaningful query words appear in the clip's tags/description."""
    q = _words(query)
    t = _words(text)
    return len(q & t), len(q)


_cache: dict = {}


# ---------- Pixabay ----------

def _pixabay_videos(cfg, q):
    key = ("pv", q)
    if key not in _cache:
        j = _get("https://pixabay.com/api/videos/", {"key": cfg["pixabay_key"], "q": q, "per_page": 50, "safesearch": "true"}, name="Pixabay")
        out = []
        for h in j.get("hits", []):
            v = h.get("videos", {})
            f = None
            for size in ("medium", "large", "small"):   # medium (≈1280-1920 wide) keeps downloads fast
                c = v.get(size) or {}
                if c.get("url") and c.get("width", 0) >= c.get("height", 1) and c.get("width", 0) >= 1280:
                    f = c
                    break
            if f:
                out.append({"type": "video", "id": f"xv{h['id']}", "url": f["url"], "duration": float(h.get("duration", 0)),
                            "tags": h.get("tags", ""), "credit": f"{h.get('user', 'Pixabay')} (Pixabay)"})
        _cache[key] = out
    return _cache[key]


def _pixabay_photos(cfg, q):
    key = ("pp", q)
    if key not in _cache:
        j = _get("https://pixabay.com/api/", {"key": cfg["pixabay_key"], "q": q, "image_type": "photo", "orientation": "horizontal",
                                              "per_page": 40, "safesearch": "true", "min_width": 1600}, name="Pixabay")
        _cache[key] = [{"type": "photo", "id": f"xp{h['id']}", "url": h.get("largeImageURL") or h.get("webformatURL"),
                        "tags": h.get("tags", ""), "credit": f"{h.get('user', 'Pixabay')} (Pixabay)"} for h in j.get("hits", [])]
    return _cache[key]


# ---------- Pexels ----------

def _pexels_videos(cfg, q):
    key = ("xv", q)
    if key not in _cache:
        j = _get("https://api.pexels.com/videos/search", {"query": q, "orientation": "landscape", "per_page": 40},
                 {"Authorization": cfg["pexels_key"]}, "Pexels")
        out = []
        for v in j.get("videos", []):
            files = [f for f in v.get("video_files", []) if "mp4" in (f.get("file_type") or "") and (f.get("width") or 0) >= 1280
                     and (f.get("width") or 0) >= (f.get("height") or 1)]
            files.sort(key=lambda f: abs((f.get("width") or 0) - 1920))
            if files:
                slug = v.get("url", "").rstrip("/").split("/")[-1].replace("-", " ")
                out.append({"type": "video", "id": f"v{v['id']}", "url": files[0]["link"], "duration": float(v.get("duration", 0)),
                            "tags": slug, "credit": f"{v.get('user', {}).get('name', 'Pexels')} (Pexels)"})
        _cache[key] = out
    return _cache[key]


def _pexels_photos(cfg, q):
    key = ("xp", q)
    if key not in _cache:
        j = _get("https://api.pexels.com/v1/search", {"query": q, "orientation": "landscape", "per_page": 30},
                 {"Authorization": cfg["pexels_key"]}, "Pexels")
        _cache[key] = [{"type": "photo", "id": f"p{p['id']}", "url": p["src"].get("large2x") or p["src"]["original"],
                        "tags": p.get("alt", ""), "credit": f"{p.get('photographer', 'Pexels')} (Pexels)"} for p in j.get("photos", [])]
    return _cache[key]


def _mix(a, b):
    """Interleaves results of two providers (Pexels + Pixabay) so both get used."""
    def f(cfg, q):
        try:
            xs = a(cfg, q)
        except Exception as e:
            log(f"{a.__name__} failed: {e}")
            xs = []
        try:
            ys = b(cfg, q)
        except Exception as e:
            log(f"{b.__name__} failed: {e}")
            ys = []
        out = []
        for i in range(max(len(xs), len(ys))):
            out += [x[i] for x in (xs, ys) if i < len(x)]
        return out
    f.__name__ = f"mix_{a.__name__}"
    return f


def _provider(cfg):
    has_px, has_pb = bool(cfg.get("pexels_key")), bool(cfg.get("pixabay_key"))
    mode = cfg.get("stock_provider", "pixabay")
    if mode == "both" and has_px and has_pb:
        return _mix(_pexels_videos, _pixabay_videos), _mix(_pexels_photos, _pixabay_photos)
    if (mode == "pexels" or (mode == "both" and has_px)) and has_px:
        return _pexels_videos, _pexels_photos
    return _pixabay_videos, _pixabay_photos


# ---------- public ----------

def _relevant(items, q, used, min_hits):
    good = []
    for it in items:
        if it["id"] in used:
            continue
        hits, n = _score(q, it["tags"])
        if hits >= min_hits:
            good.append((hits, it))
    good.sort(key=lambda x: -x[0])
    return [it for _, it in good]


def find_shots(cfg, queries, n, used):
    """Returns up to n DIFFERENT relevant assets for one scene (videos preferred, photos as backup)."""
    videos, photos = _provider(cfg)
    queries = [q for q in dict.fromkeys(str(q).strip() for q in queries) if q]
    picked = []
    # pass 1: clips whose tags contain ALL query words; pass 2: at least one word
    for strict in (True, False):
        for q in queries:
            if len(picked) >= n:
                break
            need = max(1, len(_words(q))) if strict else 1
            try:
                for it in _relevant(videos(cfg, q), q, used, need):
                    if len(picked) >= n:
                        break
                    used.add(it["id"])
                    picked.append(it)
            except Exception as e:
                log(f"search '{q}' failed: {e}")
        if len(picked) >= n:
            break
    if len(picked) < n:
        for q in queries:
            try:
                for it in _relevant(photos(cfg, q), q, used, 1):
                    if len(picked) >= n:
                        break
                    used.add(it["id"])
                    picked.append(it)
            except Exception as e:
                log(f"photo search '{q}' failed: {e}")
    return picked


def find_photo(cfg, query):
    _, photos = _provider(cfg)
    items = _relevant(photos(cfg, query), query, set(), max(1, len(_words(query))))
    if not items:
        items = _relevant(photos(cfg, query), query, set(), 1)
    return items[0] if items else None


_downloaded: dict = {}


def download(asset: dict, dest: Path) -> Path:
    if asset["url"] in _downloaded:
        asset["path"] = _downloaded[asset["url"]]
        return Path(asset["path"])
    ext = ".mp4" if asset["type"] == "video" else ".jpg"
    path = dest.with_suffix(ext)
    headers = {"User-Agent": "TubeAutopilot/2.0 (faceless documentary channel; contact via GitHub)"}
    with requests.get(asset["url"], stream=True, timeout=180, headers=headers) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for block in r.iter_content(1 << 20):
                f.write(block)
    asset["path"] = str(path)
    _downloaded[asset["url"]] = str(path)
    return path
