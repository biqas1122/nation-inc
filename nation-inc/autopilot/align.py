"""Exact voice <-> caption <-> picture sync.

How it works (per narration chunk, so a mistake can never spread across the video):

1. SENTENCES: the chunk's audio is scanned for pauses (silencedetect). Every sentence boundary in
   the script is matched to a real pause with dynamic programming, so each sentence gets its real
   start and end time. This step needs nothing but ffmpeg and always runs.
2. WORDS: inside each sentence, words are spread by length. Then, if Whisper is available, it
   listens to the chunk and every word it recognises gets its exact time - but only if that time
   falls inside the sentence's window, so a Whisper slip can't push captions seconds off.

Result: every scene gets speech_start / speech_end and a per-word list sc["words"] = [(word, s, e)]
that the renderer uses for captions and cuts.
"""
import difflib
import re
import subprocess

TOKEN = re.compile(r"[a-z0-9]+")
SENT_SPLIT = re.compile(r"(?<=[.!?])[\"')\]]*\s+")

_whisper_model = None


def log(msg):
    print(f"[sync] {msg}", flush=True)


def _norm(word: str) -> list[str]:
    return TOKEN.findall(word.lower().replace("'", "").replace("’", ""))


# ------------------------------------------------------------------ audio pauses

def pauses(wav: str, noise_db=-38, min_len=0.12):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", wav, "-af", f"silencedetect=n={noise_db}dB:d={min_len}",
                        "-f", "null", "-"], capture_output=True, text=True)
    out, start = [], None
    for m in re.finditer(r"silence_(start|end): (-?[0-9.]+)", r.stderr):
        kind, v = m.group(1), max(0.0, float(m.group(2)))
        if kind == "start":
            start = v
        elif start is not None:
            out.append((start, v))
            start = None
    return out


def _speech_bounds(ps, dur):
    """First and last moment of actual speech in the chunk."""
    s0, s1 = 0.0, dur
    if ps and ps[0][0] <= 0.05:
        s0 = ps[0][1]
    if ps and ps[-1][1] >= dur - 0.05:
        s1 = ps[-1][0]
    return s0, max(s1, s0 + 0.1)


def _match_rate(W, Wtot, cands, kinds, s0, s1, max_skip=4, max_jump=10):
    """Chooses a pause (or none) for every phrase boundary so that each stretch of speech lasts about as
    long as its text predicts. W[i] = text position of boundary i (in weight units, 0..Wtot).
    Returns a list of (start, end) pauses or None, one per boundary."""
    n, m = len(W), len(cands)
    rate = (s1 - s0) / max(Wtot, 1e-6)
    mids = [(a + b) / 2 for a, b in cands]
    pos = [0.0] + W + [Wtot]           # index 0 = start, n+1 = end
    INF = float("inf")

    def seg_cost(dW, dT):
        exp = dW * rate
        if dT <= 0.05:
            return INF
        r = abs(dT - exp) / (0.25 * exp + 0.3)
        return r + 0.6 * r * r

    def skip_cost(i):
        return 0.6 if kinds[i - 1] == "comma" else 2.2

    def bonus(i, j):
        a, b = cands[j]
        plen = min(0.9, b - a)
        return plen * (1.5 if kinds[i - 1] != "comma" else 0.5)

    # states: (i, j) boundary i matched to pause j ; start state (0, -1) at time s0
    best = {(0, -1): (0.0, None)}
    by_i = {0: [-1]}
    order = [(0, -1)]
    for i in range(1, n + 1):
        by_i[i] = []
        for j in range(m):
            t = mids[j]
            if t <= s0 or t >= s1:
                continue
            cand = None
            for pi in range(max(0, i - max_skip - 1), i):
                for pj in by_i.get(pi, []):
                    if pj >= j or (pj >= 0 and j - pj > max_jump):
                        continue
                    prev_t = s0 if pj < 0 else mids[pj]
                    c = best[(pi, pj)][0] + seg_cost(pos[i] - pos[pi], t - prev_t)
                    c += sum(skip_cost(k) for k in range(pi + 1, i)) - bonus(i, j)
                    if cand is None or c < cand[0]:
                        cand = (c, (pi, pj))
            if cand and cand[0] < INF:
                best[(i, j)] = cand
                by_i[i].append(j)
                order.append((i, j))
    # close at the end
    final = None
    for (pi, pj) in order:
        if n + 1 - pi > max_skip + 1:
            continue
        prev_t = s0 if pj < 0 else mids[pj]
        c = best[(pi, pj)][0] + seg_cost(pos[n + 1] - pos[pi], s1 - prev_t)
        c += sum(skip_cost(k) for k in range(pi + 1, n + 1))
        if final is None or c < final[0]:
            final = (c, (pi, pj))
    picks = [None] * n
    st = final[1] if final else None
    while st and st[0] > 0:
        i, j = st
        picks[i - 1] = cands[j]
        st = best[st][1]
    return picks


