"""Topic planning and documentary script writing."""
import json

from . import gemini


def words(text: str) -> int:
    return len((text or "").split())


DEFAULT_RULES = """- Real, well-documented companies, brands or founders only — stories verifiable from mainstream reporting.
- Mix formats across the month: rivalries, rise stories, collapses/failures, clever business models, comebacks, marketing/pricing genius. Do not put two similar topics on consecutive days.
- Prefer stories with proven audience demand (famous brands, dramatic turns, money lessons)."""


def generate_ideas(cfg: dict, count: int, avoid: list[str], research: dict | None = None) -> list[dict]:
    focus = cfg.get("plan_focus") or ""
    avoid_txt = ", ".join(f'"{t}"' for t in avoid[-150:]) or "none"
    proven = ""
    if research and research.get("top_videos"):
        lines = [f'- "{v["title"]}" ({v["channel"]}, {v["views"]:,} views, {v["multiple"]}x its channel median)'
                 for v in research["top_videos"][:60]]
        proven = ("\nPROVEN DEMAND — competitor videos from the last 12 months that beat their own channel's median "
                  "by the most (this is what the audience is clicking on right now):\n" + "\n".join(lines) + "\n"
                  "Use these to choose companies, story types and angles that are in demand. Do NOT copy their titles "
                  "or cover the exact same story with the same angle — find a fresh angle, a related company, a "
                  "follow-up, or a story the competitors have not told yet. At least half of the ideas should clearly "
                  "build on a proven pattern above.\n")
    prompt = f"""You are the head of content for a faceless YouTube channel.
NICHE: {cfg['niche']}
Format examples: {cfg.get("idea_examples") or '"How Nike Beat Adidas", "Why Quibi Failed in 6 Months", "How Costco Makes Money Selling Cheap Hot Dogs"'}.

Research and plan {count} long-form video topics for the next {count} days{f' with extra focus on: {focus}' if focus else ''}.
Rules:
{cfg.get("idea_rules") or DEFAULT_RULES}
- Titles: curiosity-driven, honest, under 70 characters.
- Do NOT repeat or closely resemble any of these existing titles: {avoid_txt}
{proven}

Return JSON: {{"ideas":[{{"title":"...","angle":"one sentence: the hook/thesis of the story","inspired_by":"competitor video title it builds on, or empty"}}]}}"""
    out = gemini.generate_json(cfg["gemini_key"], prompt, temperature=1.0)
    ideas = out.get("ideas", out) if isinstance(out, dict) else out
    seen = {t.lower() for t in avoid}
    clean = []
    for i in ideas:
        t = str(i.get("title", "")).strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            clean.append({"title": t, "angle": str(i.get("angle", "")).strip(),
                          "inspired_by": str(i.get("inspired_by", "") or "").strip()})
    return clean[:count]


def _clean_scene(s):
    qs = s.get("visual_queries") or []
    if isinstance(qs, str):
        qs = [q.strip() for q in qs.split(",")]
    qs = [str(q).strip() for q in qs if str(q).strip()]
    if s.get("visual_query"):
        qs.append(str(s["visual_query"]).strip())
    qs = list(dict.fromkeys(qs)) or ["business office"]
    return {
        "chapter": str(s.get("chapter", "")).strip(),
        "narration": str(s.get("narration", "")).strip(),
        "visual_queries": qs[:4],
        "visual_query": qs[0],
        "on_screen_text": str(s.get("on_screen_text", "")).strip(),
        "photo_subject": str(s.get("photo_subject") or "").strip(),
        "graphic": s.get("graphic") if isinstance(s.get("graphic"), dict) else None,
    }


STYLE = """STORY RULES
- Use concrete, well-documented facts (dates, names, decisions). Only use numbers you are confident are widely reported; otherwise describe qualitatively. Never invent quotes.
- Spoken English for a documentary voiceover, short punchy sentences, no headings, no stage directions, no emojis, no "welcome back".
VISUAL RULES (stock footage, so NO brand names, logos or real people in visual queries)
- "visual_queries": exactly 3 DIFFERENT stock-footage searches for what the narration is literally about, 1-2 concrete nouns each, e.g. ["running shoes", "athlete sprint", "shoe factory"]. Things a camera can film: objects, places, actions. Never abstract words (success, strategy, lesson, idea), never brand or person names.
- "on_screen_text": max 6 words headline (can include the brand name, a year, or a number).
- "photo_subject": the real, specific person, product, building or event this scene is about, as you would search it on Wikimedia Commons (e.g. "Phil Knight", "Air Jordan 1", "Nike World Headquarters"). Empty string if nothing specific.
- "graphic": null for most scenes. For about one scene in three, add ONE animated graphic, but ONLY for facts you are certain are widely reported, and the number/year must also be said in the narration:
    {"type":"stat","value":"$126M","label":"Air Jordan sales in year one"}
    {"type":"timeline","year":"1984","label":"Nike signs Michael Jordan"}
    {"type":"compare","title":"Revenue 2023","unit":"B","a":{"label":"Nike","value":51.2},"b":{"label":"Adidas","value":23.6}}"""


