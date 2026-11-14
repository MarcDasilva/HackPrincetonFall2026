"""Test speech (macOS `say`, offline) and frequency-response filtering."""
import os
import subprocess
import tempfile

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


def tts(text, voice, fs):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.wav")
        subprocess.run(["say", "-v", voice, "-o", p, "--file-format=WAVE", f"--data-format=LEI16@{fs}", text], check=True)
        x, sr = sf.read(p)
    if sr != fs:
        x = resample_poly(x, fs, sr)
    x = trim(x)
    return x / rms(x)


def trim(x, thresh=1e-3, pad=0.05, fs=24000):
    nz = np.nonzero(np.abs(x) > thresh * np.abs(x).max())[0]
    a, b = max(0, nz[0] - int(pad * fs)), min(len(x), nz[-1] + int(pad * fs))
    return x[a:b]


def rms(x):
    return float(np.sqrt(np.mean(np.square(x))))


def babble(voices, text, fs, n_samples):
    """Sum of several talkers, each looped to length, normalised to RMS 1."""
    out = np.zeros(n_samples)
    for i, v in enumerate(voices):
        s = tts(text, v, fs)
        s = np.roll(np.resize(s, n_samples), int(i * 0.37 * fs))
        out += s
    return out / rms(out)


def apply_gain(x, fs, freqs_hz, gain_db):
    """Zero-phase filter: interpolate gain (dB) on log frequency and multiply the spectrum.

    Used for prescriptions now and for the horn's insertion gain in the design loop.
    """
    n = int(2 ** np.ceil(np.log2(len(x) + 1)))
    X = np.fft.rfft(x, n)
    f = np.fft.rfftfreq(n, 1 / fs)
    lf = np.log10(np.clip(f, freqs_hz[0], freqs_hz[-1]))
    g = np.interp(lf, np.log10(freqs_hz), gain_db)
    return np.fft.irfft(X * 10 ** (g / 20), n)[: len(x)]
