"""Find named parts in a photo with Gemini.

Gemini returns boxes as [ymin, xmin, ymax, xmax] on a 0-1000 scale; we turn them into pixels.
The rest of FaultLens reads the same fields as before: label, frame, object, x1, y1, x2, y2, w, h, conf.
(The file keeps its old name so the modules that import it do not change.)
"""

from __future__ import annotations

import io
import json
import re

from google.genai import types
from PIL import Image

from . import config
from .gemini_client import generate

PROMPT = ('Find every "{phrase}" in this photo of air-conditioning equipment. Answer with a JSON list only. '
          'Each entry: {{"box_2d": [ymin, xmin, ymax, xmax], "label": "{phrase}"}} with the numbers on a '
          "0-1000 scale. If there is none in the photo, answer [].")


def _to_pixels(entries, phrase: str, w: int, h: int) -> list[dict]:
    detections = []
    for i, e in enumerate(entries if isinstance(entries, list) else []):
        box = e.get("box_2d") if isinstance(e, dict) else None
        if not (isinstance(box, list) and len(box) == 4):
            continue
        try:
            y1, x1, y2, x2 = (min(max(float(v), 0.0), 1000.0) for v in box)
        except (TypeError, ValueError):
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        detections.append({"label": phrase, "frame": 0, "object": i,
                           "x1": x1 / 1000 * w, "y1": y1 / 1000 * h, "x2": x2 / 1000 * w, "y2": y2 / 1000 * h,
                           "w": w, "h": h, "conf": None})
    return detections


def _read_json(text: str):
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\[.*\]", text, re.S)
        try:
            return json.loads(m.group(0)) if m else []
        except ValueError:
            return []


def segment_image(image: Image.Image, phrase: str) -> list[dict]:
    """Return boxes for every match of `phrase` (for example 'condenser fan')."""
    if config.MOCK:
        return _mock_boxes(image, phrase)
    rgb = image.convert("RGB")
    w, h = rgb.size
    small = rgb.copy()
    small.thumbnail((1280, 1280))
    buf = io.BytesIO()
    small.save(buf, format="JPEG", quality=85)
    resp, _ = generate(
        config.VISION_MODEL,
        [types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"), PROMPT.format(phrase=phrase)],
        types.GenerateContentConfig(response_mime_type="application/json"),
    )
    # No matches is a normal result: an empty list, not an error.
    return _to_pixels(_read_json(resp.text), phrase, w, h)


def find_parts(image: Image.Image, phrases: list[str]) -> list[dict]:
    found = []
    for phrase in phrases:
        found.extend(segment_image(image, phrase))
    return found


def _mock_boxes(image: Image.Image, phrase: str) -> list[dict]:
    w, h = image.size
    seed = sum(map(ord, phrase)) % 5
    x1 = (0.08 + 0.15 * seed) * w
    y1 = (0.15 + 0.1 * seed) * h
    return [
        {
            "label": phrase, "frame": 0, "object": 0,
            "x1": x1, "y1": y1, "x2": min(x1 + 0.25 * w, w - 1), "y2": min(y1 + 0.25 * h, h - 1),
            "w": w, "h": h, "conf": 0.5,
        }
    ]
