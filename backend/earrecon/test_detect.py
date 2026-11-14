import json

import pytest
from PIL import Image

from earrecon import detect
from earrecon.detect import DetectError, detect_ear, parse

OK = json.dumps({"ear_visible": True, "side": "left", "box": [100, 50, 300, 400]})


# Catches the model's pixels being used on the wrong image: it sees a 1024 px downscale, but reconstruct.py cuts the ORIGINAL — an unscaled box lands on the wrong part of a big photo.
def test_box_is_scaled_back_to_the_original_photo(monkeypatch):
    monkeypatch.setattr(detect, "_ask", lambda b64: OK)
    d = detect_ear(Image.new("RGB", (2048, 1536)))  # downscaled 2x before asking
    assert d == {"box": [200, 100, 600, 800], "side": "left"}


# Catches a hallucinated or sliver box reaching SAM 2: no ear, a bad side, a box under 20 px, or prose with no JSON must be an error, never a guess.
@pytest.mark.parametrize("text", [
    "I can't see an ear.",
    json.dumps({"ear_visible": False, "side": "left", "box": [0, 0, 0, 0]}),
    json.dumps({"ear_visible": True, "side": "front", "box": [10, 10, 200, 200]}),
    json.dumps({"ear_visible": True, "side": "left", "box": [10, 10, 15, 200]}),
    json.dumps({"ear_visible": True, "side": "left", "box": "10,10,200,200"}),
])
def test_unusable_answers_are_errors(text):
    with pytest.raises(DetectError):
        parse(text, 500, 500)


# Catches a box poking outside the photo, or reversed corners, which reconstruct.py would index with.
def test_box_is_clamped_and_ordered():
    d = parse('Sure: {"ear_visible": true, "side": "right", "box": [480, 300, -20, 40]}', 500, 400)
    assert d["box"] == [0, 40, 480, 300] and d["side"] == "right"


# Catches silently running without credentials: the patient must be told, with a 503 the client can show.
def test_missing_key_is_a_503(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(DetectError) as e:
        detect_ear(Image.new("RGB", (100, 100)))
    assert e.value.status == 503
