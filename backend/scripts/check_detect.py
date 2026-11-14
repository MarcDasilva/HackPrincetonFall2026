"""Run ear detection on real photos and draw what it found, to eyeball it. SENDS THE PHOTOS TO ANTHROPIC.

    ANTHROPIC_API_KEY=... .venv/bin/python scripts/check_detect.py OUT_DIR photo1.jpg photo2.png ...

Writes OUT_DIR/<name>_box.png (red box on the photo) and prints the side and box for each.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageOps

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from earrecon.detect import detect_ear  # noqa: E402

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
for path in sys.argv[2:]:
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    d = detect_ear(img)
    ImageDraw.Draw(img).rectangle(d["box"], outline=(255, 0, 0), width=max(3, img.width // 150))
    name = os.path.splitext(os.path.basename(path))[0]
    img.save(os.path.join(out, f"{name}_box.png"))
    print(f"{path}: side={d['side']} box={d['box']} (photo {img.width}x{img.height})")
