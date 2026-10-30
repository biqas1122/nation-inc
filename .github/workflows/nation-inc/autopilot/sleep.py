"""Sleep documentary format: 45-60 minute calm narration over slow, dim Ken-Burns stills.

Pipeline (one video):
  outline + chapters (Gemini)  →  calm narration (Gemini voice, falls back to free Edge voice)
  →  2-3 pictures per minute (Wikimedia Commons paintings / archive photos, then Pixabay)
  →  ffmpeg: every picture becomes a slow zoom/pan clip (rendered in parallel), clips are joined
  →  narration + soft rain ambience (+ very quiet music) mixed under it
  →  thumbnail + UPLOAD-KIT.txt (titles, description with chapters, tags)
No Remotion / captions here: sleep videos must be dark, slow and quiet — and this keeps a 1-hour render fast.
"""
import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import commons, gemini, seo, stock, voice
from .config import FONTS, MUSIC, OUT, WORK
from .thumbnail import make_thumbnail

FPS = 24
W, H = 1920, 1080


def log(msg):
    print(f"[sleep] {msg}", flush=True)


def fmt_time(sec):
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ------------------------------------------------------------------ script

def write_script(cfg, title, angle=""):
    key = cfg["gemini_key"]
    minutes = float(cfg.get("video_minutes", 50))
    wpm = float(cfg.get("sleep_wpm", 130))
    target = int(minutes * wpm)
    n_ch = max(6, min(16, round(minutes / 4.5)))
    style = cfg.get("sleep_style", "a calm, cosy bedtime history documentary")

    outline = gemini.generate_json(key, f"""Plan {style} for YouTube — the kind people put on to fall asleep.

TOPIC: {title}
{f'ANGLE: {angle}' if angle else ''}
AUDIENCE: English-speaking adults (USA/UK/Canada/Australia) who want to learn something gentle while drifting off.
TOTAL LENGTH: about {target} words of narration (≈{minutes:g} minutes at a slow pace).

Make exactly {n_ch} chapters. Chapter 1 is a soft welcome: invite the listener to get comfortable, dim the lights,
and say what tonight's story is about — no hype, no "smash the like button". The last chapter winds down slowly and
ends with a quiet goodnight. In between: a calm chronological journey with rich, well-documented details (daily
life, places, people, how things worked). Nothing scary, no cliffhangers, no violence described in detail.
For each chapter give 3-5 "beats" (the facts it covers), a word budget (all budgets add up to about {target}), and
6-8 "pictures": concrete, searchable subjects for calm historical paintings, engravings, maps, old photographs or
landscapes that match the chapter (e.g. "Venice Grand Canal painting 18th century", "medieval monastery library",
"Roman aqueduct", "old harbour at night painting"). Real places/objects, not abstract ideas.

Also return:
- "title": final YouTube title (<70 chars), calm and inviting, e.g. "The Entire History of Venice | Relaxing History to Fall Asleep To"
- "description": 2 short SEO paragraphs (no timestamps, no hashtags)
- "tags": 12-15 SEO tags
- "thumbnail_text": 2-5 calm words for the thumbnail
- "thumbnail_picture": 1 searchable subject for a beautiful dim painting/photo for the thumbnail

Return JSON: {{"title":"","description":"","tags":[],"thumbnail_text":"","thumbnail_picture":"",
"chapters":[{{"name":"","beats":[""],"words":0,"pictures":[""]}}]}}""", temperature=0.8)

    chapters = [c for c in outline.get("chapters", []) if isinstance(c, dict) and c.get("name")]
    if not chapters:
        raise RuntimeError("Gemini returned no chapters for the sleep script.")
    scenes, story_so_far = [], ""
    for i, ch in enumerate(chapters):
        words = int(ch.get("words") or target / len(chapters))
        beats = "\n".join(f"- {b}" for b in ch.get("beats", []))
        res = gemini.generate_json(key, f"""Write chapter {i + 1} of {len(chapters)} of {style}.
VIDEO: {outline.get('title') or title}
CHAPTER: {ch['name']}
COVER THESE BEATS:
{beats}
STORY SO FAR (do not repeat it): {story_so_far[-1200:] or 'this is the beginning'}

Write about {words} words of narration.
Voice: warm, slow, softly spoken storyteller. Long flowing sentences, gentle rhythm, vivid sensory details (sounds,
light, weather, textures). Third person, past tense for history. Accurate, well-established facts only — when unsure,
stay general instead of inventing names, numbers or dates. No questions to the viewer, no lists, no headings, no
"in this chapter", no cliffhangers, no exclamation marks. {'Begin with the soft welcome.' if i == 0 else ''}
{'End with a slow wind-down and a quiet goodnight.' if i == len(chapters) - 1 else ''}
Split into paragraphs of 3-5 sentences.

Return JSON: {{"paragraphs":["",""]}}""", temperature=0.75)
        paras = [str(p).strip() for p in (res.get("paragraphs") or []) if str(p).strip()]
        if not paras:
            raise RuntimeError(f"Gemini returned an empty chapter ({ch['name']}).")
        for p in paras:
            scenes.append({"chapter": ch["name"], "narration": p})
        story_so_far += f" [{ch['name']}] " + " ".join(p.split(". ")[0] for p in paras)
        log(f"chapter {i + 1}/{len(chapters)}: {ch['name']} ({sum(len(p.split()) for p in paras)} words)")

    tags = outline.get("tags") or []
    return {
        "title": str(outline.get("title") or title).strip(),
        "description": str(outline.get("description") or "").strip(),
        "tags": tags if isinstance(tags, list) else [t.strip() for t in str(tags).split(",") if t.strip()],
        "thumbnail_text": str(outline.get("thumbnail_text") or "").strip(),
        "thumbnail_picture": str(outline.get("thumbnail_picture") or "").strip(),
        "chapters": [{"name": c["name"], "pictures": [str(p) for p in (c.get("pictures") or [])][:10]} for c in chapters],
        "scenes": scenes,
    }