def _phrases_of(scenes, idx):
    """[(scene_idx, [words...], pause_kind)] split at every punctuation mark, in speaking order.
    pause_kind is the pause that FOLLOWS the phrase: 'sent' (. ! ?), 'comma' (, ; : —) or 'scene'."""
    out = []
    for k in idx:
        ws = scenes[k]["narration"].split()
        cur = []
        for i, w in enumerate(ws):
            cur.append(w)
            last = i == len(ws) - 1
            core = w.rstrip("\"')]”’")
            if last:
                out.append((k, cur, "scene"))
                cur = []
            elif core[-1:] in ".!?":
                out.append((k, cur, "sent"))
                cur = []
            elif core[-1:] in ",;:" or core.endswith("—") or core.endswith("--"):
                out.append((k, cur, "comma"))
                cur = []
    return out


def _weight(word):
    """Rough spoken length of a word (numbers are long when read out)."""
    w = re.sub(r"[^\w$%]", "", word)
    if re.search(r"\d", w):
        return 3 + len(w) * 1.6
    return 1.5 + len(w)


PAUSE_W = {"comma": 2.5, "sent": 4.5, "scene": 5.0}


def sentence_timing(scenes, chunk):
    """Times every phrase of one chunk against its real pauses.
    Returns (list of (scene, words, start, end), matched, total_boundaries)."""
    dur = chunk["dur"]
    ps = pauses(chunk["wav"])
    s0, s1 = _speech_bounds(ps, dur)
    inner = [p for p in ps if p[0] > s0 + 0.05 and p[1] < s1 - 0.05]
    phr = _phrases_of(scenes, chunk["idx"])
    if not phr:
        return []
    lens = [sum(_weight(w) for w in ws) for _, ws, _ in phr]
    gaps = [PAUSE_W[kind] for _, _, kind in phr[:-1]]
    total = sum(lens) + sum(gaps)
    W, kinds, acc = [], [], 0.0
    for i in range(len(phr) - 1):
        acc += lens[i] + gaps[i] / 2
        W.append(acc)
        acc += gaps[i] / 2
        kinds.append(phr[i][2])
    picks = _match_rate(W, total, inner, kinds, s0, s1) if W else []
    # boundaries without a pause: interpolate between the nearest matched neighbours (local speed)
    anchors = [(0.0, s0)] + [(W[i], (p[0] + p[1]) / 2) for i, p in enumerate(picks) if p] + [(total, s1)]
    def at(w):
        for (w0, t0), (w1, t1) in zip(anchors, anchors[1:]):
            if w0 <= w <= w1:
                return t0 + (t1 - t0) * (w - w0) / max(w1 - w0, 1e-6)
        return s1
    expected = [at(w) for w in W]
    fixed, last = [], s0
    for e, p in zip(expected, picks):
        a, b = (p[0], p[1]) if p else (e, e)
        a = max(a, last + 0.12)
        b = max(b, a)
        fixed.append((a, b))
        last = b
    out, start = [], s0
    anchored = [True] + [bool(p) for p in picks] + [True]   # is boundary i a real, measured pause?
    for i, (k, ws, _) in enumerate(phr):
        end = fixed[i][0] if i < len(fixed) else s1
        out.append((k, ws, start, max(end, start + 0.1), anchored[i], anchored[i + 1]))
        if i < len(fixed):
            start = fixed[i][1]
    matched = sum(1 for p in picks if p)
    return out, matched, len(picks)


def _spread(ws, s, e):
    weights = [_weight(w) for w in ws]
    tot = sum(weights) or 1
    out, acc = [], 0
    for w, wt in zip(ws, weights):
        a = s + (e - s) * acc / tot
        acc += wt
        out.append([w, a, s + (e - s) * acc / tot])
    return out


# ------------------------------------------------------------------ whisper refinement

def _whisper(cfg):
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(cfg.get("whisper_model", "base.en"), device="cpu", compute_type="int8")
    return _whisper_model


