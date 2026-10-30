"""Nation Inc. format: every country explained as if it were a company.

Before the script is written, this module collects VERIFIED data so the AI never has to guess numbers:
- World Bank API (free, no key): GDP ("revenue"), growth, population ("employees"), GDP per person, inflation,
  unemployment, exports/imports, government debt, foreign investment, reserves — latest value + history.
- Wikidata (free, no key): current head of government ("CEO") and head of state ("chairman"), founding date,
  capital ("headquarters"), currency, flag.
Outputs: a DATA SHEET for the script, a "company card" for the video, chart series, and a thumbnail background.
"""
import re
from pathlib import Path

import requests

from . import commons, gemini, stock

UA = {"User-Agent": "NationIncAutopilot/1.0 (YouTube documentary research; contact via GitHub)"}
INDICATORS = {
    "gdp": ("NY.GDP.MKTP.CD", "GDP — the country's yearly 'revenue'", "money"),
    "growth": ("NY.GDP.MKTP.KD.ZG", "Real GDP growth", "pct"),
    "population": ("SP.POP.TOTL", "Population — the 'employees'", "num"),
    "gdp_per_capita": ("NY.GDP.PCAP.CD", "GDP per person", "money"),
    "inflation": ("FP.CPI.TOTL.ZG", "Inflation (consumer prices)", "pct"),
    "unemployment": ("SL.UEM.TOTL.ZS", "Unemployment (% of workforce)", "pct"),
    "exports": ("NE.EXP.GNFS.CD", "Exports of goods & services — 'sales abroad'", "money"),
    "imports": ("NE.IMP.GNFS.CD", "Imports of goods & services — 'purchases abroad'", "money"),
    "debt": ("GC.DOD.TOTL.GD.ZS", "Central government debt (% of GDP)", "pct"),
    "fdi": ("BX.KLT.DVLP.CD.WD", "Foreign direct investment inflows — 'outside investors'", "money"),
    "reserves": ("FI.RES.TOTL.CD", "Foreign reserves incl. gold — 'cash in the bank'", "money"),
}


def log(msg):
    print(f"[nation] {msg}", flush=True)


# ------------------------------------------------------------------ formatting

def money(v):
    a = abs(v)
    for div, suf in ((1e12, " trillion"), (1e9, " billion"), (1e6, " million")):
        if a >= div:
            return f"{'-' if v < 0 else ''}${a / div:.2f}{suf}"
    return f"${v:,.0f}"


def short_money(v):
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if a >= div:
            return f"{'-' if v < 0 else ''}${a / div:.1f}{suf}"
    return f"${v:,.0f}"


def people(v):
    return f"{v / 1e9:.2f} billion" if v >= 1e9 else f"{v / 1e6:.1f} million" if v >= 1e6 else f"{v:,.0f}"


def fmt(kind, v):
    return money(v) if kind == "money" else f"{v:.1f}%" if kind == "pct" else people(v)


# ------------------------------------------------------------------ lookups

def identify(cfg, title):
    """Which country is the video about? → {"country": "Japan", "iso3": "JPN", "place": "Japan"}"""
    try:
        r = gemini.generate_json(cfg["gemini_key"], f"""Video title: "{title}"
Which ONE country is this video about? If it is about a city or region (e.g. Dubai, Texas), give the country it
belongs to and put the city/region in "place". Return JSON: {{"country":"","iso3":"","place":""}}
(iso3 = ISO 3166-1 alpha-3 code, e.g. JPN, ARE, USA)""", temperature=0.1)
        iso = str(r.get("iso3") or "").upper().strip()
        if re.fullmatch(r"[A-Z]{3}", iso):
            return {"country": str(r.get("country") or iso), "iso3": iso,
                    "place": str(r.get("place") or r.get("country") or iso)}
    except Exception as e:
        log(f"country lookup via Gemini failed: {e}")
    m = re.search(r"if (.+?) (?:was|were) a", title, re.I)
    name = (m.group(1) if m else title).strip()
    return {"country": name, "iso3": "", "place": name}


