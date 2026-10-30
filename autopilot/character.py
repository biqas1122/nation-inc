"""Baron — the channel's mascot (a black-bear Wall Street CEO) who co-hosts every video.

Images live in the repo folder  character/  (or characters/), one PNG per pose, e.g.
    neutral.png  pointing.png  shocked.png  thinking.png  laughing.png  facepalm.png
    money.png    thumbsup.png  serious.png  presenting.png  narrating.png
Optional mouth variants for lip-flap:  neutral_talk.png (mouth open)  or  neutral_closed.png (mouth closed).
Names are forgiving: "shocked.png.png", "Shocked.PNG", "narrateing.png" all work.
White / fake-checkerboard backgrounds are removed automatically.

What it does in a video:
- Baron slides in at the bottom-right on the intro, chapter starts and dramatic moments (Gemini picks the
  pose and an occasional short speech-bubble line), bobs while the narrator talks and flaps his mouth with
  the voice when a talk/closed image pair exists.
- He is also placed on the thumbnail.
"""
import os
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import gemini
from .config import ROOT

DIRS = [ROOT / "character", ROOT / "characters"]
POSES = ["neutral", "narrating", "pointing", "presenting", "thinking", "serious",
         "shocked", "laughing", "facepalm", "money", "thumbsup"]
REACTIONS = {"shocked", "laughing", "facepalm", "money", "thumbsup"}
ALIASES = {"narrateing": "narrating", "narrate": "narrating", "talking": "narrating", "talk": "narrating",
           "thumbs_up": "thumbsup", "thumbup": "thumbsup", "present": "presenting", "point": "pointing",
           "think": "thinking", "laugh": "laughing", "shock": "shocked", "face_palm": "facepalm",
           "explaining": "neutral", "idle": "neutral", "cash": "money", "angry": "serious", "stern": "serious"}
FPS = 30
_CLEAN = ROOT / "work" / "character"
LAST = {"thumbnail_pose": None}


def log(msg):
    print(f"[character] {msg}", flush=True)


# ------------------------------------------------------------------ files

def _parse(name: str):
    """'Shocked.png.png' → ('shocked', None);  'neutral_talk.png' → ('neutral', 'open')."""
    n = name.lower()
    while True:
        stem, ext = os.path.splitext(n)
        if ext in (".png", ".jpg", ".jpeg", ".webp"):
            n = stem
        else:
            break
    n = re.sub(r"[^a-z_]", "", n.replace("-", "_").replace(" ", "_")).strip("_")
    variant = None
    for suf, v in (("_closed", "closed"), ("closed", "closed"), ("_talk", "open"), ("_open", "open"), ("talk", "open")):
        if n.endswith(suf) and n != suf:
            n, variant = n[: -len(suf)].rstrip("_"), v
            break
    n = ALIASES.get(n, n)
    if n not in POSES and len(n) >= 4:
        n = next((p for p in POSES if n.startswith(p[:5]) or p.startswith(n[:5])), n)
    return (n if n in POSES else None), variant


def find():
    """{pose: {"closed": path, "open": path}} for every pose image in the repo."""
    raw = {}
    for d in DIRS:
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if not f.is_file() or f.stat().st_size < 1000:
                continue
            pose, variant = _parse(f.name)
            if pose:
                raw.setdefault(pose, {})[variant or "plain"] = f
    out = {}
    for pose, v in raw.items():
        plain, closed, open_ = v.get("plain"), v.get("closed"), v.get("open")
        if plain and closed and not open_:
            open_ = plain
        if plain and open_ and not closed:
            closed = plain
        closed = closed or plain or open_
        open_ = open_ or plain or closed
        out[pose] = {"closed": closed, "open": open_}
    return out


