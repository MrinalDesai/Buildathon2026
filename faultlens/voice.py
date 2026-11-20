"""Spoken notes to text with Gemini.

The recording goes to Gemini as audio with one instruction: write down what was said.
Typed notes always work as a fallback.
"""

from __future__ import annotations

import io
import wave

from google.genai import types

from . import config
from .gemini_client import generate

PROMPT = ("Write down exactly what the technician says in this recording. Give the words only, in the language "
          "spoken, with no comments. If nothing is said, answer with an empty line.")


def check_wav(data: bytes) -> str | None:
    """Return a problem description, or None if the file is a readable WAV."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            if w.getnframes() == 0:
                return "The recording is empty."
    except (wave.Error, EOFError):
        return "Audio must be a WAV file."
    return None


def transcribe(data: bytes) -> str:
    if config.MOCK:
        return "Outdoor fan is not spinning, compressor is humming, the unit is blowing warm air."

    problem = check_wav(data)
    if problem:
        raise ValueError(problem + " Convert with: ffmpeg -i in.m4a -ac 1 -ar 16000 out.wav")

    audio = [types.Part.from_bytes(data=data, mime_type="audio/wav"), PROMPT]
    resp, used = generate(config.VOICE_MODEL, audio)
    text = (resp.text or "").strip()
    if not text and used != config.AGENT_MODEL:   # the speech model gave nothing back: ask the main model
        text = (generate(config.AGENT_MODEL, audio)[0].text or "").strip()
    return text