def worldbank(iso3):
    out = {}
    for key, (code, label, kind) in INDICATORS.items():
        try:
            r = requests.get(f"https://api.worldbank.org/v2/country/{iso3}/indicator/{code}",
                             params={"format": "json", "per_page": 80, "date": "1990:2030"}, timeout=40, headers=UA)
            data = r.json()
            rows = data[1] if isinstance(data, list) and len(data) > 1 and data[1] else []
            series = sorted((int(x["date"]), float(x["value"])) for x in rows if x.get("value") is not None)
            if series:
                out[key] = {"label": label, "kind": kind, "series": series, "year": series[-1][0], "value": series[-1][1]}
        except Exception as e:
            log(f"World Bank {code}: {e}")
    log(f"World Bank: {len(out)}/{len(INDICATORS)} indicators")
    return out


def wikidata(iso3):
    q = f"""SELECT ?c ?hosLabel ?hogLabel ?inception ?capitalLabel ?currencyLabel ?flag WHERE {{
  ?c wdt:P298 "{iso3}".
  OPTIONAL {{ ?c p:P35 ?s. ?s ps:P35 ?hos. FILTER NOT EXISTS {{ ?s pq:P582 ?e }} }}
  OPTIONAL {{ ?c p:P6 ?s2. ?s2 ps:P6 ?hog. FILTER NOT EXISTS {{ ?s2 pq:P582 ?e2 }} }}
  OPTIONAL {{ ?c wdt:P571 ?inception }}
  OPTIONAL {{ ?c wdt:P36 ?capital }}
  OPTIONAL {{ ?c wdt:P38 ?currency }}
  OPTIONAL {{ ?c wdt:P41 ?flag }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT 20"""
    info = {}
    try:
        r = requests.get("https://query.wikidata.org/sparql", params={"query": q, "format": "json"},
                         headers={**UA, "Accept": "application/sparql-results+json"}, timeout=60)
        rows = r.json()["results"]["bindings"]
        get = lambda row, k: row.get(k, {}).get("value", "")  # noqa: E731
        for row in rows:
            for k in ("hosLabel", "hogLabel", "capitalLabel", "currencyLabel", "flag"):
                v = get(row, k)
                if v and not re.fullmatch(r"Q\d+", v) and k not in info:
                    info[k] = v
            inc = get(row, "inception")
            if inc:
                m = re.match(r"(-?)0*(\d{1,4})-", inc)
                if m:
                    y = int(m.group(2)) * (-1 if m.group(1) else 1)
                    info["founded"] = min(info.get("founded", 99999), y)
    except Exception as e:
        log(f"Wikidata: {e}")
    log(f"Wikidata: {', '.join(f'{k}={v}' for k, v in info.items() if k != 'flag')}")
    return info


