"""SEO upload kit: titles, description, hashtags, tags, pinned comment and AI thumbnail prompts.

Written next to the video as UPLOAD-KIT.txt so whoever uploads can copy-paste everything into YouTube Studio.
"""
import json

from . import gemini


def log(msg):
    print(f"[seo] {msg}", flush=True)


def _story(script, limit=2200):
    """Short summary of the narration (chapter name + first sentences) for the SEO prompt."""
    out, cur = [], None
    for sc in script.get("scenes", []):
        ch = sc.get("chapter") or ""
        if ch != cur:
            out.append(f"\n[{ch}]")
            cur = ch
        out.append(sc.get("narration", "").split(". ")[0][:160])
    return " ".join(out)[:limit]


def _clean_tag(t):
    return str(t).replace("#", "").replace("<", "").replace(">", "").strip()


def build(cfg, script, chapters_text, credits_text, duration_text):
    """Returns a dict with the full SEO package (falls back to the script's own fields if Gemini fails)."""
    base = {
        "primary_keyword": "",
        "secondary_keywords": [],
        "titles": [script["title"]],
        "description_top": script.get("description", ""),
        "hashtags": ["#business", "#casestudy", "#documentary"],
        "tags": script.get("tags", []),
        "pinned_comment": "",
        "thumbnail_texts": [script.get("thumbnail_text") or script["title"]],
        "thumbnail_prompts": [],
    }
    try:
        res = gemini.generate_json(cfg["gemini_key"], f"""You are a YouTube SEO and packaging expert for {cfg.get("seo_channel") or "a faceless business documentary channel"}
(audience: USA, UK, Canada, Australia, 18-45). Create the upload package for this video.

VIDEO TITLE (working): {script['title']}
LENGTH: {duration_text}
STORY SUMMARY: {_story(script)}

Rules:
- Honest: nothing the video does not deliver, no fake numbers, no clickbait lies.
- "primary_keyword": the main search phrase people type for this topic (2-5 words).
- "secondary_keywords": 6-8 related search phrases.
- "titles": 3 different title options, each under 65 characters, primary keyword near the start, curiosity + clarity
  (patterns that work: {cfg.get("seo_title_patterns") or '"How X ...", "Why X ...", "The Rise and Fall of X", "X vs Y: ..."'}). Best one first.
- "description_top": 3 short paragraphs, 120-200 words total. The FIRST sentence contains the primary keyword and
  hooks the reader (it shows in search results). Mention 2-3 secondary keywords naturally. End with one line inviting
  viewers to subscribe for {cfg.get("seo_subscribe") or "weekly business case studies"}. No hashtags, no timestamps, no links.
- "hashtags": exactly 3 hashtags (first one is the topic/brand, then #business-type tags), CamelCase, no spaces.
- "tags": 15-20 YouTube tags (mix of exact topic, brand names, broad business terms), no "#".
- "pinned_comment": one engaging question for viewers about the story (1-2 sentences).
- "thumbnail_texts": 3 options of 2-4 BIG words for the thumbnail (do not repeat the title).
- "thumbnail_prompts": 3 detailed prompts for an AI image generator (Midjourney / Ideogram / ChatGPT / Gemini),
  16:9, 1280x720, ultra-sharp, high contrast, dramatic lighting, ONE clear focal object, bold emotion, empty space on
  one side for text. Show products, buildings, objects, charts or anonymous silhouettes — NEVER a realistic face of a
  real person, and no readable logos (trademark-safe). Each prompt a different concept.

Return JSON with exactly these keys:
{{"primary_keyword":"","secondary_keywords":[],"titles":[],"description_top":"","hashtags":[],"tags":[],
"pinned_comment":"","thumbnail_texts":[],"thumbnail_prompts":[]}}""", temperature=0.7)
        for k in base:
            v = res.get(k)
            if v:
                base[k] = v
    except Exception as e:
        log(f"SEO package from Gemini failed, using basic one: {e}")

    base["titles"] = [str(t).strip()[:100] for t in base["titles"] if str(t).strip()] or [script["title"]]
    tags = list(dict.fromkeys(_clean_tag(t) for t in base["tags"] if _clean_tag(t)))
    base["tags"] = tags
    hs = []
    for h in base["hashtags"]:
        h = "#" + "".join(str(h).replace("#", "").split())
        if len(h) > 1 and h not in hs:
            hs.append(h)
    base["hashtags"] = hs[:3]

    desc = str(base["description_top"]).strip()
    if chapters_text:
        desc += "\n\n" + chapters_text
    desc += "\n\n" + credits_text
    if base["hashtags"]:
        desc += "\n\n" + " ".join(base["hashtags"])
    base["description"] = desc[:4900]
    return base


def write_kit(path, kit, duration_text, thumb_name):
    tags_line = ", ".join(kit["tags"])
    while len(tags_line) > 480 and "," in tags_line:
        tags_line = tags_line.rsplit(",", 1)[0]
    lines = [
        "TUBE AUTOPILOT — UPLOAD KIT",
        "=" * 60,
        f"Video length: {duration_text}",
        f"Auto thumbnail: {thumb_name} (or make a better one with the prompts below)",
        "",
        "1) TITLE (pick one — first is recommended)",
        *[f"   {i + 1}. {t}" for i, t in enumerate(kit["titles"])],
        "",
        "2) DESCRIPTION (copy everything between the lines)",
        "-" * 60,
        kit["description"],
        "-" * 60,
        "",
        "3) TAGS (YouTube Studio → Show more → Tags, paste as is)",
        tags_line,
        "",
        "4) HASHTAGS (already at the end of the description)",
        " ".join(kit["hashtags"]),
        "",
        "5) PINNED COMMENT (post it after publishing, then Pin)",
        kit.get("pinned_comment", ""),
        "",
        "6) THUMBNAIL TEXT options",
        *[f"   - {t}" for t in kit["thumbnail_texts"]],
        "",
        "7) AI THUMBNAIL PROMPTS (1280x720, 16:9)",
        *[f"   {i + 1}. {p}\n" for i, p in enumerate(kit["thumbnail_prompts"])],
        "",
        "KEYWORDS",
        f"   Primary: {kit.get('primary_keyword', '')}",
        f"   Secondary: {', '.join(kit.get('secondary_keywords') or [])}",
        "",
        "STUDIO SETTINGS",
        "   Audience: No, it's not made for kids",
        "   Altered or synthetic content: No for a normal video (an AI narrator alone does not need it);",
        "   Yes only if you add realistic AI images/video of real people or real events (e.g. an AI thumbnail scene)",
        "   Category: Education · Language: English · Captions: English",
        "   Add an end screen (subscribe + best video) and put the video in a playlist",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    json_path = path.with_suffix(".json")
    json_path.write_text(json.dumps(kit, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
