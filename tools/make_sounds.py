"""Builds the mod's sounds: wordless voice syllables and a few cues. Needs ffmpeg on PATH.

    python tools/make_sounds.py

Writes mono .ogg files into luanti/mods/npcasso/sounds/. Rerun after changing a recipe below.
"""
import math
import pathlib
import random
import subprocess
import tempfile
import wave

RATE = 22050
OUT = pathlib.Path(__file__).resolve().parent.parent / "luanti" / "mods" / "npcasso" / "sounds"


def tone(freq, dur, glide=0.0, harmonics=(1, .5, .25), decay=28, lowpass=.35, vibrato=0.0):
    """One soft note. glide bends the pitch by that fraction over its length."""
    out, phase, prev = [], 0.0, 0.0
    for i in range(int(RATE * dur)):
        t = i / RATE
        f = freq * (1 + glide * t / dur) * (1 + vibrato * math.sin(2 * math.pi * 7 * t))
        phase += 2 * math.pi * f / RATE
        wave_ = sum(a * math.sin(phase * (k + 1)) for k, a in enumerate(harmonics))
        prev += lowpass * (wave_ * (1 - math.exp(-t * 700)) * math.exp(-t * decay) - prev)
        out.append(prev)
    return out


def melody(notes, gap=0.0, **kw):
    out = []
    for freq, dur in notes:
        out += tone(freq, dur, **kw) + [0.0] * int(RATE * gap)
    return out


def scream(dur=.9):
    """A sharp rise to a ragged held note that tails off: rich harmonics, a shake, and some breath."""
    rng, out, phase, prev = random.Random(7), [], 0.0, 0.0
    for i in range(int(RATE * dur)):
        t = i / RATE
        f = (500 + 450 * min(t / .12, 1) - 350 * max(t - .5, 0)) * (1 + .05 * math.sin(2 * math.pi * 9 * t))
        phase += 2 * math.pi * f / RATE
        voice = sum(a * math.sin(phase * (k + 1)) for k, a in enumerate((1, .8, .7, .5, .4, .3)))
        env = min(t / .02, 1) * min((dur - t) / .25, 1)
        prev += .55 * ((voice + rng.uniform(-1.2, 1.2)) * env - prev)
        out.append(prev)
    return out


def gasp(dur=.3):
    """A quick breath in: noise that swells and cuts."""
    rng, out, prev = random.Random(3), [], 0.0
    for i in range(int(RATE * dur)):
        t = i / RATE
        prev += .25 * (rng.uniform(-1, 1) * math.sin(math.pi * min(t / dur, 1) ** .6) - prev)
        out.append(prev)
    return out


def wind(seconds=12):
    """A loop of cold wind: noise whose brightness and loudness swell and fall in whole cycles, so it joins up."""
    rng, n = random.Random(11), RATE * seconds
    noise = [rng.uniform(-1, 1) for _ in range(n)]
    out, prev = [], 0.0
    for lap in range(2):  # the second lap starts from where the first ended, so the seam is clean
        for i in range(n):
            t = i / RATE
            gust = .5 + .5 * math.sin(2 * math.pi * t / seconds * 2 + 1) * math.sin(2 * math.pi * t / seconds * 3)
            prev += (.02 + .10 * gust) * (noise[i] - prev)
            if lap:
                out.append(prev * (.35 + .65 * gust))
    return out


def save(name, samples):
    peak = max(abs(s) for s in samples) or 1
    with tempfile.TemporaryDirectory() as tmp:
        wav = pathlib.Path(tmp) / f"{name}.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
            w.writeframes(b"".join(int(s / peak * 26000).to_bytes(2, "little", signed=True) for s in samples))
        OUT.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ac", "1", "-c:a", "libvorbis",
                        "-q:a", "3", str(OUT / f"{name}.ogg")], check=True)


# (pitch Hz, glide, harmonics, lowpass, length): eight vowel-ish colours. A villager's own pitch is set in game.
SYLLABLES = [(300, .10, (1, .6, .3), .30, .10), (340, -.08, (1, .4, .5), .35, .09),
             (380, .15, (1, .7, .2), .25, .08), (420, .00, (1, .3, .6), .40, .09),
             (460, -.12, (1, .5, .3), .30, .07), (500, .08, (1, .2, .5), .45, .08),
             (350, .20, (1, .8, .4), .28, .10), (400, -.05, (1, .5, .5), .35, .08)]

if __name__ == "__main__":
    for i, (f, g, h, lp, d) in enumerate(SYLLABLES, 1):
        save(f"npcasso_syl_{i}", tone(f, d, g, h, 28, lp))
    bell = dict(harmonics=(1, .3, .1), decay=7, lowpass=.45)  # A minor: kind, and a little sad
    save("npcasso_notice", melody([(880, .14), (1047, .3)], **bell))
    save("npcasso_accept", melody([(440, .14), (523, .14), (659, .4)], **bell))
    save("npcasso_done", melody([(440, .14), (523, .14), (659, .14), (880, .8)], **bell))
    save("npcasso_wind", wind())
    save("npcasso_scream", scream())
    save("npcasso_gasp", gasp())
    print(f"wrote {len(list(OUT.glob('*.ogg')))} sounds to {OUT}")