# ------------------------------------------------------------------ pictures

def _pictures_for(cfg, subjects, n, used, folder, tag):
    """n downloaded pictures for a chapter: Wikimedia Commons first (paintings/archive), then Pixabay photos."""
    got = []
    subjects = [s for s in subjects if s] or ["old landscape painting"]
    rounds = 0
    while len(got) < n and rounds < 3:
        for s in subjects:
            if len(got) >= n:
                break
            a = commons.search(s if rounds == 0 else f"{s} painting" if rounds == 1 else s.split()[0], used)
            if not a and cfg.get("pixabay_key") and rounds == 0:
                a = stock.find_photo(cfg, s)
                if a and a.get("url") in used:
                    a = None
            if not a:
                continue
            try:
                p = stock.download(a, folder / f"{tag}_{len(got):02d}")
                used.add(a.get("url"))
                a["path"] = str(p)
                got.append(a)
            except Exception as e:
                log(f"picture download failed: {e}")
        rounds += 1
    return got


# ------------------------------------------------------------------ render

def _segment(job):
    """One picture → a slow zoom/pan clip with gentle fades (and an optional chapter title)."""
    img, out, frames, move, title_file = job
    n = max(1, frames)
    dur = n / FPS
    if move == "in":
        z, x, y = f"1+0.10*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif move == "out":
        z, x, y = f"1.10-0.10*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif move == "left":
        z, x, y = "1.10", f"(iw-iw/zoom)*(1-on/{n})", "ih/2-(ih/zoom/2)"
    else:
        z, x, y = "1.10", f"(iw-iw/zoom)*on/{n}", "ih/2-(ih/zoom/2)"
    fade = min(1.6, dur / 3)
    vf = (f"scale=2560:1440:force_original_aspect_ratio=increase,crop=2560:1440,setsar=1,"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={W}x{H}:fps={FPS},"
          f"eq=brightness=-0.05:saturation=0.82,vignette=PI/4.5,"
          f"fade=t=in:st=0:d={fade:.2f},fade=t=out:st={dur - fade:.2f}:d={fade:.2f}")
    if title_file:
        font = str(FONTS / "Poppins-Bold.ttf")
        a = "if(lt(t,1.5),0,if(lt(t,3),(t-1.5)/1.5,if(lt(t,8),1,if(lt(t,9.5),(9.5-t)/1.5,0))))"
        vf += (f",drawtext=fontfile='{font}':textfile='{title_file}':fontsize=60:fontcolor=white:alpha='{a}':"
               f"x=(w-text_w)/2:y=h-220:shadowcolor=black@0.7:shadowx=3:shadowy=3")
    vf += ",format=yuv420p"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", img, "-vf", vf, "-frames:v", str(n), "-r", str(FPS),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-tune", "stillimage", "-an", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        # broken picture → plain dark frame so the timeline never breaks
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x0b0b0e:s={W}x{H}:r={FPS}",
                        "-frames:v", str(n), "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                        "-pix_fmt", "yuv420p", out], check=True)
    return out


