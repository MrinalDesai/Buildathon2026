"""Central settings. Everything comes from environment variables (.env)."""

import os

from dotenv import load_dotenv

load_dotenv()

# Sign-in for Gemini. Either a Gemini API key, or Vertex AI (used on Cloud Run).
# Google's library reads these names from the environment by itself.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
USE_VERTEX = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes")

# Main reasoning agent.
AGENT_MODEL = os.getenv("AGENT_MODEL", "gemini-3.8-flash")

# Part finding in photos (boxes). Same model unless set otherwise.
VISION_MODEL = os.getenv("VISION_MODEL", "") or AGENT_MODEL
SAM_MODEL = VISION_MODEL   # old name, still read by the web page

# Speech to text (recorded WAV files): Google's speech-to-text model.
VOICE_MODEL = os.getenv("VOICE_MODEL", "gemini-3.5-transcribe")

# Second check of every diagnosis: a different, larger model, so the check is independent.
SECOND_CHECK_MODEL = os.getenv("SECOND_CHECK_MODEL", "gemini-4-argon")

# Reading handwritten job cards: a small, fast model is enough.
CARD_MODEL = os.getenv("CARD_MODEL", "gemini-3.5-flash-lite")

# If one of the models above is not available to this account, the call is repeated on AGENT_MODEL
# and the answer is labelled with the model that really answered.

# Independent checker. Leave these three empty: the checker then runs on Gemini with its own,
# skeptical prompt. (They can point the checker at another OpenAI-style host.)
CHECKER_BASE_URL = os.getenv("CHECKER_BASE_URL", "")
CHECKER_API_KEY = os.getenv("CHECKER_API_KEY", "")
CHECKER_MODEL = os.getenv("CHECKER_MODEL", "")
if not CHECKER_API_KEY or CHECKER_API_KEY.startswith("your-"):
    # No other host set: run the checker on Gemini.
    CHECKER_BASE_URL = CHECKER_API_KEY = CHECKER_MODEL = ""

# Optional second host, left over from the earlier build. Leave the key empty.
FIREWORKS_BASE_URL = os.getenv("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1")
FIREWORKS_API_KEY = os.getenv("FIREWORKS_API_KEY", "")
FIREWORKS_MODEL = os.getenv("FIREWORKS_MODEL", "accounts/fireworks/models/muse-spark-open")

# Which equipment profile to load from faultlens/knowledge/<name>.yaml
EQUIPMENT_PROFILE = os.getenv("EQUIPMENT_PROFILE", "split_ac")

# Offline mode: no API calls, canned answers. For building the UI and tests
# while the API account is unavailable. Never use for results you report.
MOCK = os.getenv("FAULTLENS_MOCK", "0") == "1"

# Reasoning effort for the step-by-step coach (low, medium, high). Medium keeps turns quick.
COACH_REASONING = os.getenv("COACH_REASONING", "medium")

# Agent loop limits.
MAX_AGENT_TURNS = int(os.getenv("MAX_AGENT_TURNS", "8"))
KEYFRAMES_PER_VIDEO = int(os.getenv("KEYFRAMES_PER_VIDEO", "4"))

# Set by `python -m faultlens.checker` once a sound format is proven to reach the checker model.
CHECKER_AUDIO_FORMAT = os.getenv("CHECKER_AUDIO_FORMAT", "").strip()

# Public demo (the Cloud Run deployment). Paid model calls are limited per visitor and per day, and the
# full test-set run is switched off (the saved run is shown instead).
PUBLIC_DEMO = os.getenv("PUBLIC_DEMO", "0") == "1"
VISITOR_CALLS_PER_HOUR = int(os.getenv("VISITOR_CALLS_PER_HOUR", "60"))
DAILY_CALLS = int(os.getenv("DAILY_CALLS", "800"))
