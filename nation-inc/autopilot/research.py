"""Competitor research: what is working in our niche right now.

1. DISCOVER competitors: YouTube search for niche phrases (long videos, last 12 months) -> the channels
   that keep showing up, filtered to real case-study channels (English, enough long videos, not giants).
2. COLLECT each channel's long uploads from the last 12 months (views, length, date).
3. RANK every video by its OUTLIER MULTIPLE = its views / that channel's median views.
   (Raw views just rank channel size; the multiple ranks the IDEA. Same method as the MIT-licensed
   "yt-viral" skill by Jake Schincariol.)
4. SAVE the result to state/research.json + state/research.md (always) and a "Research" sheet tab.

Uses the YouTube Data API with a free API key (YOUTUBE_API_KEY). Quota used per run is about
1,200 of the free 10,000 units/day.
"""
import datetime as dt
import json
import re
import statistics
import time

import requests

from .config import STATE

API = "https://www.googleapis.com/youtube/v3"


def log(msg):
    print(f"[research] {msg}", flush=True)


def _get(key, path, **params):
    for i in range(4):
        r = requests.get(f"{API}/{path}", params={**params, "key": key}, timeout=60)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (500, 503):
            time.sleep(4 * (i + 1))
            continue
        msg = r.text[:300]
        if r.status_code == 403 and "quota" in msg.lower():
            raise RuntimeError("YouTube API daily quota used up — research will retry next run.")
        raise RuntimeError(f"YouTube API {path} error {r.status_code}: {msg}")
    raise RuntimeError(f"YouTube API {path} kept failing")


def _seconds(iso):
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _chunks(xs, n=50):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


# ---------------------------------------------------------------- discover

def discover_channels(cfg, key, since_iso):
    queries = cfg.get("research_queries") or []
    seen = {}
    for q in queries:
        for length in ("medium", "long"):          # 4-20 min and 20+ min documentaries
            try:
                j = _get(key, "search", part="snippet", q=q, type="video", videoDuration=length,
                         order="viewCount", publishedAfter=since_iso, relevanceLanguage="en", maxResults=50)
            except RuntimeError as e:
                log(f"search '{q}' ({length}) failed: {e}")
                if "quota" in str(e).lower():
                    raise
                continue
            for it in j.get("items", []):
                cid = it["snippet"]["channelId"]
                seen.setdefault(cid, {"id": cid, "title": it["snippet"]["channelTitle"], "hits": 0})
                seen[cid]["hits"] += 1
    for handle in cfg.get("competitor_handles") or []:
        try:
            r = _get(key, "channels", part="id,snippet", forHandle=handle.lstrip("@"))
            for it in r.get("items", []):
                seen.setdefault(it["id"], {"id": it["id"], "title": it["snippet"]["title"], "hits": 0})
                seen[it["id"]]["hits"] += 5   # hand-picked seeds always count
        except RuntimeError as e:
            log(f"handle {handle} failed: {e}")
    log(f"{len(seen)} channels found from {len(queries)} searches")
    return list(seen.values())


def channel_details(key, chans):
    out = []
    for group in _chunks([c["id"] for c in chans]):
        j = _get(key, "channels", part="snippet,statistics,contentDetails", id=",".join(group), maxResults=50)
        for it in j.get("items", []):
            st = it.get("statistics", {})
            out.append({
                "id": it["id"],
                "title": it["snippet"]["title"],
                "country": it["snippet"].get("country", ""),
                "subs": int(st.get("subscriberCount", 0) or 0),
                "videos": int(st.get("videoCount", 0) or 0),
                "uploads": it["contentDetails"]["relatedPlaylists"]["uploads"],
                "hits": next((c["hits"] for c in chans if c["id"] == it["id"]), 0),
            })
    return out


