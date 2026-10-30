import numpy as np, subprocess, sys
SR = 44100
def midi(n): return 440.0 * 2 ** ((n - 69) / 12)
def onepole(x, cutoff):
    a = np.exp(-2 * np.pi * cutoff / SR); y = np.empty_like(x); acc = 0.0
    # vectorised enough via lfilter-like loop on chunks
    from math import isfinite
    b = 1 - a
    for i in range(len(x)):
        acc = b * x[i] + a * acc; y[i] = acc
    return y
try:
    from scipy.signal import lfilter
    def lp(x, cutoff):
        a = np.exp(-2*np.pi*cutoff/SR); return lfilter([1-a], [1, -a], x)
except ImportError:
    lp = onepole
def saw(f, t, phase=0.0): return 2 * ((f * t + phase) % 1) - 1
def tri(f, t): return 2 * np.abs(saw(f, t)) - 1
def env_adsr(n, a, r):
    e = np.ones(n); na, nr = min(int(a*SR), n // 2), min(int(r*SR), n // 2)
    if na: e[:na] = np.linspace(0, 1, na)
    if nr: e[-nr:] *= np.linspace(1, 0, nr)
    return e

def track(name, chords, bpm, bars_per_chord, mood_cut, pulse=True, kick=False, seed=0, length=150):
    rng = np.random.default_rng(seed)
    chord_len = 60 / bpm * 4 * bars_per_chord
    n_total = int(length * SR)
    L = np.zeros(n_total); Rr = np.zeros(n_total)
    t_all = np.arange(n_total) / SR
    k = 0; start = 0.0
    while start < length:
        ch = chords[k % len(chords)]
        s, e = int(start * SR), min(n_total, int((start + chord_len + 1.5) * SR))
        t = t_all[s:e] - start
        n = e - s
        env = env_adsr(n, 1.8, 2.2)
        pad_l = np.zeros(n); pad_r = np.zeros(n)
        for note in ch:
            f = midi(note)
            pad_l += saw(f * 0.997, t, 0.1) + 0.6 * tri(f * 2.003, t)
            pad_r += saw(f * 1.003, t, 0.4) + 0.6 * tri(f * 1.997, t)
        cut = mood_cut * (1 + 0.25 * np.sin(2 * np.pi * 0.05 * (t + start)))
        pad_l = lp(pad_l, mood_cut) * env / len(ch); pad_r = lp(pad_r, mood_cut) * env / len(ch)
        L[s:e] += 0.32 * pad_l; Rr[s:e] += 0.32 * pad_r
        # sub bass on the root
        bass = np.sin(2 * np.pi * midi(ch[0] - 12) * t) * env
        L[s:e] += 0.22 * bass; Rr[s:e] += 0.22 * bass
        start += chord_len; k += 1
    if pulse:   # soft arpeggio pluck, eighth notes
        step = 60 / bpm / 2; i = 0; tt = 0.0
        while tt < length - 1:
            ci = int(tt // chord_len) % len(chords); ch = chords[ci]
            note = ch[[0, 1, 2, 1, 2, 3 % len(ch), 2, 1][i % 8] % len(ch)] + 12
            s = int(tt * SR); n = int(0.6 * SR); e = min(n_total, s + n); t = np.arange(e - s) / SR
            p = np.sin(2*np.pi*midi(note)*t) * np.exp(-t * 7) * (0.7 + 0.3 * rng.random())
            pan = 0.5 + 0.35 * np.sin(i * 0.7)
            L[s:e] += 0.10 * p * (1 - pan); Rr[s:e] += 0.10 * p * pan
            tt += step; i += 1
    if kick:
        beat = 60 / bpm; tt = 0.0
        while tt < length - 1:
            s = int(tt * SR); n = int(0.35 * SR); e = min(n_total, s + n); t = np.arange(e - s) / SR
            f = 45 + 70 * np.exp(-t * 30)
            kk = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)
            L[s:e] += 0.18 * kk; Rr[s:e] += 0.18 * kk
            tt += beat * 2
    mix = np.stack([L, Rr], axis=1)
    fade = int(2.5 * SR)
    mix[:fade] *= np.linspace(0, 1, fade)[:, None]; mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
    mix /= np.max(np.abs(mix)) + 1e-9
    raw = (mix * 0.8 * 32767).astype(np.int16).tobytes()
    out = f"{name}.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    "-af", "aecho=0.8:0.85:60|120|240:0.35|0.25|0.18,highpass=f=35,loudnorm=I=-20:TP=-2:LRA=9",
                    "-ar", "44100", "-b:a", "160k", out], input=raw, check=True)
    print("made", out)

# MIDI notes: A2=45, C3=48, D3=50, E3=52, F3=53, G3=55, A3=57, Bb3=58, C4=60
tracks = [
  ("documentary-tension",  [[45,57,60,64],[41,57,60,65],[48,55,60,64],[43,55,59,62]], 84, 2, 900, True,  False, 1),
  ("rise-and-grow",        [[48,55,60,64],[43,55,59,62],[45,57,60,64],[41,57,60,65]], 92, 2, 1100, True, True, 2),
  ("dark-collapse",        [[38,50,53,57],[34,50,53,58],[41,53,57,60],[36,48,52,55]], 72, 2, 700, True,  False, 3),
  ("mystery-investigation",[[40,52,55,59],[36,52,55,60],[38,50,54,57],[35,47,54,59]], 78, 2, 800, True,  False, 4),
  ("corporate-pulse",      [[45,57,60,64],[48,55,60,64],[43,55,59,62],[41,57,60,65]], 100, 1, 1300, True, True, 5),
  ("reflective-lesson",    [[41,53,57,60],[48,55,60,64],[45,57,60,64],[43,55,59,62]], 70, 2, 950, False, False, 6),
]
for t in tracks:
    track(*t)