CHART_RULE = """
- With a DATA SHEET you may also use a line-chart graphic that the system draws from the verified data:
    {"type":"chart","metric":"gdp"}   (metric = one of: METRICS) — use it 2-3 times per video where the trend matters,
  and say the trend in the narration.
- For this channel "visual_queries" MUST name the actual place: country/city + what to show, e.g.
  ["Tokyo skyline", "Japan car factory", "Osaka port"]; "photo_subject" = a real landmark, port, factory,
  building or the leader named in the data sheet (searchable on Wikimedia Commons)."""


def generate_script(cfg: dict, title: str, angle: str = "", facts: str = "", metrics=None) -> dict:
    """Writes the script in small pieces (outline, then one chapter per call) so each request stays light."""
    key = cfg["gemini_key"]
    minutes = float(cfg.get("video_minutes", 10))
    target = round(minutes * 150)

    # 1) outline
    data_block = (f"\nDATA SHEET (verified, from the World Bank and Wikidata — use THESE numbers for any statistic; "
                  f"do not invent other figures):\n{facts}\n") if facts else ""
    style = STYLE + (CHART_RULE.replace("METRICS", ", ".join(metrics or [])) if facts and metrics else "")
    outline = gemini.generate_json(key, f"""Plan a long-form YouTube documentary for {cfg.get("script_channel") or "a faceless business case-study channel"}.

TOPIC: {title}
{f'ANGLE: {angle}' if angle else ''}
AUDIENCE: English-speaking viewers (USA/UK/Canada/Australia), 18-45, interested in business and brands.
TOTAL LENGTH: about {target} words of narration (≈{minutes:g} minutes).
{data_block}
Make 6-8 chapters. Chapter 1 is "Intro": a 15-25 second cold-open hook (surprising fact, stakes or question).
Arc: {cfg.get("script_arc") or "setup → rise/conflict → turning points → outcome → the business lesson"}. The last chapter is the lesson + a natural line asking viewers to subscribe.
For each chapter give 3-5 bullet "beats" with the concrete, well-documented facts it must cover, and a word budget (all budgets add up to about {target}).

Also return:
- "title": final YouTube title (<70 chars, curiosity-driven, honest). No exaggeration and no dollar figures or statistics unless they are certain and widely reported.
- "description": 2 short SEO paragraphs (no timestamps, no hashtags)
- "tags": 12-15 SEO tags
- "thumbnail_text": 2-4 punchy words for the thumbnail
- "thumbnail_query": 1-2 concrete nouns for a striking stock PHOTO directly tied to the story's main object (e.g. "sneakers", "burger", "smartphone"); no brand names, no abstract words

Return ONLY JSON:
{{"title":"","description":"","tags":[],"thumbnail_text":"","thumbnail_query":"","chapters":[{{"name":"","beats":[""],"words":0}}]}}""", temperature=0.8)
    chapters = outline.get("chapters") or []
    if not chapters:
        raise RuntimeError("Outline came back without chapters.")
    print(f"[script] outline: {len(chapters)} chapters", flush=True)

    # 2) one call per chapter
    scenes = []
    plan_txt = "\n".join(f"{i + 1}. {c.get('name', '')}" for i, c in enumerate(chapters))
    for i, ch in enumerate(chapters):
        name = str(ch.get("name") or f"Part {i + 1}").strip()
        budget = int(ch.get("words") or target / len(chapters))
        budget = max(60, min(budget, 450))
        n_scenes = max(1, round(budget / 55))
        prev = scenes[-1]["narration"][-400:] if scenes else ""
        beats = "\n".join(f"- {b}" for b in (ch.get("beats") or []))
        part = gemini.generate_json(key, f"""You are writing one chapter of a YouTube documentary script.

VIDEO: {outline.get('title') or title}
ALL CHAPTERS:
{plan_txt}

WRITE NOW: chapter {i + 1} of {len(chapters)} — "{name}"
MUST COVER:
{beats or '- (use your judgement)'}
LENGTH: about {budget} words of narration, split into {n_scenes} scene(s) of roughly equal length.
{'This is the cold-open hook: grab attention in the first sentence.' if i == 0 else ''}
{'This is the final chapter: give the key lesson and end with a natural line asking viewers to subscribe.' if i == len(chapters) - 1 else ''}
{f'The previous chapter ended with: "...{prev}" — continue smoothly, do not repeat it.' if prev else ''}
{'End with a short open loop that makes viewers want the next chapter.' if 0 < i < len(chapters) - 1 else ''}
{data_block}
{style}

Return ONLY JSON: {{"scenes":[{{"narration":"","visual_queries":["","",""],"on_screen_text":"","photo_subject":"","graphic":null}}]}}""", temperature=0.8)
        got = [_clean_scene({**sc, "chapter": "Intro" if i == 0 else name}) for sc in (part.get("scenes") or [])]
        got = [g for g in got if g["narration"]]
        if not got:
            raise RuntimeError(f"Chapter {i + 1} came back empty.")
        scenes.extend(got)
        print(f"[script] chapter {i + 1}/{len(chapters)} '{name}': {sum(words(g['narration']) for g in got)} words", flush=True)

    title_out = str(outline.get("title") or title).strip()
    title_out = fact_check(key, title_out, scenes, facts)

    tags = outline.get("tags") or []
    return {
        "title": title_out,
        "description": str(outline.get("description") or "").strip(),
        "tags": tags if isinstance(tags, list) else [t.strip() for t in str(tags).split(",") if t.strip()],
        "thumbnail_text": str(outline.get("thumbnail_text") or "").strip(),
        "thumbnail_query": str(outline.get("thumbnail_query") or "business").strip(),
        "scenes": scenes,
    }


