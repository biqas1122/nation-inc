"""Entry point.

  python -m autopilot.main plan            # make sure the calendar has upcoming topics (adds 30 when low)
  python -m autopilot.main run             # plan if needed, then produce + upload today's video
  python -m autopilot.main test --topic "How Nike Beat Adidas"   # render only, no sheet / upload
"""
import argparse
import os
import datetime as dt
import json
import shutil
import sys
import traceback
from zoneinfo import ZoneInfo

from . import align, commons, edit, notify, research, scriptgen, seo, stock, voice
from .config import OUT, WORK, load_config, require, save_sheet_id
from .thumbnail import frame_from_video, make_thumbnail


def log(msg):
    print(f"[autopilot] {msg}", flush=True)


def slug(s):
    import re
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "video"


def fmt_time(sec):
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def description_parts(script, scenes):
    """Returns (chapters text, credits text) for the YouTube description."""
    marks = []
    for sc in scenes:
        name = sc.get("chapter")
        if name and (not marks or marks[-1][0] != name):
            marks.append([name, sc["start"]])
    ok = []
    for name, t in marks:
        if not ok:
            ok.append([name, 0])
        elif t - ok[-1][1] >= 12:
            ok.append([name, t])
    chapters = ("Chapters:\n" + "\n".join(f"{fmt_time(t)} {n}" for n, t in ok)) if len(ok) >= 3 else ""
    allc = [a["credit"] for sc in scenes for a in (sc.get("shots") or []) if a]
    photos = list(dict.fromkeys(c for c in allc if "Wikimedia" in c))
    stockc = list(dict.fromkeys(c for c in allc if "Wikimedia" not in c))[:25]
    credits = ""
    if photos:
        credits += "Photos (Wikimedia Commons, free licenses):\n" + "\n".join(photos) + "\n\n"
    credits += "Stock footage: " + (", ".join(stockc) if stockc else "Pixabay") + "."
    credits += "\nThis video is for educational and commentary purposes. All trademarks belong to their respective owners."
    return chapters, credits


# ---------------- produce one video ----------------

