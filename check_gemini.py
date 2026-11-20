"""Quick check before deploying: does the Gemini sign-in work, and do the three kinds of call work?

    python check_gemini.py

Makes three small calls: plain text, a tool call, and finding a part in a library photo.
"""

import json
from pathlib import Path

from PIL import Image

from faultlens import config, sam
from faultlens.gemini_client import client, text_part

print("Model:", config.AGENT_MODEL, "| sign-in:", "Vertex AI" if config.USE_VERTEX else "API key")

r = client().responses.create(model=config.AGENT_MODEL, input=[{"role": "user", "content": "Say OK."}])
print("1. Text:", r.output_text.strip()[:60], "| tokens in/out:", r.usage.input_tokens, r.usage.output_tokens)

tool = {"type": "function", "name": "report", "description": "Report the fault.",
        "parameters": {"type": "object", "properties": {"fault": {"type": "string"}}, "required": ["fault"]}}
r = client().responses.create(model=config.AGENT_MODEL, tools=[tool], reasoning={"effort": "low"}, input=[
    {"role": "system", "content": "You are a repair assistant."},
    {"role": "user", "content": [text_part("The outdoor fan does not spin. Call report.")]}])
calls = [i for i in r.output if i.type == "function_call"]
print("2. Tool call:", calls[0].name, json.loads(calls[0].arguments) if calls else "NO TOOL CALL")

photos = sorted(Path("library").glob("*/photos/*.jpg"))
if photos:
    boxes = sam.segment_image(Image.open(photos[0]), "copper pipe")
    print(f"3. Part finding on {photos[0]}: {len(boxes)} box(es)")

print("4. Which model answers each job (a different name on the right means it fell back):")
from faultlens.gemini_client import generate
for job, m in [("second check", config.SECOND_CHECK_MODEL), ("job cards", config.CARD_MODEL), ("voice", config.VOICE_MODEL)]:
    try:
        _, used = generate(m, "Say OK.")
        print(f"   {job}: wanted {m} -> answered by {used}")
    except Exception as e:
        print(f"   {job}: wanted {m} -> FAILED: {str(e)[:120]}")
print("Done.")
