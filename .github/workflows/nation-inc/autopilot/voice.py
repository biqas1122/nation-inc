"""Voiceover: narrates scenes in a few chunks, builds one master WAV and scene timings."""
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import requests

from . import gemini

RATE = 24000
MAX_WORDS = 300
CHUNKS: list = []   # filled by narrate(): [{'idx': [...], 't0': s, 'dur': s, 'wav': path}]
LEAD, GAP, OUTRO = 0.5, 0.45, 4.0


def log(msg):
    print(f"[voice] {msg}", flush=True)


def chunk_scenes(scenes):
    chunks, cur = [], None
    for i, sc in enumerate(scenes):
        w = len(sc["narration"].split())
        if cur is None or cur["words"] + w > MAX_WORDS:
            cur = {"idx": [], "words": 0}
            chunks.append(cur)
        cur["idx"].append(i)
        cur["words"] += w
    return chunks


def _to_pcm24k(data: bytes, src_ext: str) -> bytes:
    """Converts any audio (mp3 etc.) to 24 kHz mono s16le PCM via ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix=src_ext, delete=False) as f:
        f.write(data)
        src = f.name
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-"],
                         capture_output=True, check=True)
    Path(src).unlink(missing_ok=True)
    return out.stdout


def _resample(pcm: bytes, rate: int) -> bytes:
    if rate == RATE:
        return pcm
    out = subprocess.run(["ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "-",
                          "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-"], input=pcm, capture_output=True, check=True)
    return out.stdout


def _eleven(cfg, text) -> bytes:
    for i in range(5):
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{cfg['elevenlabs_voice_id']}",
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": cfg["elevenlabs_key"], "Accept": "audio/mpeg"},
            json={"text": text, "model_id": cfg.get("elevenlabs_model", "eleven_multilingual_v2"),
                  "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.25}},
            timeout=300,
        )
        if r.status_code == 200:
            return _to_pcm24k(r.content, ".mp3")
        if r.status_code == 429:
            time.sleep(10 * (i + 1))
            continue
        raise RuntimeError(f"ElevenLabs error {r.status_code}: {r.text[:300]}")
    raise RuntimeError("ElevenLabs kept rate-limiting.")


def _edge(cfg, text) -> bytes:
    """Free Microsoft neural voice (no key, no daily limit)."""
    import asyncio
    import edge_tts

    voice = cfg.get("edge_voice", "en-US-ChristopherNeural")
    rate = cfg.get("edge_rate", "+0%")
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        path = f.name
    for i in range(4):
        try:
            asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(path))
            data = Path(path).read_bytes()
            Path(path).unlink(missing_ok=True)
            if data:
                return _to_pcm24k(data, ".mp3")
        except Exception as e:  # network hiccups
            log(f"edge-tts retry {i + 1}: {e}")
            time.sleep(5 * (i + 1))
    raise RuntimeError("Free voice (edge-tts) failed.")


def _speak_all(cfg, provider, scenes, chunks):
    for n, c in enumerate(chunks, 1):
        text = "\n\n".join(scenes[k]["narration"] for k in c["idx"])
        if provider == "elevenlabs":
            pcm = _eleven(cfg, text)
        elif provider == "edge":
            pcm = _edge(cfg, text)
        else:
            raw, rate = gemini.tts(cfg["gemini_key"], text, cfg.get("gemini_voice", "Charon"), cfg.get("tts_style", ""))
            pcm = _resample(raw, rate)
        c["pcm"] = pcm
        c["dur"] = len(pcm) / 2 / RATE
        log(f"part {n}/{len(chunks)}: {c['dur']:.1f}s")


def narrate(cfg: dict, scenes: list, out_wav: Path) -> float:
    """Writes the master narration WAV, fills scene timings, returns total video length (s)."""
    chunks = chunk_scenes(scenes)
    provider = cfg.get("voice_provider", "gemini")
    log(f"{len(chunks)} narration call(s) via {provider}")
    try:
        _speak_all(cfg, provider, scenes, chunks)
    except Exception as e:
        if provider == "edge":
            raise
        # keep one consistent voice for the whole video: redo every part with the free voice
        log(f"{provider} voice failed ({str(e)[:200]}). Switching the whole video to the free voice.")
        _speak_all(cfg, "edge", scenes, chunks)
    pcm_parts = []

    silence = lambda s: b"\x00\x00" * int(s * RATE)  # noqa: E731
    t = LEAD
    pcm_parts.append(silence(LEAD))
    CHUNKS.clear()
    for n, c in enumerate(chunks):
        part = out_wav.with_name(f"chunk_{n:02d}.wav")
        with wave.open(str(part), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(c["pcm"])
        CHUNKS.append({"idx": list(c["idx"]), "t0": t, "dur": c["dur"], "wav": str(part)})
        lens = [len(scenes[k]["narration"]) + 20 for k in c["idx"]]
        total, acc = sum(lens), 0
        for j, k in enumerate(c["idx"]):
            s0 = t + acc / total * c["dur"]
            acc += lens[j]
            s1 = t + acc / total * c["dur"]
            scenes[k].update(start=s0, speech_start=s0, speech_end=s1,
                             end=(t + c["dur"] + GAP) if j == len(c["idx"]) - 1 else s1)
        pcm_parts.append(c["pcm"])
        pcm_parts.append(silence(GAP))
        t += c["dur"] + GAP
    scenes[0]["start"] = 0.0
    total_len = t + OUTRO
    pcm_parts.append(silence(OUTRO))

    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(pcm_parts))
    log(f"narration total {total_len:.1f}s")
    return total_len