def _ambience(total, out):
    """Soft rain-like ambience (generated, copyright-free)."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"anoisesrc=d={total + 1:.1f}:c=brown:a=0.6",
                    "-af", "highpass=f=80,lowpass=f=1400,volume=0.9", "-ar", "48000", "-ac", "2", str(out)], check=True)
    return out


def render(cfg, script, narration_wav, total, out_file):
    seg_dir = WORK / "segments"
    shutil.rmtree(seg_dir, ignore_errors=True)
    seg_dir.mkdir(parents=True)
    pic_dir = WORK / "pictures"
    pic_dir.mkdir(parents=True, exist_ok=True)
    scenes = script["scenes"]
    seg_len = float(cfg.get("sleep_seconds_per_picture", 22))

    # chapter spans from the narration timing
    spans = []
    for ch in script["chapters"]:
        idx = [i for i, s in enumerate(scenes) if s["chapter"] == ch["name"]]
        if idx:
            spans.append([ch, scenes[idx[0]]["start"], scenes[idx[-1]]["end"]])
    spans[0][1] = 0.0
    for a, b in zip(spans, spans[1:]):
        a[2] = b[1]
    spans[-1][2] = total

    used, jobs, moves, credits, marks = set(), [], ["in", "left", "out", "right"], [], []
    for ci, (ch, s, e) in enumerate(spans):
        n = max(1, round((e - s) / seg_len))
        pics = _pictures_for(cfg, ch.get("pictures", []), n, used, pic_dir, f"c{ci:02d}")
        if not pics and jobs:
            pics = [{"path": jobs[-1][0], "credit": ""}]
        log(f"chapter {ci + 1}: {len(pics)}/{n} pictures")
        marks.append((ch["name"], s))
        title_file = None
        if ci > 0:
            title_file = str(seg_dir / f"title_{ci:02d}.txt")
            Path(title_file).write_text(ch["name"], encoding="utf-8")
        for k in range(n):
            a = pics[k % len(pics)] if pics else None
            t0, t1 = s + (e - s) * k / n, s + (e - s) * (k + 1) / n
            frames = round(t1 * FPS) - round(t0 * FPS)
            img = a["path"] if a else ""
            jobs.append((img, str(seg_dir / f"s{len(jobs):04d}.mp4"), frames, moves[len(jobs) % 4],
                         title_file if k == 0 else None))
            if a and a.get("credit") and a["credit"] not in credits:
                credits.append(a["credit"])

    workers = max(1, os.cpu_count() or 2)
    log(f"rendering {len(jobs)} picture clips on {workers} cores…")
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(_segment, jobs))
    lst = seg_dir / "list.txt"
    lst.write_text("".join(f"file '{j[1]}'\n" for j in jobs))
    silent = WORK / "video_silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(silent)],
                   check=True)

    # audio: narration + soft ambience + (very quiet) calm music
    amb = _ambience(total, WORK / "ambience.wav")
    inputs = ["-i", str(silent), "-i", str(narration_wav), "-i", str(amb)]
    music_names = cfg.get("sleep_music") or ["reflective-lesson"]
    track = next((p for n_ in music_names for p in MUSIC.glob(f"{n_}*")), None) if MUSIC.exists() else None
    fc = (f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={cfg.get('narration_volume', 1.0)}[n];"
          f"[2:a]volume={cfg.get('ambience_volume', 0.10)}[r];")
    mix = "[n][r]"
    count = 2
    if track:
        inputs += ["-stream_loop", "-1", "-i", str(track)]
        fc += f"[3:a]aresample=48000,aformat=channel_layouts=stereo,volume={cfg.get('music_volume', 0.05)}[m];"
        mix += "[m]"
        count = 3
    fc += (f"{mix}amix=inputs={count}:duration=first:normalize=0,afade=t=in:st=0:d=3,"
           f"afade=t=out:st={max(0, total - 8):.2f}:d=8[a]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.2f}", "-movflags", "+faststart",
                    str(out_file)], check=True)
    log(f"done: {out_file} ({out_file.stat().st_size / 1e6:.0f} MB)")
    return credits, marks, jobs


# ------------------------------------------------------------------ produce

def produce(cfg, title, angle=""):
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    OUT.mkdir(exist_ok=True)

    log(f"Script: {title}")
    script = write_script(cfg, title, angle)
    scenes = script["scenes"]
    log(f"{len(script['chapters'])} chapters, {sum(len(s['narration'].split()) for s in scenes)} words")

    voice.LEAD, voice.GAP, voice.OUTRO = 3.0, float(cfg.get("sleep_pause", 1.4)), 15.0
    narration = WORK / "narration.wav"
    total = voice.narrate(cfg, scenes, narration)

    name = re.sub(r"[^a-z0-9]+", "-", script["title"].lower()).strip("-")[:60] or "sleep-video"
    video = OUT / f"{name}.mp4"
    credits, marks, jobs = render(cfg, script, narration, total, video)

    thumb = OUT / f"{name}-thumbnail.jpg"
    bg = None
    tp = script.get("thumbnail_picture")
    if tp:
        a = commons.search(tp, set()) or (stock.find_photo(cfg, tp) if cfg.get("pixabay_key") else None)
        if a:
            try:
                bg = str(stock.download(a, WORK / "thumb_bg"))
            except Exception as e:
                log(f"thumbnail picture failed: {e}")
    if not bg:
        bg = next((j[0] for j in jobs if j[0]), None)
    make_thumbnail(bg, script.get("thumbnail_text") or script["title"], cfg.get("channel_name", ""), thumb)

    ok = [marks[0]] if marks else []
    for n_, t in marks[1:]:
        if t - ok[-1][1] >= 10:
            ok.append((n_, t))
    chapters_text = ("Chapters:\n" + "\n".join(f"{fmt_time(t)} {n_}" for n_, t in ok)) if len(ok) >= 3 else ""
    credit_txt = ("Pictures (Wikimedia Commons, free licenses / Pixabay):\n" + "\n".join(credits[:40])) if credits \
        else "Pictures: Wikimedia Commons / Pixabay."
    credit_txt += "\nNarration and ambience made for this channel. For relaxation and educational purposes."
    kit = seo.build(cfg, script, chapters_text, credit_txt, fmt_time(total))
    seo.write_kit(OUT / "UPLOAD-KIT.txt", kit, fmt_time(total), thumb.name)
    meta = {"title": kit["titles"][0], "description": kit["description"], "tags": kit["tags"], "duration": total}
    (WORK / "script.json").write_text(json.dumps({**meta, "script": script}, indent=2, default=str))
    log(f"ready: {meta['title']} ({fmt_time(total)})")
    return video, thumb, meta
