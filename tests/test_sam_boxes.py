"""Tests for bounding box conversion and JSON response parsing in faultlens.sam."""

import pytest
from faultlens.sam import _read_json, _to_pixels


def test_normal_box_converts_to_right_pixels_2000x1000():
    # Gemini returns [ymin, xmin, ymax, xmax] on a 0-1000 scale
    # Image size: w=2000, h=1000
    entries = [
        {"box_2d": [100, 200, 500, 600], "label": "condenser fan"}
    ]
    detections = _to_pixels(entries, phrase="condenser fan", w=2000, h=1000)

    assert len(detections) == 1
    det = detections[0]
    assert det["label"] == "condenser fan"
    assert det["frame"] == 0
    assert det["object"] == 0
    # ymin=100 -> y1 = 100 / 1000 * 1000 = 100.0
    # xmin=200 -> x1 = 200 / 1000 * 2000 = 400.0
    # ymax=500 -> y2 = 500 / 1000 * 1000 = 500.0
    # xmax=600 -> x2 = 600 / 1000 * 2000 = 1200.0
    assert det["x1"] == 400.0
    assert det["y1"] == 100.0
    assert det["x2"] == 1200.0
    assert det["y2"] == 500.0
    assert det["w"] == 2000
    assert det["h"] == 1000
    assert det["conf"] is None


def test_values_outside_0_1000_are_clamped():
    # Negative coordinates clamped to 0.0, coordinates above 1000 clamped to 1000.0
    entries = [
        {"box_2d": [-100, -50, 1200, 1500]}
    ]
    detections = _to_pixels(entries, phrase="compressor", w=2000, h=1000)

    assert len(detections) == 1
    det = detections[0]
    # Clamped: y1=0.0, x1=0.0, y2=1000.0, x2=1000.0
    # x1 = 0 / 1000 * 2000 = 0.0
    # y1 = 0 / 1000 * 1000 = 0.0
    # x2 = 1000 / 1000 * 2000 = 2000.0
    # y2 = 1000 / 1000 * 1000 = 1000.0
    assert det["x1"] == 0.0
    assert det["y1"] == 0.0
    assert det["x2"] == 2000.0
    assert det["y2"] == 1000.0


def test_box_with_x2_le_x1_or_y2_le_y1_dropped():
    entries = [
        {"box_2d": [100, 200, 500, 200]},   # x2 == x1 (200 == 200)
        {"box_2d": [100, 500, 500, 200]},   # x2 < x1 (200 < 500)
        {"box_2d": [300, 200, 300, 600]},   # y2 == y1 (300 == 300)
        {"box_2d": [500, 200, 100, 600]},   # y2 < y1 (100 < 500)
        {"box_2d": [1100, 200, 1200, 600]},  # y1 and y2 both > 1000 -> clamped to 1000, y2 <= y1
        {"box_2d": [100, -200, 500, -100]},  # x1 and x2 both < 0 -> clamped to 0, x2 <= x1
    ]
    detections = _to_pixels(entries, phrase="fan", w=2000, h=1000)
    assert detections == []

    # Also verify that a valid box alongside invalid ones is kept
    mixed = [
        {"box_2d": [100, 200, 500, 200]},  # invalid
        {"box_2d": [100, 200, 500, 600]},  # valid
    ]
    result = _to_pixels(mixed, phrase="fan", w=2000, h=1000)
    assert len(result) == 1
    assert result[0]["object"] == 1
    assert result[0]["x1"] == 400.0
    assert result[0]["x2"] == 1200.0


def test_malformed_entry_is_skipped():
    entries = [
        {"label": "missing_box"},               # missing box_2d
        {"box_2d": "not_a_list"},               # box_2d is not a list
        {"box_2d": [100, 200, 300]},           # wrong length (3)
        {"box_2d": [100, 200, 300, 400, 500]},  # wrong length (5)
        {"box_2d": []},                          # wrong length (0)
        {"box_2d": ["a", "b", "c", "d"]},       # non-numeric strings
        {"box_2d": [100, None, 300, 400]},      # non-numeric None
        {"box_2d": [100, [200], 300, 400]},     # non-numeric nested list
        None,                                    # non-dict entry
        "just a string",                         # non-dict entry
        42,                                      # non-dict entry
        {"box_2d": [100, 200, 300, 400]},      # valid entry
    ]
    detections = _to_pixels(entries, phrase="filter", w=2000, h=1000)
    assert len(detections) == 1
    assert detections[0]["object"] == 11
    assert detections[0]["label"] == "filter"

    # Also check when entries itself is not a list
    assert _to_pixels(None, phrase="filter", w=2000, h=1000) == []
    assert _to_pixels({}, phrase="filter", w=2000, h=1000) == []
    assert _to_pixels("invalid", phrase="filter", w=2000, h=1000) == []


def test_read_json_bare_json():
    bare_list = '[{"box_2d": [100, 200, 300, 400], "label": "valve"}]'
    assert _read_json(bare_list) == [{"box_2d": [100, 200, 300, 400], "label": "valve"}]

    bare_empty = "[]"
    assert _read_json(bare_empty) == []


def test_read_json_inside_prose():
    # Markdown code block with prose
    markdown_text = (
        "Here are the detected parts in the image:\n"
        "```json\n"
        '[{"box_2d": [50, 100, 250, 400], "label": "capacitor"}]\n'
        "```\n"
        "Hope this helps!"
    )
    assert _read_json(markdown_text) == [{"box_2d": [50, 100, 250, 400], "label": "capacitor"}]

    # Inline text surrounding the JSON
    prose_text = (
        "I found the following components: "
        '[{"box_2d": [0, 0, 500, 500]}] '
        "in the provided image."
    )
    assert _read_json(prose_text) == [{"box_2d": [0, 0, 500, 500]}]


def test_read_json_garbage_returns_empty_list():
    assert _read_json("") == []
    assert _read_json(None) == []
    assert _read_json("   \n\t  ") == []
    assert _read_json("No items could be located in this image.") == []
    assert _read_json("Here is [unclosed json array") == []
    assert _read_json("Invalid syntax: [ { 'single_quote': 123 } ]") == []
    assert _read_json("Random chars !@#$%^&*()") == []
