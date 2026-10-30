"""Turns timed scenes into a Remotion edit (props.json) and renders the final MP4.

Editing rules (documentary style):
- a new shot every ~3-5 s, cut points snapped to word starts
- scene changes: whip-pan or flash + whoosh;  inside a scene: crossfade or hard cut
- slow zoom / pan on every shot, punch-in zoom on numbers
- word-by-word highlighted captions, headline lower-thirds, chapter cards
- stat / timeline / comparison graphics, progress bar with chapter marks
- background music ducked under the voice
"""
import json
import os
import random
import re
import shutil
import subprocess
from pathlib import Path

from . import character
from .config import FONTS, MUSIC, ROOT

REMOTION = ROOT / "remotion"
PUBLIC = REMOTION / "public"
RUN = PUBLIC / "run"
FPS = 30
CHAPTER_CARD = 2.2


def log(msg):
    print(f"[edit] {msg}", flush=True)


def _probe_duration(path: str) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
                           capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _place(src: str, name: str) -> str:
    """Puts a file into remotion/public/run and returns its public path."""
    RUN.mkdir(parents=True, exist_ok=True)
    dst = RUN / name
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy(src, dst)
    return f"run/{name}"


def _make_sfx():
    sfx = PUBLIC / "sfx"
    sfx.mkdir(parents=True, exist_ok=True)
    whoosh, hit = sfx / "whoosh.wav", sfx / "hit.wav"
    if not whoosh.exists():
        # filtered noise sweep = whoosh (generated, so no licensing issues)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=0.7:c=pink:a=0.9",
                        "-af", "highpass=f=300,lowpass=f=5000,afade=t=in:st=0:d=0.28,afade=t=out:st=0.3:d=0.4,volume=1.4",
                        "-ar", "48000", "-ac", "2", str(whoosh)], check=True)
    if not hit.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=55:d=0.9",
                        "-af", "afade=t=out:st=0.05:d=0.85,volume=2.2,lowpass=f=200",
                        "-ar", "48000", "-ac", "2", str(hit)], check=True)
    return "sfx/whoosh.wav", "sfx/hit.wav"


def _fonts():
    dst = PUBLIC / "fonts"
    dst.mkdir(parents=True, exist_ok=True)
    for f in ("Anton-Regular.ttf", "Poppins-Bold.ttf", "Poppins-ExtraBold.ttf"):
        if not (dst / f).exists():
            shutil.copy(FONTS / f, dst / f)


# ---------------------------------------------------------------- words

def _scene_words(sc):
    """Real word timings from Whisper if available, else an even spread over the scene's speech."""
    if sc.get("words"):
        return [{"w": w, "s": float(s), "e": float(e)} for w, s, e in sc["words"]]
    ws = sc["narration"].split()
    s0, s1 = sc["speech_start"], sc["speech_end"]
    total = sum(len(w) + 1 for w in ws) or 1
    out, acc = [], 0
    for w in ws:
        a = s0 + acc / total * (s1 - s0)
        acc += len(w) + 1
        out.append({"w": w, "s": a, "e": s0 + acc / total * (s1 - s0)})
    return out


def _pages(words):
    pages, cur = [], []
    for w in words:
        cur.append(w)
        text = " ".join(x["w"] for x in cur)
        if len(cur) >= 5 or len(text) > 26 or w["w"][-1:] in ".!?;:," and len(cur) >= 2:
            pages.append(cur)
            cur = []
    if cur:
        pages.append(cur)
    out = []
    for i, p in enumerate(pages):
        s = p[0]["s"]
        nxt = pages[i + 1][0]["s"] if i + 1 < len(pages) else p[-1]["e"] + 0.4
        e = min(nxt, p[-1]["e"] + 0.6)
        clean = [{"w": re.sub(r"[,.;:]+$", "", x["w"]).replace('"', ""), "s": x["s"], "e": x["e"]} for x in p]
        out.append({"s": s, "e": max(e, s + 0.3), "words": clean})
    return out


def _speech(words, gap=0.35):
    iv = []
    for w in words:
        if iv and w["s"] - iv[-1][1] <= gap:
            iv[-1][1] = max(iv[-1][1], w["e"])
        else:
            iv.append([w["s"], w["e"]])
    return iv


# ---------------------------------------------------------------- shots

def _cut_points(start, end, n, words):
    """n shots inside [start, end], each cut moved to the nearest word start."""
    if n <= 1:
        return [start, end]
    pts = [start]
    for k in range(1, n):
        target = start + (end - start) * k / n
        cands = [w["s"] for w in words if start + 1.5 < w["s"] < end - 1.5]
        best = min(cands, key=lambda s: abs(s - target)) if cands else target
        if best - pts[-1] >= 1.6:
            pts.append(best)
    pts.append(end)
    return pts


