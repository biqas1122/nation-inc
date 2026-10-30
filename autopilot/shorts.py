"""4 vertical Shorts (1080x1920, 30-58 s) cut from each long video — for YouTube Shorts, TikTok, Reels, Facebook.

Gemini picks 4 self-contained, hooky moments from the script; each is re-rendered vertically with Remotion
(same footage, big captions, a hook title on top, Baron, and a "full story" call to action at the end).
Titles / captions / hashtags for every platform are appended to UPLOAD-KIT.txt.
"""
import json
import os
import subprocess
from pathlib import Path

from . import gemini
from .config import ROOT

REMOTION = ROOT / "remotion"
MIN_S, MAX_S = 25.0, 58.0


def log(msg):
    print(f"[shorts] {msg}", flush=True)


def _fallback(scenes, n):
    picks, i = [], 1
    while i < len(scenes) and len(picks) < n:
        j = i
        while j + 1 < len(scenes) and scenes[j + 1]["end"] - scenes[i]["start"] <= 45:
            j += 1
        picks.append({"from": i, "to": j, "hook": scenes[i].get("on_screen_text") or "", "title": "", "caption": "",
                      "hashtags": []})
        i = j + max(2, len(scenes) // n)
    return picks


def plan(cfg, scenes, title, n=4):
    lines = [f"{i}. ({sc['end'] - sc['start']:.0f}s) {sc['narration'][:220]}" for i, sc in enumerate(scenes)]
    try:
        res = gemini.generate_json(cfg["gemini_key"], f"""You cut viral Shorts from a long business documentary: "{title}".
Pick {n} DIFFERENT moments that work on their own for a viewer who never saw the long video.
Each moment is a range of consecutive scenes, {MIN_S:.0f}-{MAX_S:.0f} seconds in total (durations are given).
The FIRST scene of each range must open with a strong hook (surprising fact, big number, conflict); the range should end
on a satisfying point. Spread them across the story; never overlap.
For each also write:
- "hook": 3-7 word on-screen hook title (big text at the top), e.g. "THEY SOLD WATER FOR $1.4B"
- "title": YouTube Shorts title under 60 chars (curiosity, honest)
- "caption": 1-2 sentence caption for TikTok/Instagram/Facebook ending with a question
- "hashtags": 5 relevant hashtags (include #shorts, #business)

SCENES:
{chr(10).join(lines)}

Return JSON: {{"shorts":[{{"from":0,"to":0,"hook":"","title":"","caption":"","hashtags":[]}}]}}""", temperature=0.6)
        picks = [p for p in res.get("shorts", []) if isinstance(p, dict)]
    except Exception as e:
        log(f"Gemini pick failed ({e}) — using simple picks")
        picks = []
    out, used = [], set()
    for p in picks:
        try:
            a, b = int(p["from"]), int(p["to"])
        except (KeyError, TypeError, ValueError):
            continue
        a, b = max(0, a), min(len(scenes) - 1, max(a, b))
        while b > a and scenes[b]["end"] - scenes[a]["start"] > MAX_S:
            b -= 1
        while b + 1 < len(scenes) and scenes[b]["end"] - scenes[a]["start"] < MIN_S:
            b += 1
        if scenes[b]["end"] - scenes[a]["start"] > MAX_S + 4 or any(k in used for k in range(a, b + 1)):
            continue
        used.update(range(a, b + 1))
        out.append({**p, "from": a, "to": b})
    if len(out) < n:
        for p in _fallback(scenes, n):
            if len(out) >= n:
                break
            if not any(k in used for k in range(p["from"], p["to"] + 1)):
                used.update(range(p["from"], p["to"] + 1))
                out.append(p)
    return out[:n]


def _shift(items, t0, t1, keys=("s", "e")):
    out = []
    for it in items:
        a, b = it[keys[0]], it[keys[1]]
        if b <= t0 or a >= t1:
            continue
        x = dict(it)
        x[keys[0]], x[keys[1]] = round(max(a, t0) - t0, 3), round(min(b, t1) - t0, 3)
        out.append(x)
    return out


def short_props(props, t0, t1, hook, cta):
    dur = t1 - t0
    shots = []
    for sh in props["shots"]:
        if sh["end"] <= t0 or sh["start"] >= t1:
            continue
        x = dict(sh)
        cut = max(0.0, t0 - sh["start"])
        x["start"], x["end"] = round(max(sh["start"], t0) - t0, 3), round(min(sh["end"], t1) - t0, 3)
        if x["type"] == "video":
            x["trim"] = round((sh.get("trim") or 0) + cut * (sh.get("rate") or 1), 3)
        if not shots:
            x["transition"] = "cut"
        shots.append(x)
    pages = []
    for pg in props["pages"]:
        if pg["e"] <= t0 or pg["s"] >= t1:
            continue
        pages.append({"s": round(max(pg["s"], t0) - t0, 3), "e": round(min(pg["e"], t1) - t0, 3),
                      "words": [{**w, "s": round(w["s"] - t0, 3), "e": round(w["e"] - t0, 3)} for w in pg["words"]]})
    ch = props.get("character")
    if ch:
        f0, f1 = int(round(t0 * 30)), int(round(t1 * 30))
        apps = [dict(a, tag=False) for a in _shift(ch["appearances"], t0, t1)]
        ch = {**ch, "appearances": apps, "level": ch["level"][f0:f1 + 1]}
    return {
        **props,
        "durationInFrames": int(round(dur * 30)),
        "total": round(dur, 3),
        "offset": round(t0, 3),
        "hook": hook,
        "cta": cta,
        "shots": shots,
        "pages": pages,
        "headlines": [],
        "chapters": [],
        "graphics": _shift(props["graphics"], t0, t1),
        "punches": [round(p - t0, 3) for p in props["punches"] if t0 <= p < t1],
        "sfx": [dict(s, at=round(s["at"] - t0, 3)) for s in props["sfx"] if t0 <= s["at"] < t1],
        "speech": [[round(max(a, t0) - t0, 3), round(min(b, t1) - t0, 3)] for a, b in props["speech"] if b > t0 and a < t1],
        "character": ch,
        "outroStart": dur + 10,
    }


def make(cfg, scenes, script, props_file: Path, out_dir: Path, name: str, count=None):
    """Renders the Shorts next to the long video and returns their info (for the upload kit)."""
    n = int(count or cfg.get("shorts_per_video", 4))
    if n <= 0:
        return []
    props = json.loads(Path(props_file).read_text())
    picks = plan(cfg, scenes, script["title"], n)
    channel = cfg.get("channel_name") or ""
    cta = "FULL STORY ON OUR CHANNEL" + (f" · {channel.upper()}" if channel else "")
    done = []
    for k, p in enumerate(picks, 1):
        t0 = max(0.0, scenes[p["from"]]["start"] - 0.05)
        t1 = scenes[p["to"]]["end"] + 0.3
        sp = short_props(props, t0, t1, str(p.get("hook") or "").upper()[:60], cta)
        pf = Path(props_file).with_name(f"short_{k}.json")
        pf.write_text(json.dumps(sp))
        out = out_dir / f"{name}-short-{k}.mp4"
        cmd = ["npx", "remotion", "render", "src/index.ts", "Short", str(out.resolve()), f"--props={pf.resolve()}",
               "--codec=h264", "--crf=21", "--audio-bitrate=160k",
               f"--concurrency={cfg.get('render_concurrency') or max(1, (os.cpu_count() or 2))}",
               "--timeout=120000", "--log=warn"]
        if os.environ.get("REMOTION_BROWSER"):
            cmd.append(f"--browser-executable={os.environ['REMOTION_BROWSER']}")
        log(f"short {k}/{len(picks)}: {t1 - t0:.0f}s — {p.get('hook')}")
        r = subprocess.run(cmd, cwd=REMOTION, capture_output=True, text=True)
        if r.returncode != 0 or not out.exists():
            log(f"short {k} failed: {(r.stderr or r.stdout)[-600:]}")
            continue
        done.append({"file": out.name, "seconds": round(t1 - t0), "hook": p.get("hook", ""),
                     "title": p.get("title") or p.get("hook", ""), "caption": p.get("caption", ""),
                     "hashtags": p.get("hashtags") or ["#shorts", "#business"]})
    return done


def kit_text(done, cfg=None):
    """Shorts section of the upload kit, with a posting plan: long video + 2 Shorts today, 2 Shorts tomorrow."""
    if not done:
        return ""
    import datetime as dt
    from zoneinfo import ZoneInfo
    tz = ZoneInfo((cfg or {}).get("timezone", "Asia/Karachi"))
    d0 = dt.datetime.now(tz).date()
    d1 = d0 + dt.timedelta(days=1)
    day = lambda d: d.strftime("%a %d %b")  # noqa: E731
    slots = [(d0, "9:30 PM"), (d0, "11:30 PM"), (d1, "7:00 PM"), (d1, "10:00 PM")]
    lines = ["", "=" * 60, "SHORTS / TIKTOK / REELS / FACEBOOK (vertical clips in this release)", "=" * 60, "",
             "POSTING PLAN (Pakistan time — evening here = daytime in the USA/UK):",
             f"   {day(d0)} 9:00 PM  →  LONG VIDEO (publish this first)"]
    for k, d in enumerate(done):
        dd, tm = slots[min(k, len(slots) - 1)]
        lines.append(f"   {day(dd)} {tm}  →  SHORT {k + 1}")
    lines += ["   (In YouTube Studio use 'Schedule' so the assistant can upload everything at once.)",
              "   On every YouTube Short: Studio → Short → 'Related video' → pick today's LONG video,",
              "   so viewers can tap through to the full story. TikTok/Instagram/Facebook: same times."]
    for k, d in enumerate(done, 1):
        tags = " ".join(h if str(h).startswith("#") else f"#{h}" for h in d["hashtags"])
        lines += ["", f"SHORT {k}: {d['file']} ({d['seconds']}s)",
                  f"   Title (YouTube Shorts): {d['title']}",
                  f"   Caption (TikTok / Instagram / Facebook): {d['caption']} {tags}"]
    return "\n".join(lines)
