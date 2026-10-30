"""Gemini: model auto-detection with quota-aware fallback, JSON generation and TTS."""
import base64
import json
import re
import time

import requests

BASE = "https://generativelanguage.googleapis.com/v1beta"
_candidates: dict = {}
_dead: set = set()


def log(msg: str) -> None:
    print(f"[gemini] {msg}", flush=True)


class QuotaError(RuntimeError):
    pass


# ---------------- model detection ----------------

def _version(name: str) -> int:
    m = re.search(r"gemini-(\d+)(?:\.(\d+))?", name)
    return int(m.group(1)) * 100 + int(m.group(2) or 0) if m else 0


def _rank(names):
    # stable before preview/exp, newest first, shortest (base) name first
    return sorted(set(names), key=lambda n: (1 if re.search(r"preview|exp", n) else 0, -_version(n), len(n)))


def candidates(key: str) -> dict:
    if _candidates:
        return _candidates
    names, token = [], ""
    for _ in range(10):
        r = requests.get(f"{BASE}/models", params={"pageSize": 1000, **({"pageToken": token} if token else {})},
                         headers={"x-goog-api-key": key}, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"Gemini key check failed ({r.status_code}): {r.text[:300]}")
        j = r.json()
        for m in j.get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", []):
                names.append(m["name"].replace("models/", ""))
        token = j.get("nextPageToken")
        if not token:
            break
    bad = re.compile(r"tts|image|audio|live|embed|vision|thinking|robotics|computer|learnlm|gemma|aqa|nano|banana")
    gem = [n for n in names if n.startswith("gemini-") and not bad.search(n)]
    flash = [n for n in gem if "flash" in n and "lite" not in n]
    lite = [n for n in gem if "flash-lite" in n]
    pro = [n for n in gem if "pro" in n]
    text = _rank(flash) + _rank(lite) + _rank(pro)
    text = list(dict.fromkeys(text)) or _rank(gem)
    tts_all = [n for n in names if "tts" in n]
    tts = list(dict.fromkeys(_rank([n for n in tts_all if "flash" in n]) + _rank(tts_all)))
    _candidates.update(text=text[:8], tts=tts[:4])
    log(f"script models to try: {', '.join(_candidates['text']) or 'none'}")
    log(f"voice models to try: {', '.join(_candidates['tts']) or 'none'}")
    return _candidates


# ---------------- core call ----------------

def _quota_kind(err: dict, msg: str) -> str:
    """'day' (or zero quota) → give up on this model; 'minute' → wait and retry."""
    ids = []
    for d in err.get("details", []):
        for v in d.get("violations", []) or []:
            ids.append(str(v.get("quotaId", "")) + " " + str(v.get("quotaMetric", "")))
    blob = " ".join(ids) + " " + msg
    if re.search(r"limit:\s*0\b", msg) or re.search(r"PerDay|per day|daily", blob, re.I):
        return "day"
    return "minute"


def _call(key: str, kind: str, body: dict) -> dict:
    models = [m for m in candidates(key)[kind] if m not in _dead]
    if not models:
        raise QuotaError(f"No Gemini {kind} model with free quota left on this key today.")
    last = ""
    for model in models:
        wait, tries = 15, 0
        while tries < 4:
            tries += 1
            t0 = time.time()
            try:
                r = requests.post(f"{BASE}/models/{model}:generateContent", headers={"x-goog-api-key": key},
                                  json=body, timeout=(20, 300))
            except requests.RequestException as e:
                last = f"{model} → network/timeout: {e}"
                log(f"{model}: no reply ({str(e)[:120]})")
                if tries >= 2:
                    log(f"{model}: giving up, trying next model")
                    break
                time.sleep(wait)
                continue
            if r.status_code == 200:
                # remember the working model first next time
                lst = _candidates[kind]
                if lst and lst[0] != model:
                    lst.remove(model)
                    lst.insert(0, model)
                return r.json()
            try:
                err = r.json().get("error", {})
            except ValueError:
                err = {}
            msg = err.get("message", r.text[:300])
            last = f"{model} → {r.status_code}: {msg[:300]}"
            if r.status_code == 429:
                if _quota_kind(err, msg) == "day":
                    log(f"{model}: no free quota left ({msg[:160]}). Trying next model.")
                    _dead.add(model)
                    break
                delay = wait
                for d in err.get("details", []):
                    if "retryDelay" in d:
                        try:
                            delay = float(str(d["retryDelay"]).rstrip("s")) + 3
                        except ValueError:
                            pass
                log(f"{model}: per-minute limit, waiting {int(delay)}s ({msg[:120]})")
                time.sleep(min(delay, 90))
                wait = min(wait * 2, 90)
                continue
            if r.status_code in (500, 502, 503, 504):
                if tries >= 2:
                    log(f"{model}: server busy ({r.status_code}) again after {int(time.time() - t0)}s — trying next model")
                    break
                log(f"{model}: server busy ({r.status_code}) after {int(time.time() - t0)}s, retrying in {wait}s")
                time.sleep(wait)
                continue
            if r.status_code in (400, 403, 404):
                log(f"{model}: {r.status_code} {msg[:160]} — trying next model")
                _dead.add(model)
                break
            raise RuntimeError(f"Gemini error {last}")
        else:
            log(f"{model}: still limited after retries — trying next model")
    raise QuotaError(f"All Gemini {kind} models are rate-limited or out of free quota. Last error: {last}")


def _parse_json(text: str):
    clean = re.sub(r"```(?:json)?", "", text, flags=re.I).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        starts = [i for i in (clean.find("{"), clean.find("[")) if i >= 0]
        end = max(clean.rfind("}"), clean.rfind("]"))
        if starts and end > min(starts):
            return json.loads(clean[min(starts):end + 1])
        raise RuntimeError("Gemini did not return valid JSON.")


def generate_json(key: str, prompt: str, temperature: float = 0.85):
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": temperature, "maxOutputTokens": 8192},
    }
    for attempt in range(2):
        resp = _call(key, "text", body)
        parts = resp.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if text:
            try:
                return _parse_json(text)
            except (RuntimeError, json.JSONDecodeError):
                log("reply was not valid JSON, asking again")
                continue
        log("empty reply, asking again")
    raise RuntimeError("Gemini returned no usable reply.")


def tts(key: str, text: str, voice: str, style: str = "") -> tuple[bytes, int]:
    """Returns (PCM int16 little-endian mono bytes, sample_rate)."""
    # The style line is NOT sent: Gemini sometimes read it out loud at the start of a chunk
    # ("Narrate like a business documentary…"). The voice itself (e.g. Charon) gives the documentary tone.
    prompt = text
    resp = _call(key, "tts", {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    })
    for p in resp.get("candidates", [{}])[0].get("content", {}).get("parts", []):
        data = p.get("inlineData", {})
        if data.get("data"):
            m = re.search(r"rate=(\d+)", data.get("mimeType", ""))
            return base64.b64decode(data["data"]), int(m.group(1)) if m else 24000
    raise RuntimeError("Gemini TTS returned no audio.")