def _cap_segments(pts, max_len):
    """Splits any segment longer than max_len into equal parts, so no shot runs longer than max_len."""
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        parts = max(1, -(-int((b - a) * 1000) // int(max_len * 1000)))
        for j in range(1, parts):
            out.append(a + (b - a) * j / parts)
        out.append(b)
    return out


def build_props(cfg, scenes, script, narration_wav, total):
    for p in (RUN,):
        shutil.rmtree(p, ignore_errors=True)
    RUN.mkdir(parents=True, exist_ok=True)
    _fonts()
    whoosh, hit = _make_sfx()
    rnd = random.Random(script.get("title", ""))
    max_shot = min(float(cfg.get("shot_seconds", 4)), 4.0)  # hard limit: no shot longer than 4 s
    shot_len = max_shot - 0.5                                  # aim for ~3.5 s shots

    all_words, shots, headlines, graphics, sfx, punches, chapters = [], [], [], [], [], [], []
    history = []
    past_clips = []
    placed = {}
    motions = ["in", "left", "out", "right"]
    last_chapter = None

    # "company card" (Nation Inc.): shown right after the chapter-2 card
    card = None
    c = script.get("card")
    if c and c.get("rows"):
        first2 = next((sc for sc in scenes if sc.get("chapter") and sc["chapter"] != scenes[0].get("chapter")), None)
        cs = (first2["start"] + CHAPTER_CARD + 0.3) if first2 else 2.0
        card = {"name": c["name"], "rows": c["rows"], "s": round(cs, 3), "e": round(cs + 6.5, 3),
                "flag": _place(c["flag"], "flag.png") if c.get("flag") else None}
        sfx.append({"src": hit, "at": cs, "volume": 0.4})

    for i, sc in enumerate(scenes):
        words = _scene_words(sc)
        all_words += words
        s0, s1 = sc["start"], sc["end"]

        # chapter cards
        if sc.get("chapter") and sc["chapter"] != last_chapter:
            chapters.append({"name": sc["chapter"], "s": s0 if i else 0.0, "index": len(chapters) + 1})
            if i:
                sfx.append({"src": hit, "at": s0, "volume": 0.5})
            last_chapter = sc["chapter"]
        card_until = s0 + CHAPTER_CARD if chapters and chapters[-1]["s"] == s0 and i else s0

        # shots
        assets = [a for a in (sc.get("shots") or ([sc["asset"]] if sc.get("asset") else [])) if a and a.get("path")]
        n = max(1, -(-int((s1 - s0) * 1000) // int(shot_len * 1000)))
        pts = _cap_segments(_cut_points(s0, s1, n, words), max_shot)
        for k in range(len(pts) - 1):
            a = assets[k % len(assets)] if assets else None
            if a and len(assets) == 1 and k % 2 == 1 and past_clips:
                a = past_clips[-1 - (k // 2) % min(3, len(past_clips))]  # alternate with recent clips, don't repeat one
            if not a:
                continue
            if a["path"] not in placed:
                ext = ".mp4" if a["type"] == "video" else Path(a["path"]).suffix or ".jpg"
                placed[a["path"]] = (_place(a["path"], f"a{len(placed):03d}{ext}"),
                                     _probe_duration(a["path"]) if a["type"] == "video" else 0)
            src, clip_len = placed[a["path"]]
            seg = pts[k + 1] - pts[k]
            shot = {"src": src, "type": a["type"], "start": round(pts[k], 3), "end": round(pts[k + 1], 3),
                    "motion": motions[(len(shots)) % 4]}
            if a["type"] == "video":
                room = clip_len - seg - 0.3
                if room > 0:
                    shot["trim"] = round(rnd.uniform(0, min(room, 8)), 2)
                    shot["rate"] = 1
                else:
                    shot["trim"] = 0
                    shot["rate"] = round(max(0.5, min(1, (clip_len - 0.2) / seg)), 3) if clip_len else 1
            if a.get("credit_on_screen"):
                shot["credit"] = a["credit_on_screen"]
            if k == 0 and i > 0:
                shot["transition"] = "flash" if i % 3 == 0 else "whip"
                sfx.append({"src": whoosh, "at": max(0, pts[k] - 0.25), "volume": 0.32})
            else:
                shot["transition"] = "fade" if k % 2 else "cut"
            shots.append(shot)
        for a in assets:
            if a not in past_clips:
                past_clips.append(a)

        # graphic (timed to when its number/year is spoken)
        g = sc.get("graphic")
        g_start = None
        if isinstance(g, dict) and g.get("type") == "chart":
            ser = (script.get("series") or {}).get(str(g.get("metric") or ""))
            gs = max(card_until + 0.2, s0 + 0.8)
            ge = min(gs + 5.5, s1 - 0.1)
            if ser and ge - gs >= 2.5 and not (card and gs < card["e"] and ge > card["s"]):
                graphics.append({"type": "chart", "s": round(gs, 3), "e": round(ge, 3), **ser})
                g_start = gs
                sfx.append({"src": hit, "at": gs, "volume": 0.3})
            g = None
        if isinstance(g, dict) and g.get("type") in ("stat", "timeline", "compare"):
            key = re.sub(r"[^0-9]", "", str(g.get("value") or g.get("year") or ""))[:4]
            hit_w = next((w for w in words if key and key in re.sub(r"[^0-9]", "", w["w"])), None)
            gs = max(card_until + 0.2, (hit_w["s"] - 0.2) if hit_w else s0 + 1.0)
            ge = min(gs + 4.2, s1 - 0.1)
            if ge - gs >= 2.0 and not (card and gs < card["e"] and ge > card["s"]):
                item = {"type": g["type"], "s": round(gs, 3), "e": round(ge, 3)}
                try:
                    if g["type"] == "stat":
                        item.update(value=str(g["value"])[:14], label=str(g.get("label", ""))[:60])
                    elif g["type"] == "timeline":
                        item.update(year=str(g["year"])[:9], label=str(g.get("label", ""))[:48], history=list(history))
                        history.append({"year": item["year"], "label": item["label"]})
                    else:
                        item.update(title=str(g.get("title", ""))[:50], unit=str(g.get("unit", ""))[:4],
                                    a={"label": str(g["a"]["label"])[:14], "value": float(g["a"]["value"])},
                                    b={"label": str(g["b"]["label"])[:14], "value": float(g["b"]["value"])})
                    graphics.append(item)
                    g_start = gs
                    punches.append(gs)
                    sfx.append({"src": hit, "at": gs, "volume": 0.35})
                except (KeyError, TypeError, ValueError):
                    pass

        # headline lower-third (skip if a graphic covers the start of the scene)
        text = (sc.get("on_screen_text") or "").strip()
        hs = max(s0 + 0.25, card_until + 0.1)
        he = min(hs + 4.2, s1 - 0.2, (g_start - 0.1) if g_start else 1e9)
        if text and he - hs >= 1.5:
            headlines.append({"text": text[:40], "s": round(hs, 3), "e": round(he, 3)})

    # punch-ins on spoken numbers (max one every 6 s)
    for w in all_words:
        if re.search(r"\d|\$|percent|million|billion", w["w"], re.I):
            if not punches or min(abs(w["s"] - p) for p in punches) > 6:
                punches.append(w["s"])
    punches.sort()

    music = None
    tracks = [p for p in MUSIC.glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg")] if MUSIC.exists() else []
    if tracks:
        tr = rnd.choice(tracks)
        music = _place(str(tr), "music" + tr.suffix.lower())
        log(f"music: {tr.name}")

    try:
        char = character.build(cfg, scenes, total, graphics, chapters, narration_wav, _place)
    except Exception as e:
        log(f"mascot skipped: {e}")
        char = None

    props = {
        "card": card,
        "character": char,
        "fps": FPS,
        "durationInFrames": int(round(total * FPS)),
        "total": total,
        "channel": cfg.get("channel_name", ""),
        "narration": _place(str(narration_wav), "narration.wav"),
        "music": music,
        "musicVolume": float(cfg.get("music_volume", 0.14)),
        "duckVolume": float(cfg.get("music_duck_volume", 0.045)),
        "speech": _speech(all_words),
        "shots": shots,
        "pages": _pages(all_words),
        "headlines": headlines,
        "chapters": chapters,
        "graphics": graphics,
        "punches": punches,
        "sfx": sfx,
        "outroStart": max(0, total - 4.0),
    }
    log(f"{len(shots)} shots · {len(graphics)} graphics · {len(chapters)} chapters · {len(props['pages'])} caption pages")
    return props


def render(cfg, scenes, script, narration_wav, total, out_file: Path, work: Path):
    props = build_props(cfg, scenes, script, narration_wav, total)
    work.mkdir(parents=True, exist_ok=True)
    pfile = work / "props.json"
    pfile.write_text(json.dumps(props))
    cmd = ["npx", "remotion", "render", "src/index.ts", "Main", str(out_file.resolve()),
           f"--props={pfile.resolve()}", "--codec=h264", "--crf=20", "--audio-bitrate=192k",
           f"--concurrency={cfg.get('render_concurrency') or max(1, (os.cpu_count() or 2))}",
           "--timeout=120000", "--log=info", "--offthreadvideo-cache-size-in-bytes=1500000000"]
    if os.environ.get("REMOTION_BROWSER"):
        cmd.append(f"--browser-executable={os.environ['REMOTION_BROWSER']}")
    log("rendering with Remotion…")
    # Remotion prints a progress line for every few frames — tens of thousands of lines that make the
    # GitHub log page crash the browser. Show a short summary every 30 s and keep the tail for errors.
    import collections
    import time as _time
    tail = collections.deque(maxlen=120)
    last = 0.0
    proc = subprocess.Popen(cmd, cwd=REMOTION, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace", bufsize=1)
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        tail.append(line)
        noisy = ("Rendered" in line or "Encoded" in line or "Stitch" in line or "%" in line) and "rror" not in line
        if not noisy or _time.time() - last > 30:
            print(f"[remotion] {line[:300]}", flush=True)
            if noisy:
                last = _time.time()
    proc.wait()
    if proc.returncode != 0 or not out_file.exists():
        print("[remotion] ---- last lines ----\n" + "\n".join(tail), flush=True)
        raise RuntimeError("Remotion render failed (see log above).")
    log(f"done: {out_file} ({out_file.stat().st_size / 1e6:.1f} MB)")
    return out_file