def clean(src: Path, dst: Path, height: int = 760) -> Path:
    """Transparent background (removes white / checkerboard), trimmed and resized."""
    im = Image.open(src).convert("RGBA")
    a = np.array(im)
    w, h = im.size
    corners = [a[0, 0, 3], a[0, w - 1, 3], a[h - 1, 0, 3], a[h - 1, w - 1, 3]]
    if min(corners) > 200:  # background is not transparent → flood-fill light pixels from the edges
        rgb = im.convert("RGB")
        key = (255, 0, 255)
        seeds = [(x, 0) for x in range(0, w, 24)] + [(x, h - 1) for x in range(0, w, 24)] + \
                [(0, y) for y in range(0, h, 24)] + [(w - 1, y) for y in range(0, h, 24)]
        for sx, sy in seeds:
            r, g, b = rgb.getpixel((sx, sy))
            if (r, g, b) != key and min(r, g, b) > 170 and max(r, g, b) - min(r, g, b) < 30:
                ImageDraw.floodfill(rgb, (sx, sy), key, thresh=170)
        m = np.array(rgb)
        bgmask = (m[:, :, 0] == 255) & (m[:, :, 1] == 0) & (m[:, :, 2] == 255)
        alpha = np.where(bgmask, 0, 255).astype("uint8")
        alpha_img = Image.fromarray(alpha, "L").filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
        im.putalpha(alpha_img)
    bbox = im.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    if bbox:
        im = im.crop(bbox)
    if im.height > height:
        im = im.resize((int(im.width * height / im.height), height), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "PNG", optimize=True)
    return dst


def prepared():
    """Cleans every pose image once per run → {pose: {"closed": Path, "open": Path}}."""
    found = find()
    out = {}
    for pose, v in found.items():
        try:
            c = clean(v["closed"], _CLEAN / f"{pose}_closed.png")
            o = c if v["open"] == v["closed"] else clean(v["open"], _CLEAN / f"{pose}_open.png")
            out[pose] = {"closed": c, "open": o}
        except Exception as e:
            log(f"{pose}: image skipped ({e})")
    return out


# ------------------------------------------------------------------ direction

def _fallback_plan(scenes, poses):
    talk = [p for p in ("neutral", "narrating", "pointing", "presenting", "thinking", "serious") if p in poses] or list(poses)
    plan = []
    for i, sc in enumerate(scenes):
        txt = sc.get("narration", "").lower()
        pose = talk[i % len(talk)]
        if re.search(r"billion|million|\$|profit|revenue|money|cash", txt) and "money" in poses:
            pose = "money"
        elif re.search(r"shock|crash|collapse|bankrupt|disaster|never|insane|unbelievable", txt) and "shocked" in poses:
            pose = "shocked"
        elif re.search(r"mistake|fail|wrong|blunder", txt) and "facepalm" in poses:
            pose = "facepalm"
        show = i == 0 or pose in REACTIONS or i % 3 == 0
        plan.append({"show": show, "pose": pose, "bubble": ""})
    return plan, ("shocked" if "shocked" in poses else talk[0])


