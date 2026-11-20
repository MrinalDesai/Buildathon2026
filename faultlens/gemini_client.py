"""Gemini behind the same call shape the rest of FaultLens already uses.

Every module calls `client().responses.create(model=..., input=..., tools=...)` and reads
`resp.output`, `resp.output_text` and `resp.usage`. This file keeps that shape and sends the
request to Gemini through Google's `google-genai` library, so no other module has to change.

Two ways to sign in, both read from the environment by the library itself:
- Gemini API key:  GEMINI_API_KEY=...
- Vertex AI:       GOOGLE_GENAI_USE_VERTEXAI=true, GOOGLE_CLOUD_PROJECT=..., GOOGLE_CLOUD_LOCATION=...
  (on Cloud Run the service account signs in, no key needed)
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import uuid
from functools import lru_cache
from types import SimpleNamespace

from google import genai
from google.genai import types
from PIL import Image

from . import config

LEVELS = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}


# ----------------------------------------------------------------------------- helpers kept from before

def image_to_data_url(image: Image.Image | str | bytes, max_side: int = 1280) -> str:
    """Return a base64 data URL. Large images are shrunk to save tokens."""
    if isinstance(image, str):
        image = Image.open(image)
    elif isinstance(image, bytes):
        image = Image.open(io.BytesIO(image))
    image = image.convert("RGB")
    image.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def file_to_data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


def text_part(text: str) -> dict:
    return {"type": "input_text", "text": text}


def image_part(image) -> dict:
    return {"type": "input_image", "image_url": image_to_data_url(image)}


# ----------------------------------------------------------------------------- Gemini

@lru_cache(maxsize=1)
def gemini() -> genai.Client:
    """The Google client. Raises a clear error if no sign-in is configured."""
    if not (config.GEMINI_API_KEY or config.USE_VERTEX):
        raise RuntimeError("No Gemini sign-in found. Set GEMINI_API_KEY in .env, or set "
                           "GOOGLE_GENAI_USE_VERTEXAI=true with GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION.")
    return genai.Client()   # reads the environment itself


def generate(model: str, contents, cfg=None):
    """One Gemini call. If `model` is not available to this account, ask AGENT_MODEL instead.
    Returns (response, name of the model that answered)."""
    try:
        return gemini().models.generate_content(model=model, contents=contents, config=cfg), model
    except Exception:
        if model == config.AGENT_MODEL:
            raise
        return gemini().models.generate_content(model=config.AGENT_MODEL, contents=contents, config=cfg), config.AGENT_MODEL


def _data_url_part(url: str) -> types.Part:
    head, _, b64 = url.partition(",")
    mime = head[5:].split(";")[0] or "image/jpeg"
    return types.Part.from_bytes(data=base64.b64decode(b64), mime_type=mime)


def _to_parts(content) -> list[types.Part]:
    if isinstance(content, str):
        return [types.Part(text=content)]
    out = []
    for p in content or []:
        kind = p.get("type", "")
        if kind in ("input_text", "output_text", "text"):
            out.append(types.Part(text=p.get("text", "")))
        elif kind == "input_image":
            url = p.get("image_url")
            if isinstance(url, dict):
                url = url.get("url", "")
            out.append(_data_url_part(url))
    return out


class _Responses:
    """Stands in for the OpenAI-style `responses` object."""

    def __init__(self):
        # Gemini will not accept a tool call back unless it is the exact part Gemini sent: the
        # parts of one reply carry a signature between them, and a rebuilt copy is rejected with
        # "Function call is missing a thought_signature". So keep each reply's parts whole.
        self._turns: dict[str, list[types.Part]] = {}   # turn id -> that reply's parts, in order
        self._calls: dict[str, str] = {}                # call id -> the turn it came from
        self._names: dict[str, str] = {}

    def _history(self, items: list) -> tuple[str | None, list[types.Content]]:
        system, contents = [], []
        done: set[str] = set()

        def add(role: str, parts: list[types.Part]):
            if not parts:
                return
            if contents and contents[-1].role == role:
                contents[-1].parts.extend(parts)
            else:
                contents.append(types.Content(role=role, parts=list(parts)))

        for item in items:
            kind = item.get("type", "message")
            if kind == "function_call":
                cid = item.get("call_id", "")
                self._names.setdefault(cid, item.get("name", ""))
                turn = self._calls.get(cid)
                if turn is None:   # not ours: rebuild it, the best we can do
                    add("model", [types.Part(function_call=types.FunctionCall(
                        name=item.get("name", ""), args=json.loads(item.get("arguments") or "{}")))])
                elif turn not in done:   # replay that whole reply once, parts and signatures intact
                    done.add(turn)
                    add("model", self._turns[turn])
            elif kind == "function_call_output":
                cid = item.get("call_id", "")
                try:
                    result = json.loads(item.get("output") or "null")
                except (TypeError, ValueError):
                    result = item.get("output")
                add("user", [types.Part(function_response=types.FunctionResponse(
                    name=self._names.get(cid, ""), response={"result": result}))])
            else:
                role = item.get("role", "user")
                if role == "system":
                    text = item.get("content")
                    system.append(text if isinstance(text, str) else
                                  "\n".join(p.get("text", "") for p in text or []))
                else:
                    add("model" if role == "assistant" else "user", _to_parts(item.get("content")))
        return ("\n\n".join(system) or None), contents

    def create(self, *, model: str, input, tools: list | None = None, reasoning: dict | None = None,
               **_ignored):
        if isinstance(input, str):
            input = [{"role": "user", "content": input}]
        system, contents = self._history(input)

        cfg: dict = {}
        if system:
            cfg["system_instruction"] = system
        if tools:
            cfg["tools"] = [types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t["name"], description=t.get("description", ""),
                                          parameters_json_schema=t.get("parameters") or {"type": "object"})
                for t in tools])]
            # We run the tools ourselves; and when only one tool is offered the model must call it.
            cfg["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
            if len(tools) == 1:
                cfg["tool_config"] = types.ToolConfig(function_calling_config=types.FunctionCallingConfig(
                    mode="ANY", allowed_function_names=[tools[0]["name"]]))

        level = LEVELS.get(str((reasoning or {}).get("effort", "")).lower())
        resp = None
        if level:
            try:
                resp, used = gemini().models.generate_content(
                    model=model, contents=contents,
                    config=types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level=level),
                                                       **cfg)), model
            except Exception:   # a model that does not take a thinking level: ask again without it
                resp = None
        if resp is None:
            resp, used = generate(model, contents, types.GenerateContentConfig(**cfg))
        return self._wrap(resp, used)

    def _wrap(self, resp, used: str = "") -> SimpleNamespace:
        output, texts = [], []
        cand = (resp.candidates or [None])[0]
        parts = list(cand.content.parts) if cand and cand.content and cand.content.parts else []
        turn = "turn_" + uuid.uuid4().hex[:12]
        self._turns[turn] = parts
        for part in parts:
            if part.function_call:
                cid = part.function_call.id or "call_" + uuid.uuid4().hex[:12]
                self._calls[cid] = turn
                self._names[cid] = part.function_call.name
                output.append(SimpleNamespace(type="function_call", call_id=cid, name=part.function_call.name,
                                              arguments=json.dumps(dict(part.function_call.args or {}))))
            elif part.text and not part.thought:
                texts.append(part.text)
        text = "".join(texts)
        if text:
            output.append(SimpleNamespace(type="message", role="assistant", text=text))
        um = resp.usage_metadata
        usage = SimpleNamespace(input_tokens=getattr(um, "prompt_token_count", 0) or 0,
                                output_tokens=getattr(um, "candidates_token_count", 0) or 0)
        return SimpleNamespace(output=output, output_text=text, usage=usage, model=used)


class _Client:
    def __init__(self):
        self.responses = _Responses()


@lru_cache(maxsize=1)
def client() -> _Client:
    gemini()   # fail early, with the clear message, if no sign-in is set
    return _Client()
