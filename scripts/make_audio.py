"""
Makes all the video's audio from scratch with numpy (no samples, so nothing to
license): a backing track written to the video's structure, plus sound effects.

    .venv/bin/python scripts/make_audio.py

Writes WAV files to video/public/audio/.

The track is 120 bpm in A minor (Am F C G, one chord per bar), and its sections
follow the scenes: a sparse intro under the hook, a groove through the build,
a breakdown with a riser for "the catch", then the full groove, brighter for
the results, and a fade out.
"""

import json
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "video" / "public" / "audio"
RATE = 44100
BPM = 120
BEAT = 60 / BPM
BAR = 4 * BEAT
rng = np.random.default_rng(7)


def seconds(n):
    return int(n * RATE)


def save(name, samples, peak=0.9):
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim == 1:
        samples = np.stack([samples, samples], axis=1)
    loudest = np.max(np.abs(samples)) or 1.0
    samples = samples / loudest * peak
    pcm = (samples * 32767).astype(np.int16)
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / f"{name}.wav"), "wb") as file:
        file.setnchannels(2)
        file.setsampwidth(2)
        file.setframerate(RATE)
        file.writeframes(pcm.tobytes())


def t_axis(length):
    return np.arange(seconds(length)) / RATE


def envelope(length, attack=0.005, decay=0.2):
    t = t_axis(length)
    return np.minimum(1, t / max(attack, 1e-4)) * np.exp(-t / decay)


def lowpass(signal, cutoff):
    # One-pole filter: cheap, smooth, good enough for pads and noise.
    alpha = 1 - np.exp(-2 * np.pi * cutoff / RATE)
    out = np.empty_like(signal)
    acc = 0.0
    for index, value in enumerate(signal):
        acc += alpha * (value - acc)
        out[index] = acc
    return out


def highpass(signal, cutoff):
    return signal - lowpass(signal, cutoff)


def note(name):
    names = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4, "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1, "B": 2}
    pitch, octave = name[:-1], int(name[-1])
    return 440 * 2 ** ((names[pitch] + 12 * (octave - 4)) / 12)


# ---------------------------------------------------------------- effects

def golf_hit():
    # A sharp "tock": a click of filtered noise, a short woody body, and a
    # quick whoosh of the ball leaving.
    length = 0.5
    t = t_axis(length)
    click = highpass(rng.standard_normal(len(t)), 2500) * np.exp(-t / 0.004)
    body = np.sin(2 * np.pi * (900 * np.exp(-t / 0.03) + 300) * t) * np.exp(-t / 0.025)
    flight = lowpass(rng.standard_normal(len(t)), 3000) * np.exp(-((t - 0.12) / 0.09) ** 2) * 0.25
    return click * 1.2 + body + flight


def cup_drop():
    # The ball rattling round the cup: a few bright knocks, then a hollow thunk.
    length = 0.9
    signal = np.zeros(seconds(length))
    for start, pitch, level in [(0.0, 2600, 0.6), (0.07, 2350, 0.5), (0.13, 2500, 0.4), (0.2, 2200, 0.3)]:
        t = t_axis(0.12)
        knock = np.sin(2 * np.pi * pitch * t) * np.exp(-t / 0.02) * level
        signal[seconds(start):seconds(start) + len(t)] += knock
    t = t_axis(0.6)
    thunk = np.sin(2 * np.pi * 170 * t) * np.exp(-t / 0.12)
    signal[seconds(0.27):seconds(0.27) + len(t)] += thunk * 0.9
    return signal


def ace_sting():
    # The hole-in-one moment: a boom, a bright rising arpeggio of bells, and a
    # shimmer that rings out.
    length = 2.6
    signal = np.zeros(seconds(length))
    t = t_axis(1.2)
    boom = np.sin(2 * np.pi * (110 * np.exp(-t / 0.25) + 40) * t) * np.exp(-t / 0.4)
    signal[: len(t)] += boom * 1.1
    for index, name in enumerate(["A4", "C#5", "E5", "A5", "C#6", "E6"]):
        start = seconds(0.04 + index * 0.07)
        t = t_axis(1.8)
        bell = (np.sin(2 * np.pi * note(name) * t) + 0.4 * np.sin(2 * np.pi * note(name) * 2.01 * t)) * np.exp(-t / 0.5)
        end = min(len(signal), start + len(t))
        signal[start:end] += bell[: end - start] * 0.45
    t = t_axis(length)
    shimmer = highpass(rng.standard_normal(len(t)), 6000) * np.minimum(1, t / 0.3) * np.exp(-t / 0.8) * 0.35
    return signal + shimmer


def whoosh():
    length = 0.45
    t = t_axis(length)
    noise = rng.standard_normal(len(t))
    swell = np.sin(np.pi * t / length) ** 2
    return lowpass(noise, 1800) * swell + highpass(noise, 5000) * swell * 0.2


def click():
    t = t_axis(0.06)
    return highpass(rng.standard_normal(len(t)), 3000) * np.exp(-t / 0.006) + np.sin(2 * np.pi * 1800 * t) * np.exp(-t / 0.01) * 0.5


def tick():
    t = t_axis(0.03)
    return np.sin(2 * np.pi * 2400 * t) * np.exp(-t / 0.006)


def pop():
    t = t_axis(0.15)
    return np.sin(2 * np.pi * (660 * np.exp(-t / 0.04) + 520) * t) * np.exp(-t / 0.05)


def riser(length=2.0):
    t = t_axis(length)
    sweep = np.sin(2 * np.pi * (200 + 1400 * (t / length) ** 2) * t)
    noise = highpass(rng.standard_normal(len(t)), 2000) * (t / length) ** 2
    return (sweep * 0.5 + noise * 0.6) * (t / length) ** 1.5