def _load_16k(wav):
    """Decodes audio with ffmpeg into the float32 16 kHz array Whisper wants (avoids PyAV version issues)."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", wav, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0


def _asr_words(cfg, wav):
    segs, _ = _whisper(cfg).transcribe(_load_16k(wav), language="en", word_timestamps=True, beam_size=1,
                                       vad_filter=False, condition_on_previous_text=False)
    out = []
    for seg in segs:
        for w in seg.words or []:
            toks = _norm(w.word)
            span = (w.end - w.start) / max(1, len(toks))
            for i, t in enumerate(toks):
                out.append((t, w.start + i * span, w.start + (i + 1) * span))
    return out


def _refine(words, asr, win_pad=0.25):
    """words: list of [word, s, e, sent_s, sent_e]. Replaces times with Whisper's where they agree."""
    toks, owner = [], []
    for wi, w in enumerate(words):
        for t in _norm(w[0]):
            toks.append(t)
            owner.append(wi)
    if not toks or not asr:
        return 0.0
    sm = difflib.SequenceMatcher(None, toks, [a[0] for a in asr], autojunk=False)
    got = {}
    for a, b, n in sm.get_matching_blocks():
        if n < 3:          # single/double-word matches are often the wrong "the"/"a" - ignore them
            continue
        for k in range(n):
            wi = owner[a + k]
            ts, te = asr[b + k][1], asr[b + k][2]
            w = words[wi]
            pad = win_pad
            if w[3] - pad <= ts <= w[4] + pad:
                if wi in got:
                    got[wi] = (got[wi][0], max(got[wi][1], te))
                else:
                    got[wi] = (ts, te)
    heard = len(got)
    for wi, (s, e) in got.items():
        w = words[wi]
        # phrase edges measured from real pauses are kept; Whisper only places the words inside
        if len(w) > 6 and w[6]:
            s = w[1]
        if len(w) > 7 and w[7]:
            e = w[2]
        w[1], w[2] = s, max(e, s + 0.05)
    # pause-measured phrase edges are fixed points too
    for wi, w in enumerate(words):
        if wi not in got and ((len(w) > 6 and w[6]) or (len(w) > 7 and w[7])):
            got[wi] = (w[1], w[2])
    # re-spread the words Whisper missed between their known neighbours
    i = 0
    while i < len(words):
        if i in got:
            i += 1
            continue
        j = i
        while j < len(words) and j not in got:
            j += 1
        left = words[i - 1][2] if i > 0 else words[i][3]
        right = words[j][1] if j < len(words) else words[j - 1][4]
        left, right = min(left, right), max(left, right)
        seg = _spread([w[0] for w in words[i:j]], left, right)
        for k, (w, s, e) in enumerate(seg):
            words[i + k][1], words[i + k][2] = s, e
        i = j
    return heard / len(words)


# ------------------------------------------------------------------ main entry

def sync(cfg: dict, scenes: list, wav: str, chunks: list = None):
    from . import voice
    chunks = chunks if chunks is not None else voice.CHUNKS
    if not chunks:
        log("no chunk info — keeping estimated timings")
        finalize_times(scenes)
        return "estimate"

    use_whisper = cfg.get("use_whisper", True)
    total_m = total_b = 0
    ratios = []
    per_scene = {i: [] for i in range(len(scenes))}
    for n, ch in enumerate(chunks):
        res = sentence_timing(scenes, ch)
        if not res:
            continue
        phrases, m, b = res
        total_m += m
        total_b += b
        words = []
        for k, ws, s, e, lock_s, lock_e in phrases:
            sp = _spread(ws, s, e)
            for n_, (w, a, z) in enumerate(sp):
                words.append([w, a, z, s, e, k, lock_s and n_ == 0, lock_e and n_ == len(sp) - 1,
                              lock_s and lock_e])
        if use_whisper:
            try:
                r = _refine(words, _asr_words(cfg, ch["wav"]))
                ratios.append(r)
            except Exception as ex:
                if not ratios:
                    log(f"Whisper not available ({str(ex)[:120]}) — using pause-based sentence timing only")
                use_whisper = False
        for w, a, z, _, _, k, _, _, _ in words:
            per_scene[k].append((w, ch["t0"] + a, ch["t0"] + z))

    for i, sc in enumerate(scenes):
        if per_scene[i]:
            sc["words"] = per_scene[i]
    log(f"phrase boundaries matched to real pauses: {total_m}/{total_b}")
    if ratios:
        log(f"Whisper confirmed {sum(ratios) / len(ratios):.0%} of words (inside their sentence windows)")
    finalize_times(scenes)
    return "whisper" if ratios else "pauses"


def finalize_times(scenes: list, gap_after_last: float = 0.45):
    """Turns speech times into visual scene start/end (cut slightly before each new sentence)."""
    for sc in scenes:
        if sc.get("words"):
            sc["speech_start"] = sc["words"][0][1]
            sc["speech_end"] = sc["words"][-1][2]
    for i, sc in enumerate(scenes):
        sc["start"] = 0.0 if i == 0 else max(scenes[i - 1]["speech_start"] + 0.5, sc["speech_start"] - 0.12)
    for i, sc in enumerate(scenes):
        sc["end"] = scenes[i + 1]["start"] if i + 1 < len(scenes) else sc["speech_end"] + gap_after_last