def direct(cfg, scenes, poses, name):
    """Asks Gemini where Baron appears, which pose, and a few short speech-bubble lines."""
    avail = list(poses)
    lines = []
    for i, sc in enumerate(scenes):
        ch = " [CHAPTER START]" if i == 0 or sc.get("chapter") != scenes[i - 1].get("chapter") else ""
        lines.append(f"{i}.{ch} {sc.get('narration', '')[:170]}")
    try:
        res = gemini.generate_json(cfg["gemini_key"], f"""You direct {name}, the mascot co-host of a business documentary
YouTube channel: an authoritative black-bear Wall Street CEO in a navy suit with gold tie and glasses. Smart, confident,
dry humour — never childish. He pops up in the bottom corner of the video to react to the story.

Available poses: {", ".join(avail)}
Reaction poses (use on the matching dramatic beat only): {", ".join(p for p in avail if p in REACTIONS)}

For EVERY numbered scene below decide:
- "show": true for about 35-45% of scenes — always scene 0, every [CHAPTER START], and the most dramatic,
  surprising, funny or money moments. Never more than 3 scenes in a row.
- "pose": the pose that fits that moment best (talking poses for normal explaining).
- "bubble": a short witty reaction line for a speech bubble (2-6 words, e.g. "Bold move.", "That aged badly.",
  "Wait... HOW much?") on only about 1 in 4 shown scenes; otherwise "". Never repeat a line. No profanity.
Also pick "thumbnail_pose": the pose that would make the strongest YouTube thumbnail for this story.

SCENES:
{chr(10).join(lines)}

Return JSON: {{"scenes":[{{"i":0,"show":true,"pose":"","bubble":""}}],"thumbnail_pose":""}}""", temperature=0.7)
        by_i = {int(x.get("i", -1)): x for x in res.get("scenes", []) if isinstance(x, dict)}
        plan = []
        for i in range(len(scenes)):
            x = by_i.get(i, {})
            pose = x.get("pose") if x.get("pose") in poses else None
            plan.append({"show": bool(x.get("show")) and bool(pose), "pose": pose or avail[0],
                         "bubble": str(x.get("bubble") or "").strip()[:40]})
        if plan:
            plan[0]["show"] = True
        tp = res.get("thumbnail_pose") if res.get("thumbnail_pose") in poses else None
        if sum(p["show"] for p in plan) >= max(2, len(plan) // 6):
            return plan, tp or ("shocked" if "shocked" in poses else avail[0])
        log("Gemini plan too thin, using simple rules")
    except Exception as e:
        log(f"Gemini direction failed ({e}), using simple rules")
    return _fallback_plan(scenes, poses)


# ------------------------------------------------------------------ voice level

def voice_levels(wav, total):
    """One digit (0-9) per video frame: how loud the narrator is → mouth open / bob."""
    from .align import _load_16k
    x = _load_16k(str(wav))
    hop = 16000 // FPS
    n = int(total * FPS) + 1
    rms = np.zeros(n, dtype="float32")
    for i in range(n):
        seg = x[i * hop:(i + 1) * hop]
        if len(seg):
            rms[i] = float(np.sqrt(np.mean(seg * seg)))
    ref = float(np.percentile(rms[rms > 0], 95)) if np.any(rms > 0) else 1.0
    lv = np.clip(rms / max(ref, 1e-6) * 9, 0, 9).astype(int)
    # natural mouth flap: close briefly every few frames even in long loud stretches
    run = 0
    for i in range(n):
        if lv[i] >= 3:
            run += 1
            if run % 5 == 0:
                lv[i] = 2
        else:
            run = 0
    return "".join(str(int(v)) for v in lv)


# ------------------------------------------------------------------ build props

def build(cfg, scenes, total, graphics, chapters, narration_wav, place):
    """Returns the Remotion 'character' prop, or None when no images are in the repo."""
    if cfg.get("character_enabled") is False:
        return None
    poses = prepared()
    if not poses:
        log("no character images found (folder 'character/') — video without mascot")
        return None
    name = str(cfg.get("character_name") or "Baron")
    log(f"{name}: {len(poses)} poses ({', '.join(sorted(poses))})")
    plan, thumb_pose = direct(cfg, scenes, poses, name)
    LAST["thumbnail_pose"] = thumb_pose

    public = {}
    for pose, v in poses.items():
        c = place(str(v["closed"]), f"char_{pose}_c.png")
        o = c if v["open"] == v["closed"] else place(str(v["open"]), f"char_{pose}_o.png")
        public[pose] = {"closed": c, "open": o}

    card_starts = {round(c["s"], 2) for c in chapters[1:]}
    blocked = [(g["s"] - 0.3, g["e"] + 0.2) for g in graphics]
    apps = []
    for i, (sc, p) in enumerate(zip(scenes, plan)):
        if not p["show"]:
            continue
        s = sc["start"] + (2.5 if round(sc["start"], 2) in card_starts else 0.25)
        e = min(sc["end"] - 0.05, s + (5.5 if p["pose"] in REACTIONS else 8.0), total - 4.2)
        for bs, be in blocked:
            if bs < e and be > s:
                if bs > s:
                    e = min(e, bs)
                else:
                    s = max(s, be)
        if e - s < 2.2:
            continue
        apps.append({"s": round(s, 3), "e": round(e, 3), "pose": p["pose"],
                     "bubble": p["bubble"] if e - s >= 3 else "", "enter": True, "exit": True, "tag": False})
    for a, b in zip(apps, apps[1:]):  # back-to-back appearances: stay on screen, just change pose
        if b["s"] - a["e"] < 0.9:
            a["exit"], b["enter"] = False, False
            a["e"] = b["s"]
    if apps:
        apps[0]["tag"] = True
    log(f"{name} appears {len(apps)} times, {sum(1 for a in apps if a['bubble'])} speech bubbles")
    return {"name": name, "poses": public, "appearances": apps, "level": voice_levels(narration_wav, total)}


# ------------------------------------------------------------------ thumbnail

def thumbnail_image():
    """Cleaned PNG of the best thumbnail pose (or None)."""
    found = find()
    if not found:
        return None
    pose = LAST.get("thumbnail_pose")
    pose = pose if pose in found else next((p for p in ("shocked", "pointing", "money", "serious", "neutral") if p in found),
                                           next(iter(found)))
    try:
        return clean(found[pose]["open"], _CLEAN / f"thumb_{pose}.png", height=1000)
    except Exception as e:
        log(f"thumbnail character failed: {e}")
        return None
