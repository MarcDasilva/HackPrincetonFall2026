"""Checks of the HASPI level convention and the shipped speech clips. Run from backend/: .venv/bin/python -m pytest tests -q"""
import os

import numpy as np
import pytest
import soundfile as sf
from clarity.evaluator.haspi import haspi_v2

from hornsim import context, scoring
from hornsim.audio import rms

S = context.load_defaults()["speech"]
AG = scoring.audiogram(context.load_defaults()["patient"]["audiogram_db_hl"])    # the example sloping loss
LEVELS = (50, 65, 80)


def clip(name):
    x, fs = sf.read(os.path.join(context.SPEECH_CACHE, name + ".wav"))
    assert fs == S["sample_rate"]
    return x


@pytest.fixture(scope="module")
def unaided():
    """Unaided HASPI [clip, level] for the shipped clean clips and babble mixtures."""
    clean = [clip(f"clean_{i + 1}") for i in range(len(S["clean"]))]
    noisy = [(clip(f"babble_{i + 1}_talker"), clip(f"babble_{i + 1}_noise") * 10 ** (-c["snr_db"] / 20))
             for i, c in enumerate(S["noisy"])]
    score = lambda ref, heard: [scoring.haspi(ref, heard, S["sample_rate"], AG, L) for L in LEVELS]
    return np.array([score(x, x) for x in clean]), np.array([score(x, x + b) for x, b in noisy])


def test_every_configured_clip_is_shipped_at_rms_1():
    names = [f"clean_{i + 1}" for i in range(len(S["clean"]))]
    names += [f"babble_{i + 1}_{part}" for i in range(len(S["noisy"])) for part in ("talker", "noise")]
    assert len(S["noisy"]) >= 4
    for n in names:
        assert abs(rms(clip(n)) - 1) < 1e-3, n
    for i in range(len(S["noisy"])):
        assert len(clip(f"babble_{i + 1}_talker")) == len(clip(f"babble_{i + 1}_noise"))


def test_reference_stays_at_65_db_spl_and_only_the_heard_signal_moves():
    x = clip("clean_1")
    np.random.seed(0)
    direct, _ = haspi_v2(x, 24000, x * 10 ** (-15 / 20), 24000, AG, level1=65)
    assert scoring.haspi(x, x, 24000, AG, 50) == pytest.approx(float(direct), abs=1e-9)
    assert scoring.haspi(x, x, 24000, AG, 65) == pytest.approx(scoring.haspi(x, x, 24000, AG, 65), abs=1e-9)   # repeats


def test_unaided_clean_speech_gets_easier_with_level(unaided):
    clean = unaided[0].mean(0)
    assert clean[0] < clean[1] < clean[2]
    assert clean[2] > 0.95 and clean[0] < 0.7             # loud speech is audible to this listener, soft speech is not


def test_unaided_babble_average_rises_with_level_and_sits_off_the_floor(unaided):
    babble = unaided[1].mean(0)
    assert babble[0] + 0.05 < babble[1] < babble[2] - 0.05
    assert babble[0] > 0.2 and babble[2] < 0.9            # room to rank designs both ways at every level
    assert np.all(babble < unaided[0].mean(0))            # babble is harder than quiet
