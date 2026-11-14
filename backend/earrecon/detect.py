"""Which ear, and where: ask Claude (vision) for the ear's bounding box and side.

The box is SAM 2's prompt in reconstruct.py, and a box that clips the ear or swallows the face gives a ragged mask and a
bad mesh fit; the side decides whether the photo is mirrored first. A fixed guess cannot be right for both a close-up
and a far-away photo, so a model looks at the picture.

PRIVACY: this sends the patient's ear photo to Anthropic's API. app/main.py calls it ONLY when the request left the box
or side blank; a client that sends both never triggers a call. Needs ANTHROPIC_API_KEY.
"""
import base64
import io
import json
import os
import logging
import urllib.error
import urllib.request

from PIL import Image

log = logging.getLogger("uvicorn.error")
MODEL = os.environ.get("EAR_DETECT_MODEL", "claude-sonnet-5-5")
URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com") + "/v1/messages"
MAX_SIDE = 1024  # the model sees (and answers in the pixels of) this downscale; boxes are scaled back

PROMPT = """This is a photo of a person's ear. Reply with ONLY a JSON object, no other text:
{"ear_visible": true or false, "side": "left" or "right", "box": [x0, y0, x1, y1]}

- box: pixel coordinates in THIS image (origin top-left), tight around the WHOLE outer ear: the top of the rim (helix) to the bottom of the lobe, and from the outer rim to where the ear meets the head. Do not include hair or neck beyond the ear.
- side: the PERSON'S OWN ear. If the face is turned toward the image's LEFT edge you are looking at their LEFT ear; toward the RIGHT edge, their RIGHT ear.
- If no ear is clearly visible, set ear_visible to false and use [0, 0, 0, 0]."""


class DetectError(Exception):
    """`status` is the HTTP code app/main.py should answer with; the message is shown to the patient as is."""

    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def _ask(jpeg_b64):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise DetectError("Ear detection is not set up on the server (ANTHROPIC_API_KEY is missing).", 503)
    # Thinking is ON by default for this model and ate all 300 tokens on the first live call, leaving no text. The answer is one short JSON object: turn it off (this model rejects {"type": "disabled"}; "between_tools" is its off switch) and leave headroom.
    body = {"model": MODEL, "max_tokens": 1024, "thinking": {"type": "between_tools"}, "messages": [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": jpeg_b64}},
        {"type": "text", "text": PROMPT}]}]}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {
        "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return "".join(b.get("text", "") for b in json.load(r)["content"])
    except urllib.error.HTTPError as e:
        # The API's reason goes to the server log, not to the patient.
        log.warning("ear detection: Anthropic API %s %s", e.code, e.read()[:300])
        raise DetectError("Ear detection could not be reached. Try again.", 502)
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
        log.warning("ear detection: %r", e)
        raise DetectError("Ear detection could not be reached. Try again.", 502)


def parse(text, w, h):
    """The model's reply -> {"box": [x0, y0, x1, y1] in the ORIGINAL photo's pixels (clamped), "side": "left"|"right"}.
    Anything off — no JSON, no ear, a box that is not a box — is a DetectError, never a guess."""
    try:
        d = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except ValueError:
        raise DetectError("Could not read the ear detector's answer. Try again.", 502)
    if not d.get("ear_visible") or d.get("side") not in ("left", "right"):
        raise DetectError("No ear was found in the photo. Retake it with the whole ear in view.")
    try:
        x0, y0, x1, y1 = (float(v) for v in d["box"])
    except (KeyError, TypeError, ValueError):
        raise DetectError("Could not read the ear detector's answer. Try again.", 502)
    x0, x1 = max(0.0, min(x0, x1)), min(float(w), max(x0, x1))
    y0, y1 = max(0.0, min(y0, y1)), min(float(h), max(y0, y1))
    # reconstruct.py rejects boxes under 20 px; a sliver here means the model failed, not that the ear is tiny.
    if x1 - x0 < 20 or y1 - y0 < 20:
        raise DetectError("No ear was found in the photo. Retake it with the whole ear in view.")
    return {"box": [round(x0), round(y0), round(x1), round(y1)], "side": d["side"]}


def detect_ear(img):
    """img: RGB PIL image, already EXIF-rotated (the same pixels reconstruct.py will see)."""
    w, h = img.size
    k = min(1.0, MAX_SIDE / max(w, h))
    small = img.resize((round(w * k), round(h * k))) if k < 1 else img
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=90)
    d = parse(_ask(base64.b64encode(buf.getvalue()).decode()), *small.size)
    x0, y0, x1, y1 = (round(v / k) for v in d["box"])
    d["box"] = [x0, y0, min(w, x1), min(h, y1)]  # rounding after the upscale can land 1 px outside
    return d
