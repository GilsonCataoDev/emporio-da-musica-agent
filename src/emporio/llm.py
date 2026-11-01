"""LLM providers behind one small interface.

A turn is a loop: the model either answers or asks for tools; the agent runs the tools and
feeds the results back until the model answers. Provider-specific message objects stay
inside each class (`state` is opaque to the agent), which keeps Gemini details out of the
agent loop and lets tests run against a scripted fake model.
"""

from __future__ import annotations

import importlib
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

# Preview-era Gemini models are often overloaded (503/504), so the agent walks a chain:
# GEMINI_MODEL (if set) first, then these, each tried a couple of times before moving on.
DEFAULT_MODELS = (
    "gemini-3.6-flash", "gemini-3-flash-preview", "gemini-3.5-flash",
    "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash",
)
RETRY_CODES = {500, 502, 503, 504}  # 429 moves to the next model: free-tier quotas are per model and per day
ATTEMPTS_PER_MODEL = 2
BACKOFF_SECONDS = 2.0  # wait before the second attempt on the same model


def _network_errors() -> tuple[tuple[type[BaseException], ...], tuple[type[BaseException], ...]]:
    """(timeouts, other transport errors) raised by the SDK's HTTP client.

    The SDK does not wrap these in `errors.APIError`, so without this a slow or unreachable
    model would end the turn instead of moving on to the next model in the chain.
    """
    timeouts: list[type[BaseException]] = [TimeoutError]
    transport: list[type[BaseException]] = [ConnectionError]
    for name in ("httpx", "httpx2"):  # the SDK accepts either client
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        timeouts.append(module.TimeoutException)
        transport.append(module.TransportError)
    return tuple(timeouts), tuple(transport)


TIMEOUT_ERRORS, TRANSPORT_ERRORS = _network_errors()


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str = ""


@dataclass
class Step:
    """One model response: final text, or tool calls to run (possibly with some text)."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLM(Protocol):
    def start(self, history: list[dict[str, str]], user_text: str) -> Any: ...
    def step(self, state: Any) -> Step: ...
    def add_results(self, state: Any, calls: list[ToolCall], results: list[dict[str, Any]]) -> None: ...


class GeminiLLM:
    def __init__(self, system_prompt: str, tool_schemas: list[dict], model: str | None = None,
                 api_key: str | None = None, temperature: float = 0.3):
        from google import genai
        from google.genai import types

        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and add a key from "
                "https://aistudio.google.com/apikey"
            )
        self._types = types
        self._client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=45_000))  # ms
        preferred = model or os.environ.get("GEMINI_MODEL")
        self.models = [preferred, *[m for m in DEFAULT_MODELS if m != preferred]] if preferred else list(DEFAULT_MODELS)
        self.model = self.models[0]
        declarations = [
            types.FunctionDeclaration(
                name=s["name"], description=s["description"], parameters_json_schema=s["parameters"]
            )
            for s in tool_schemas
        ]
        self._config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(function_declarations=declarations)],
            temperature=temperature,
            # The agent loop runs the tools itself so every call is logged and bounded.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def start(self, history: list[dict[str, str]], user_text: str) -> list:
        t = self._types
        contents = [
            t.Content(role="user" if m["role"] == "user" else "model", parts=[t.Part(text=m["text"])])
            for m in history
        ]
        contents.append(t.Content(role="user", parts=[t.Part(text=user_text)]))
        return contents

    def step(self, state: list) -> Step:
        response = self._generate(state)
        if not response.candidates or not response.candidates[0].content:
            return Step(text="")
        content = response.candidates[0].content
        # Keep the model's own content object so provider metadata (e.g. thought signatures)
        # is sent back unchanged on the next step.
        state.append(content)
        text = "".join(p.text for p in (content.parts or []) if getattr(p, "text", None) and not getattr(p, "thought", False))
        calls = [
            ToolCall(name=p.function_call.name, args=dict(p.function_call.args or {}), id=p.function_call.id or "")
            for p in (content.parts or []) if getattr(p, "function_call", None)
        ]
        return Step(text=text.strip(), tool_calls=calls)

    def _generate(self, contents: list):
        """Call the model; on transient errors (overload, rate limit) retry, then try the next model.

        A model that answered once stays first for later calls. Errors that retrying cannot fix
        (bad request, auth) are raised right away. A missing model, an exhausted quota or a timeout
        moves on to the next model in the chain (a model that hung once will likely hang again).
        """
        from google.genai import errors

        last: Exception | None = None
        for index, model in enumerate(self.models):
            for attempt in range(1, ATTEMPTS_PER_MODEL + 1):
                try:
                    response = self._client.models.generate_content(
                        model=model, contents=contents, config=self._config
                    )
                    if index:
                        self.models.insert(0, self.models.pop(index))
                        self.model = model
                    return response
                except errors.APIError as exc:
                    last = exc
                    if exc.code in (404, 429):
                        break  # model unavailable or out of quota for this key: try the next one
                    if exc.code not in RETRY_CODES:
                        raise
                    if attempt < ATTEMPTS_PER_MODEL:
                        time.sleep(BACKOFF_SECONDS)
                except TIMEOUT_ERRORS as exc:
                    last = exc
                    break
                except TRANSPORT_ERRORS as exc:
                    last = exc
                    if attempt < ATTEMPTS_PER_MODEL:
                        time.sleep(BACKOFF_SECONDS)
        assert last is not None
        raise last

    def add_results(self, state: list, calls: list[ToolCall], results: list[dict[str, Any]]) -> None:
        t = self._types
        parts = [
            t.Part.from_function_response(name=c.name, response={"result": r})
            for c, r in zip(calls, results)
        ]
        state.append(t.Content(role="user", parts=parts))


class ScriptedLLM:
    """Test double: replays a fixed list of Steps and records what it was shown."""

    def __init__(self, steps: list[Step]):
        self._steps = list(steps)
        self.seen: list[dict] = []

    def start(self, history, user_text):
        return {"history": list(history), "user": user_text, "results": []}

    def step(self, state) -> Step:
        self.seen.append({"user": state["user"], "results": list(state["results"])})
        if not self._steps:
            raise AssertionError("ScriptedLLM ran out of steps")
        return self._steps.pop(0)

    def add_results(self, state, calls, results):
        state["results"].extend(results)