def _download(url, dest: Path):
    try:
        r = requests.get(url, headers=UA, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return dest
    except Exception as e:
        log(f"download failed {url}: {e}")
        return None


# ------------------------------------------------------------------ main entry

def prepare(cfg, title, work: Path):
    """Returns {"sheet": str, "metrics": [...], "card": {...}, "series": {...}, "thumb_bg": path|None}."""
    work.mkdir(parents=True, exist_ok=True)
    who = identify(cfg, title)
    log(f"topic → {who['place']} ({who['country']}, {who['iso3'] or '?'})")
    wb = worldbank(who["iso3"]) if who["iso3"] else {}
    wd = wikidata(who["iso3"]) if who["iso3"] else {}

    lines = [f"Country: {who['country']}" + (f" (video focuses on {who['place']})" if who["place"] != who["country"] else "")]
    if wd.get("hogLabel"):
        lines.append(f"Head of government ('CEO') right now: {wd['hogLabel']}")
    if wd.get("hosLabel") and wd.get("hosLabel") != wd.get("hogLabel"):
        lines.append(f"Head of state ('chairman of the board') right now: {wd['hosLabel']}")
    if wd.get("capitalLabel"):
        lines.append(f"Capital ('headquarters'): {wd['capitalLabel']}")
    if wd.get("currencyLabel"):
        lines.append(f"Currency: {wd['currencyLabel']}")
    if "founded" in wd:
        f = wd["founded"]
        lines.append(f"Founded (modern state, per Wikidata): {f if f > 0 else f'{-f} BC'}")
    for key, d in wb.items():
        s = d["series"]
        hist = ""
        old = [p for p in s if p[0] <= d["year"] - 10]
        if old:
            hist = f" (ten years earlier, {old[-1][0]}: {fmt(d['kind'], old[-1][1])})"
        lines.append(f"{d['label']}: {fmt(d['kind'], d['value'])} in {d['year']}{hist}")
    sheet = "\n".join(f"- {x}" for x in lines)

    # chart series (scaled for display)
    series = {}
    for key, d in wb.items():
        pts = [p for p in d["series"] if p[0] >= 2000]
        if len(pts) < 5:
            continue
        if d["kind"] == "money":
            mx = max(abs(v) for _, v in pts)
            div, unit = (1e12, "T") if mx >= 1e12 else (1e9, "B") if mx >= 1e9 else (1e6, "M")
            series[key] = {"title": d["label"].split(" — ")[0], "prefix": "$", "unit": unit,
                           "points": [[y, round(v / div, 3)] for y, v in pts]}
        elif d["kind"] == "pct":
            series[key] = {"title": d["label"].split(" — ")[0], "prefix": "", "unit": "%",
                           "points": [[y, round(v, 2)] for y, v in pts]}
        else:
            div, unit = (1e9, "B") if max(v for _, v in pts) >= 1e9 else (1e6, "M")
            series[key] = {"title": d["label"].split(" — ")[0], "prefix": "", "unit": unit,
                           "points": [[y, round(v / div, 3)] for y, v in pts]}

    # company card
    rows = []
    if wd.get("hogLabel"):
        rows.append(["CEO", wd["hogLabel"]])
    if wd.get("capitalLabel"):
        rows.append(["HQ", wd["capitalLabel"]])
    if "founded" in wd and wd["founded"] > 0:
        rows.append(["FOUNDED", str(wd["founded"])])
    if "population" in wb:
        rows.append(["EMPLOYEES", people(wb["population"]["value"])])
    if "gdp" in wb:
        rows.append(["REVENUE", f"{short_money(wb['gdp']['value'])} / yr"])
    if "growth" in wb:
        g = wb["growth"]["value"]
        rows.append(["GROWTH", f"{'+' if g >= 0 else ''}{g:.1f}%"])
    if "debt" in wb:
        rows.append(["DEBT", f"{wb['debt']['value']:.0f}% of revenue"])
    flag = None
    if wd.get("flag"):
        url = wd["flag"].replace("http://", "https://")
        url += ("&" if "?" in url else "?") + "width=800"
        flag = _download(url, work / "flag.png")
    card = {"name": f"{who['place']} Inc.", "rows": rows[:7], "flag": str(flag) if flag else None}

    # thumbnail background: a real photo of the capital/place, else the flag
    thumb_bg = None
    place = who["place"] if who["place"] != who["country"] else (wd.get("capitalLabel") or who["country"])
    try:
        ph = commons.search(f"{place} skyline", set()) or (stock.find_photo(cfg, f"{place} city") if cfg.get("pixabay_key") else None)
        if ph:
            thumb_bg = str(stock.download(ph, work / "nation_thumb"))
    except Exception as e:
        log(f"thumbnail photo failed: {e}")
    if not thumb_bg and flag:
        thumb_bg = str(flag)
    log(f"data sheet: {len(lines)} facts, {len(series)} chart series, card rows: {len(card['rows'])}")
    return {"sheet": sheet, "metrics": list(series), "card": card, "series": series, "thumb_bg": thumb_bg, "who": who}
