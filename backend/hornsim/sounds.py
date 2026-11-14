"""Everyday sound library for listening tests: one FSD50K clip for each of its 200 sound classes.

    python -m hornsim.sounds fetch      download ~200 clips into data/sounds and write catalog.json
    python -m hornsim.sounds            print label -> clip

FSD50K eval (Zenodo 4060432, CC BY / CC0 per clip) spans the AudioSet vocabulary: vehicles, music,
crowds, animals, nature, household, speech. Clips are mono 16-bit 44.1 kHz, cut to their loudest 5 s (shorter ones kept whole); callers resample, as
audio.tts does.
"""
import csv
import io
import json
import os
import struct
import sys
import time
import urllib.request
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import soundfile as sf

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "sounds")
CATALOG = os.path.join(ROOT, "catalog.json")
URL = "https://zenodo.org/api/records/4060432/files/{}/content"
PARTS = [URL.format("FSD50K.eval_audio.z01"), URL.format("FSD50K.eval_audio.zip")]
PART0_SIZE = 3 * 2**30   # Zenodo lists the .z01 at exactly 3072 MB.
CLIP_S = 5      # seconds kept per clip


def _get(url, start=None, end=None):
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"} if start is not None else {})
    for wait in [2, 5, 15, 30, 60, None]:
        try:
            with urllib.request.urlopen(req) as r:
                return r.read()
        except urllib.error.URLError as e:
            # Zenodo answers bursts with 429 and the network blips — back off rather than fail the fetch.
            if getattr(e, "code", 429) != 429 or wait is None:
                raise
            time.sleep(wait)


def _read_dir():
    """fname -> (disk, local header offset, method, compressed size), from the split archive's
    central directory. Python's zipfile cannot open multi-disk archives — hence the hand parse."""
    tail = urllib.request.urlopen(urllib.request.Request(PARTS[1], headers={"Range": "bytes=-65536"})).read()
    e = tail.rfind(b"PK\x05\x06")
    _, _, cd_disk, _, n, cd_size, cd_off, _ = struct.unpack("<4s4H2LH", tail[e:e + 22])
    cd = _get(PARTS[cd_disk], cd_off, cd_off + cd_size - 1)
    out, i = {}, 0
    for _ in range(n):
        f = struct.unpack("<4s6H3L5HLL", cd[i:i + 46])
        method, csize, nlen, elen, clen, disk, off = f[4], f[8], f[10], f[11], f[12], f[13], f[16]
        name = cd[i + 46:i + 46 + nlen].decode()
        out[os.path.basename(name)] = (disk, off, method, csize)
        i += 46 + nlen + elen + clen
    return out


def _span(disk, start, length):
    """Bytes from a split archive; an entry may run off the end of the .z01 into the .zip."""
    if disk == 0 and start + length > PART0_SIZE:
        return _get(PARTS[0], start, PART0_SIZE - 1) + _get(PARTS[1], 0, start + length - PART0_SIZE - 1)
    return _get(PARTS[disk], start, start + length - 1)


def _extract(entry):
    disk, off, method, csize = entry
    head = _span(disk, off, 30)
    nlen, elen = struct.unpack("<HH", head[26:30])
    # A header that ends exactly at the .z01 boundary pushes the data to the start of the .zip.
    start = off + 30 + nlen + elen
    data = _span(1, start - PART0_SIZE, csize) if disk == 0 and start >= PART0_SIZE else _span(disk, start, csize)
    return zlib.decompressobj(-15).decompress(data) if method == 8 else data


def choose(rows, vocab):
    """One distinct clip per class, the one with the fewest labels — the purest example of it.

    FSD50K tags each clip with its full ancestry, so a lone "Frog" clip reads "Frog,Animal,..."; fewest
    labels still prefers it over a frog heard under rain."""
    rows = sorted(rows, key=lambda r: (len(r["labels"].split(",")), r["fname"]))
    used, picks = set(), {}
    for label in vocab:
        r = next((r for r in rows if label in r["labels"].split(",") and r["fname"] not in used), None)
        if r:
            used.add(r["fname"])
            picks[label] = r["fname"]
    return picks


def loudest(x, fs, seconds=CLIP_S):
    """The highest-energy window of the clip — the first seconds are often silence or a fade-in."""
    n = int(seconds * fs)
    if len(x) <= n:
        return x
    e = np.convolve(x ** 2, np.ones(n), "valid")
    i = int(np.argmax(e))
    return x[i:i + n]


def fetch():
    os.makedirs(os.path.join(ROOT, "clips"), exist_ok=True)
    gt = zipfile.ZipFile(io.BytesIO(_get(URL.format("FSD50K.ground_truth.zip"))))
    rows = list(csv.DictReader(io.TextIOWrapper(gt.open("FSD50K.ground_truth/eval.csv"))))
    vocab = [r[1] for r in csv.reader(io.TextIOWrapper(gt.open("FSD50K.ground_truth/vocabulary.csv")))]
    picks = choose(rows, vocab)
    index = _read_dir()

    def one(item):
        label, fname = item
        path = f"clips/{label.lower()}.wav"
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            x, fs = sf.read(io.BytesIO(_extract(index[f"{fname}.wav"])), always_2d=True)
            sf.write(full, loudest(x.mean(axis=1), fs), fs, subtype="PCM_16")
        return label.lower(), path

    with ThreadPoolExecutor(4) as ex:
        cat = dict(ex.map(one, picks.items()))
    json.dump(dict(sorted(cat.items())), open(CATALOG, "w"), indent=0)


def catalog():
    return json.load(open(CATALOG))


def load(label):
    """(mono samples, fs) for a catalog label."""
    x, fs = sf.read(os.path.join(ROOT, catalog()[label]), always_2d=True)
    return x.mean(axis=1), fs


if __name__ == "__main__":
    if sys.argv[1:] == ["fetch"]:
        fetch()
    for label, path in catalog().items():
        print(label, path)