def produce(cfg, title, angle=""):
    if cfg.get("format") == "sleep":
        from . import sleep
        return sleep.produce(cfg, title, angle)
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    OUT.mkdir(exist_ok=True)

    log(f"Script: {title}")
    facts = None
    if cfg.get("format") == "nation":
        from . import nation
        facts = nation.prepare(cfg, title, WORK / "nation")
    script = scriptgen.generate_script(cfg, title, angle, facts=facts["sheet"] if facts else "",
                                       metrics=facts["metrics"] if facts else None)
    if facts:
        script["card"], script["series"], script["maps"] = facts["card"], facts["series"], facts.get("maps")
    scenes = script["scenes"]
    log(f"{len(scenes)} scenes, {sum(scriptgen.words(s['narration']) for s in scenes)} words")

    narration = WORK / "narration.wav"
    total = voice.narrate(cfg, scenes, narration)
    align.sync(cfg, scenes, str(narration))

    # several different, relevant clips per scene → a cut every few seconds
    used = set()
    shot_len = min(float(cfg.get("shot_seconds", 4)), 3.5)  # a new clip every 3-4 seconds
    n_assets = 0
    for i, sc in enumerate(scenes):
        dur = max(1.0, sc["end"] - sc["start"])
        want = max(1, min(12, -(-int(dur * 10) // int(shot_len * 10))))
        queries = sc.get("visual_queries") or [sc["visual_query"]]
        real = []
        if facts:
            # Nation Inc.: real photos of the actual country first (Wikimedia Commons: cities, landmarks,
            # ports, factories, leaders), stock video only fills the gaps
            for q in queries + ([sc["photo_subject"]] if sc.get("photo_subject") else []):
                if len(real) >= max(1, want // 2 + 1):
                    break
                ph = commons.search(q, used)
                if ph:
                    try:
                        stock.download(ph, WORK / f"real_{i:03d}_{len(real)}")
                        real.append(ph)
                    except Exception as e:
                        log(f"scene {i + 1} photo download failed: {e}")
        try:
            shots = stock.find_shots(cfg, queries, max(0, want - len(real)), used) if want > len(real) else []
        except Exception as e:
            log(f"scene {i + 1} footage search failed: {e}")
            shots = []
        ok = list(real)
        for j, a in enumerate(shots):
            try:
                stock.download(a, WORK / f"asset_{i:03d}_{j}")
                ok.append(a)
            except Exception as e:
                log(f"scene {i + 1} clip download failed: {e}")
        if ok and len(ok) < want:
            log(f"scene {i + 1}: only {len(ok)}/{want} relevant clips — longer shots")
        # a real photo of the subject (Wikimedia Commons) opens the scene when available
        if sc.get("photo_subject"):
            ph = commons.search(sc["photo_subject"], used)
            if ph:
                try:
                    stock.download(ph, WORK / f"photo_{i:03d}")
                    ok.insert(0, ph)
                except Exception as e:
                    log(f"scene {i + 1} photo download failed: {e}")
        sc["shots"] = ok
        sc["asset"] = ok[0] if ok else None
        n_assets += len(ok)
    if facts and facts.get("map") and not facts.get("maps") and len(scenes) > 1:
        scenes[1].setdefault("shots", []).insert(0, {"type": "photo", "path": facts["map"], "url": "map",
                                                     "credit": "Locator map: Wikimedia Commons",
                                                     "credit_on_screen": "Map: Wikimedia Commons"})
    for i, sc in enumerate(scenes):  # never leave a scene empty
        if not sc.get("shots"):
            prev = next((scenes[j]["shots"] for j in range(i - 1, -1, -1) if scenes[j].get("shots")), None) \
                or next((x["shots"] for x in scenes if x.get("shots")), None)
            sc["shots"] = prev[-1:] if prev else []
            sc["asset"] = sc["shots"][0] if sc["shots"] else None
            log(f"scene {i + 1}: no relevant footage found, reusing previous shot")
    log(f"footage ready: {n_assets} clips")

    name = slug(script["title"])
    video = OUT / f"{name}.mp4"
    edit.render(cfg, scenes, script, narration, total, video, WORK / "render")

    thumb = OUT / f"{name}-thumbnail.jpg"
    bg = facts.get("thumb_bg") if facts else None
    try:
        p = None if bg else stock.find_photo(cfg, script.get("thumbnail_query") or scenes[0]["visual_query"])
        if p:
            bg = str(stock.download(p, WORK / "thumb_bg"))
    except Exception as e:
        log(f"thumbnail photo failed: {e}")
    if not bg:
        first = next((s["asset"] for s in scenes if s.get("asset") and s["asset"].get("path")), None)
        if first and first["type"] == "video":
            bg = str(frame_from_video(first["path"], WORK / "thumb_frame.jpg"))
        elif first:
            bg = first["path"]
    make_thumbnail(bg, script.get("thumbnail_text") or script["title"], cfg.get("channel_name", ""), thumb)

    chapters, credits = description_parts(script, scenes)
    kit = seo.build(cfg, script, chapters, credits, fmt_time(total))
    seo.write_kit(OUT / "UPLOAD-KIT.txt", kit, fmt_time(total), thumb.name)
    log(f"SEO upload kit ready: {kit['titles'][0]}")
    try:
        from . import shorts
        made = shorts.make(cfg, scenes, script, WORK / "render" / "props.json", OUT, name)
        if made:
            with open(OUT / "UPLOAD-KIT.txt", "a", encoding="utf-8") as f:
                f.write(shorts.kit_text(made, cfg))
        log(f"{len(made)} shorts ready")
    except Exception as e:
        log(f"shorts skipped: {e}")
    meta = {"title": kit["titles"][0], "description": kit["description"], "tags": kit["tags"], "duration": total}
    (WORK / "script.json").write_text(json.dumps({**meta, "script": script}, indent=2, default=str))
    return video, thumb, meta


# ---------------- commands ----------------

def today(cfg):
    return dt.datetime.now(ZoneInfo(cfg.get("timezone", "Asia/Karachi"))).date()


def parse_date(s):
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(s.strip(), f).date()
        except (ValueError, AttributeError):
            pass
    return None


def google_ready(cfg):
    return all(cfg.get(k) for k in ("google_client_id", "google_client_secret", "google_refresh_token"))


def open_calendar(cfg):
    """Google Sheet when Google is connected, otherwise the calendar file in the GitHub repo."""
    if not google_ready(cfg):
        from .repo_calendar import RepoCalendar
        log("Google not connected yet — using the calendar in the GitHub repo (state/calendar.csv)")
        return None, RepoCalendar()
    from .google_apis import Calendar, creds
    c = creds(cfg)
    cal = Calendar(cfg, c)
    if cal.ensure():
        save_sheet_id(cal.id, cal.url)
        log(f"Created your content calendar sheet: {cal.url}")
        # move anything planned before Google was connected into the new sheet
        from .repo_calendar import RepoCalendar
        old = [r for r in RepoCalendar().rows() if r["status"] == "Planned"]
        if old:
            cal.append([{"date": r["date"], "title": r["title"], "angle": r["angle"], "notes": r["notes"]} for r in old])
            log(f"Moved {len(old)} planned topics from the repo calendar into the sheet")
    return c, cal


def plan(cfg, cal, force=False):
    """Keeps the calendar filled up to `plan_horizon_days` ahead (default 30) on the posting days."""
    rows = cal.rows()
    t = today(cfg)
    horizon = t + dt.timedelta(days=int(cfg.get("plan_horizon_days", 30)))
    post_days = set(cfg.get("post_days") or [0, 1, 2, 3, 4, 5, 6])   # 0 = Monday
    dates = [parse_date(r["date"]) for r in rows if parse_date(r["date"])]
    start = max([t] + [d + dt.timedelta(days=1) for d in dates])
    slots, d = [], start
    while d <= horizon:
        if d.weekday() in post_days:
            slots.append(d)
        d += dt.timedelta(days=1)
    if not slots and not force:
        log(f"Calendar already planned until {max(dates) if dates else t} — nothing to add.")
        return 0
    if not slots:
        return 0
    data = research.load()
    if data:
        log(f"Using competitor research from {data.get('updated')} ({len(data.get('top_videos', []))} proven videos)")
    log(f"Planning {len(slots)} topics for {slots[0]} → {slots[-1]}…")
    ideas = scriptgen.generate_ideas(cfg, len(slots), [r["title"] for r in rows], data)
    items = [{"date": slots[i].isoformat(), "title": idea["title"], "angle": idea["angle"],
              "notes": f"Inspired by: {idea['inspired_by']}" if idea.get("inspired_by") else ""}
             for i, idea in enumerate(ideas)]
    cal.append(items)
    log(f"Added {len(items)} topics to the calendar: {cal.url}")
    return len(items)


def do_research(cfg):
    require(cfg, "gemini_key", "youtube_api_key")
    data = research.run(cfg)
    _, cal = open_calendar(cfg)
    try:
        cal.write_research(data)
    except Exception as e:
        log(f"could not write Research tab: {e}")
    added = plan(cfg, cal)
    top = data.get("top_videos", [])[:3]
    lines = "\n".join(f"• {v['title']} ({v['multiple']}x, {v['channel']})" for v in top)
    notify.whatsapp(f"📊 Tube Autopilot research done: {len(data.get('competitors', []))} competitors analysed, "
                    f"{added} new topics planned.\nTop ideas right now:\n{lines}\n\nCalendar: {cal.url}")


def publish_time(cfg):
    tz = ZoneInfo(cfg.get("timezone", "Asia/Karachi"))
    hh, mm = (int(x) for x in str(cfg.get("publish_time", "21:00")).split(":"))
    now = dt.datetime.now(tz)
    when = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if when < now + dt.timedelta(minutes=20):
        when = now + dt.timedelta(minutes=30)
    return when


def run(cfg):
    from .google_apis import upload_video
    require(cfg, "gemini_key")
    require(cfg, "pexels_key" if cfg.get("stock_provider") == "pexels" else "pixabay_key")
    if cfg.get("voice_provider") == "elevenlabs":
        require(cfg, "elevenlabs_key")
    credentials, cal = open_calendar(cfg)
    plan(cfg, cal)

    t = today(cfg)
    rows = cal.rows()
    due = [r for r in rows if r["status"] == "Planned" and (parse_date(r["date"]) or t) <= t]
    due.sort(key=lambda r: (parse_date(r["date"]) or t, r["row"]))
    if not due:
        log("Nothing scheduled for today.")
        return
    item = due[0]
    stamp = lambda: dt.datetime.now(ZoneInfo(cfg.get("timezone", "Asia/Karachi"))).strftime("%Y-%m-%d %H:%M")  # noqa: E731
    cal.update(item["row"], status="Producing", notes="Working…", now=stamp())
    try:
        video, thumb, meta = produce(cfg, item["title"], item["angle"])
        if not google_ready(cfg):
            # YouTube not connected yet: the video is kept as a download on the GitHub run page
            run_url = "{}/{}/actions/runs/{}".format(os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
                                                    os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_RUN_ID", ""))
            cal.update(item["row"], status="Ready", link=run_url, notes="Download from Artifacts (7 days) and upload", now=stamp())
            notify.whatsapp(f"🎬 New video ready: {meta['title']} ({fmt_time(meta['duration'])}).\n"
                            f"Download the zip from Artifacts (kept 7 days) — video, thumbnail and UPLOAD-KIT.txt (title, description, tags, hashtags, thumbnail prompts):\n{run_url}")
            log("Video ready for download ✓")
            return
        when = publish_time(cfg)
        vid = upload_video(credentials, cfg, video, thumb, meta["title"], meta["description"], meta["tags"], when)
        note = (f"Scheduled for {when.strftime('%d %b %H:%M')} · {fmt_time(meta['duration'])}"
                if cfg.get("publish_mode", "private") == "scheduled" else f"{cfg.get('publish_mode')} · {fmt_time(meta['duration'])}")
        cal.update(item["row"], status="Uploaded", link=f"https://youtu.be/{vid}", notes=note, now=stamp())
        mode = cfg.get("publish_mode", "private")
        action = (f"It will go live automatically at {when.strftime('%d %b %H:%M')} unless you change it."
                  if mode == "scheduled" else "It is PRIVATE — watch it, then click Publish (or Schedule) in YouTube Studio.")
        notify.whatsapp(f"🎬 New video ready: {meta['title']}\nLength {fmt_time(meta['duration'])}.\n{action}\n"
                        f"Check & publish: https://studio.youtube.com/video/{vid}/edit")
        log("All done ✓")
    except Exception as e:
        cal.update(item["row"], status="Failed", notes=str(e)[:300], now=stamp())
        notify.whatsapp(f"⚠️ Tube Autopilot could not make today's video ({item['title']}).\nReason: {str(e)[:300]}\n"
                        "The topic is marked Failed in the calendar — set it back to Planned to retry.")
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "run", "test", "research"])
    ap.add_argument("--topic", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    try:
        if a.cmd == "plan":
            require(cfg, "gemini_key")
            _, cal = open_calendar(cfg)
            plan(cfg, cal, force=a.force)
        elif a.cmd == "research":
            do_research(cfg)
        elif a.cmd == "run":
            run(cfg)
        else:
            require(cfg, "gemini_key")
            require(cfg, "pexels_key" if cfg.get("stock_provider") == "pexels" else "pixabay_key")
            produce(cfg, a.topic or cfg.get("test_topic") or "How Nike Beat Adidas")
            log(f"Test render saved in {OUT} (download it from this run's Artifacts).")
    except SystemExit:
        raise
    except Exception as e:
        traceback.print_exc()
        print(f"\n::error::{e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