# ---------------------------------------------------------------- music

def kick():
    t = t_axis(0.35)
    return np.sin(2 * np.pi * (45 + 100 * np.exp(-t / 0.03)) * t) * np.exp(-t / 0.18)


def clap():
    t = t_axis(0.25)
    noise = highpass(rng.standard_normal(len(t)), 1200)
    bursts = sum(np.exp(-np.maximum(0, t - d) / 0.01) * (t >= d) for d in (0, 0.012, 0.024))
    return noise * (bursts * 0.4 + np.exp(-t / 0.08) * 0.6)


def hat(open_hat=False):
    t = t_axis(0.12 if open_hat else 0.04)
    return highpass(rng.standard_normal(len(t)), 7000) * np.exp(-t / (0.05 if open_hat else 0.012))


def pad_chord(names, length):
    t = t_axis(length)
    sound = np.zeros(len(t))
    for name in names:
        for detune in (-0.3, 0.3):
            sound += np.sin(2 * np.pi * (note(name) + detune) * t)
    fade = np.minimum(1, t / 0.4) * np.minimum(1, (length - t) / 0.4)
    return sound * fade / len(names)


def bass_note(name, length):
    t = t_axis(length)
    freq = note(name)
    tone = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * 2 * freq * t)
    return tone * np.minimum(1, t / 0.01) * np.exp(-t / 0.35)


def pluck(name, length=0.25):
    t = t_axis(length)
    freq = note(name)
    tone = sum(np.sin(2 * np.pi * freq * k * t) / k for k in (1, 2, 3))
    return tone * np.exp(-t / 0.08)


CHORDS = [
    (["A3", "C4", "E4"], "A1", ["A4", "C5", "E5", "C5"]),
    (["F3", "A3", "C4"], "F1", ["F4", "A4", "C5", "A4"]),
    (["C3", "E3", "G3"], "C2", ["C5", "E5", "G5", "E5"]),
    (["G3", "B3", "D4"], "G1", ["G4", "B4", "D5", "B4"]),
]


def add(track, sound, at, level=1.0):
    start = seconds(at)
    if start >= len(track):
        return
    end = min(len(track), start + len(sound))
    track[start:end] += sound[: end - start] * level


def build_music(length, sections):
    """sections: list of (start, end, style) with style in intro/groove/break/full/outro."""
    track = np.zeros(seconds(length))
    drums = np.zeros(seconds(length))
    kick_sound, clap_sound, hat_sound, open_hat = kick(), clap(), hat(), hat(True)
    bar_count = int(np.ceil(length / BAR))
    for bar in range(bar_count):
        bar_start = bar * BAR
        style = next((s for a, b, s in sections if a <= bar_start < b), "outro")
        pad_names, bass_name, arp = CHORDS[bar % 4]
        pad_level = {"intro": 0.35, "groove": 0.25, "break": 0.45, "full": 0.25, "outro": 0.35}[style]
        add(track, pad_chord(pad_names, BAR), bar_start, pad_level)
        if style in ("groove", "full"):
            for beat in range(4):
                add(drums, kick_sound, bar_start + beat * BEAT, 1.0)
                add(drums, hat_sound, bar_start + beat * BEAT + BEAT / 2, 0.25)
                add(track, bass_note(bass_name, BEAT), bar_start + beat * BEAT + BEAT / 2, 0.55)
            add(drums, clap_sound, bar_start + BEAT, 0.5)
            add(drums, clap_sound, bar_start + 3 * BEAT, 0.5)
            for step in range(8):
                add(track, pluck(arp[step % 4], 0.3), bar_start + step * BEAT / 2, 0.18 if style == "groove" else 0.26)
            if style == "full":
                add(drums, open_hat, bar_start + 3.5 * BEAT, 0.2)
                for step in range(8):  # a second, offset arpeggio for extra lift
                    add(track, pluck(arp[(step + 2) % 4], 0.2), bar_start + step * BEAT / 2 + BEAT / 4, 0.1)
        elif style == "intro" and bar >= 2:
            for beat in range(4):
                add(drums, hat_sound, bar_start + beat * BEAT + BEAT / 2, 0.15)
            add(drums, kick_sound, bar_start, 0.7)
    track = lowpass(track, 6000)  # take the edge off the plucks
    mix = track * 0.8 + drums * 0.7
    fade_in = np.minimum(1, np.arange(len(mix)) / seconds(1.0))
    fade_out = np.minimum(1, (len(mix) - np.arange(len(mix))) / seconds(4.0))
    return mix * fade_in * fade_out


def main():
    scenes = json.loads((ROOT / "video" / "src" / "timing.json").read_text())["scenes"]
    cuts, clock = {}, 0.0  # scene name -> start, in seconds
    for name, length_seconds in scenes:
        cuts[name] = clock
        clock += length_seconds
    length = clock
    sections = [
        (0, cuts["TheGame"], "intro"),
        (cuts["TheGame"], cuts["TheWall"], "groove"),
        (cuts["TheWall"], cuts["Search"], "break"),
        (cuts["Search"], cuts["Results"], "groove"),
        (cuts["Results"], cuts["Outro"], "full"),
        (cuts["Outro"], length + 10, "outro"),
    ]
    music = build_music(length, sections)
    # A riser into the drop after "the catch".
    rise = riser(2.0)
    add(music, rise * 0.5, cuts["Search"] - 2.0)
    save("music", music, peak=0.8)
    for name, maker in [("hit", golf_hit), ("cup", cup_drop), ("ace", ace_sting), ("whoosh", whoosh),
                        ("click", click), ("tick", tick), ("pop", pop)]:
        save(name, maker())
    print("wrote", ", ".join(sorted(p.name for p in OUT.glob("*.wav"))))


if __name__ == "__main__":
    main()
