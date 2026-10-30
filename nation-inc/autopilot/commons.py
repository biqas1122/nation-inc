"""Real photos of the people / products / places in the story from Wikimedia Commons.

Only freely-licensed images are used (Public domain, CC0, CC BY, CC BY-SA), and each one
is credited on screen and in the description, as those licenses require.
"""
import html
import re

import requests

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "TubeAutopilot/2.0 (faceless documentary channel; contact via GitHub)"}
OK_LICENSE = re.compile(r"^(public domain|pd|cc0|cc by(-sa)?( \d\.\d)?|cc-by(-sa)?)", re.I)
SKIP = re.compile(r"logo|icon|map|flag|signature|diagram|chart|coat of arms|svg", re.I)


def log(msg):
    print(f"[commons] {msg}", flush=True)


def _strip(s):
    return html.unescape(re.sub(r"<[^>]+>", "", str(s or ""))).strip()


def search(subject: str, used: set, limit: int = 12):
    """Returns one asset dict for the best freely-licensed photo of `subject`, or None."""
    subject = (subject or "").strip()
    if not subject:
        return None
    try:
        r = requests.get(API, headers=UA, timeout=30, params={
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
            "gsrsearch": f"{subject} filetype:bitmap", "gsrlimit": limit,
            "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 1920,
        })
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages") or {}
    except Exception as e:
        log(f"search '{subject}' failed: {e}")
        return None
    words = [w for w in re.findall(r"[a-z0-9]+", subject.lower()) if len(w) > 2]
    best = None
    for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
        title = p.get("title", "")
        if SKIP.search(title) or title in used:
            continue
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = _strip((meta.get("LicenseShortName") or {}).get("value"))
        if not OK_LICENSE.search(lic):
            continue
        if info.get("mime") not in ("image/jpeg", "image/png") or (info.get("width") or 0) < 900:
            continue
        hits = sum(1 for w in words if w in title.lower())
        if words and hits == 0:
            continue
        artist = _strip((meta.get("Artist") or {}).get("value"))[:60] or "Unknown"
        url = info.get("thumburl") or info.get("url")
        cand = {"type": "photo", "id": title, "url": url, "tags": subject,
                "credit": f"{artist} / Wikimedia Commons ({lic})",
                "credit_on_screen": f"Photo: {artist} · {lic}"}
        score = hits * 10 + min(info.get("width", 0), 3000) / 1000
        if not best or score > best[0]:
            best = (score, cand)
    if best:
        used.add(best[1]["id"])
        return best[1]
    return None