def fact_check(key: str, title: str, scenes: list, facts: str = "") -> str:
    """Second pass: an editor flags doubtful claims and rewrites only those sentences. Returns a safe title."""
    numbered = "\n".join(f"[{i}] {sc['narration']}" for i, sc in enumerate(scenes))
    graphics = "\n".join(f"[{i}] {json.dumps(sc['graphic'])}" for i, sc in enumerate(scenes) if sc.get("graphic"))
    try:
        res = gemini.generate_json(key, f"""You are a strict fact-checking editor for a business documentary on YouTube.

TITLE: {title}
SCRIPT (numbered scenes):
{numbered}

GRAPHICS:
{graphics or '(none)'}
{f"VERIFIED DATA (World Bank / Wikidata) — numbers that match this are correct, keep them; chart graphics are drawn from it:{chr(10)}{facts}{chr(10)}" if facts else ""}
Find every claim that is wrong, a well-known myth, exaggerated, or a number/date you are NOT confident is widely reported.
For each one, rewrite ONLY the affected sentence so it is accurate or safely qualitative (keep the same style and length).
If a graphic shows a doubtful number, mark it for removal. If the title exaggerates or uses a doubtful number, give a safer honest title (<70 chars, still curiosity-driven).

Return ONLY JSON:
{{"fixes":[{{"scene":0,"old":"exact original sentence","new":"corrected sentence"}}],"remove_graphics":[0],"title":"safe title"}}""", temperature=0.2)
    except Exception as e:
        print(f"[script] fact-check skipped: {e}", flush=True)
        return title
    n = 0
    for fx in res.get("fixes") or []:
        try:
            sc = scenes[int(fx["scene"])]
            old, new = str(fx["old"]).strip(), str(fx["new"]).strip()
            if old and new and old in sc["narration"]:
                sc["narration"] = sc["narration"].replace(old, new)
                n += 1
        except (KeyError, ValueError, IndexError, TypeError):
            continue
    for gi in res.get("remove_graphics") or []:
        try:
            scenes[int(gi)]["graphic"] = None
        except (ValueError, IndexError, TypeError):
            pass
    safe = str(res.get("title") or "").strip()
    print(f"[script] fact-check: {n} sentence(s) corrected, {len(res.get('remove_graphics') or [])} graphic(s) removed", flush=True)
    return safe if 10 <= len(safe) <= 100 else title