def recent_long_videos(key, uploads, since, min_seconds, max_pages=4):
    ids, page = [], None
    for _ in range(max_pages):
        j = _get(key, "playlistItems", part="contentDetails", playlistId=uploads, maxResults=50,
                 **({"pageToken": page} if page else {}))
        stop = False
        for it in j.get("items", []):
            pub = it["contentDetails"].get("videoPublishedAt", "")
            if pub and pub < since:
                stop = True
                break
            ids.append(it["contentDetails"]["videoId"])
        page = j.get("nextPageToken")
        if stop or not page:
            break
    vids = []
    for group in _chunks(ids):
        j = _get(key, "videos", part="snippet,statistics,contentDetails", id=",".join(group), maxResults=50)
        for it in j.get("items", []):
            secs = _seconds(it["contentDetails"].get("duration"))
            if secs < min_seconds:
                continue   # skip Shorts and short clips
            vids.append({
                "id": it["id"],
                "title": it["snippet"]["title"],
                "published": it["snippet"]["publishedAt"][:10],
                "views": int(it.get("statistics", {}).get("viewCount", 0) or 0),
                "minutes": round(secs / 60, 1),
            })
    return vids


# ---------------------------------------------------------------- main

def run(cfg):
    key = cfg.get("youtube_api_key")
    if not key:
        raise SystemExit("Missing GitHub secret: YOUTUBE_API_KEY (needed for competitor research)")
    now = dt.datetime.now(dt.timezone.utc)
    since = (now - dt.timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    min_secs = int(cfg.get("research_min_minutes", 6)) * 60

    found = discover_channels(cfg, key, since)
    chans = channel_details(key, found)
    lo, hi = int(cfg.get("competitor_min_subs", 20000)), int(cfg.get("competitor_max_subs", 8000000))
    chans = [c for c in chans if lo <= c["subs"] <= hi and c["videos"] >= 8]
    chans.sort(key=lambda c: (-c["hits"], -c["subs"]))
    want = int(cfg.get("competitors_max", 30))

    results, kept = [], []
    for c in chans:
        if len(kept) >= want:
            break
        try:
            vids = recent_long_videos(key, c["uploads"], since, min_secs)
        except RuntimeError as e:
            log(f"{c['title']}: {e}")
            continue
        if len(vids) < 4:
            continue   # a median needs at least 4 videos
        med = statistics.median(v["views"] for v in vids) or 1
        c["median_views"] = int(med)
        c["long_videos_12m"] = len(vids)
        kept.append(c)
        for v in vids:
            v.update(channel=c["title"], subs=c["subs"], multiple=round(v["views"] / med, 2),
                     url=f"https://youtu.be/{v['id']}")
            results.append(v)
    log(f"{len(kept)} competitor channels analysed, {len(results)} long videos from the last 12 months")

    min_mult = float(cfg.get("research_min_multiple", 1.8))
    outliers = sorted([v for v in results if v["multiple"] >= min_mult and v["views"] >= 20000],
                      key=lambda v: (-v["multiple"], -v["views"]))
    top = outliers[: int(cfg.get("research_top", 60))]

    data = {
        "updated": now.strftime("%Y-%m-%d %H:%M UTC"),
        "competitors": [{k: c[k] for k in ("title", "subs", "median_views", "long_videos_12m", "id")} for c in kept],
        "top_videos": top,
    }
    STATE.mkdir(exist_ok=True)
    (STATE / "research.json").write_text(json.dumps(data, indent=2))
    md = [f"# Competitor research — {data['updated']}", "",
          f"{len(kept)} competitor channels · ranked by **multiple** = views ÷ that channel's median (last 12 months, long videos only).", "",
          "## Top videos", "", "| # | Multiple | Views | Title | Channel |", "|---|---|---|---|---|"]
    for i, v in enumerate(top, 1):
        md.append(f"| {i} | {v['multiple']}x | {v['views']:,} | [{v['title'].replace('|', '/')}]({v['url']}) | {v['channel']} |")
    md += ["", "## Competitors", "", "| Channel | Subscribers | Median views | Long videos (12m) |", "|---|---|---|---|"]
    for c in kept:
        md.append(f"| [{c['title']}](https://www.youtube.com/channel/{c['id']}) | {c['subs']:,} | {c['median_views']:,} | {c['long_videos_12m']} |")
    (STATE / "research.md").write_text("\n".join(md) + "\n")
    log(f"saved state/research.md ({len(top)} outlier videos)")
    return data


def load():
    p = STATE / "research.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except ValueError:
            return None
    return None
