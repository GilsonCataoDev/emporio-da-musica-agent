"""LLM providers behind one small interface.

A turn is a loop: the model either answers or asks for tools; the agent runs the tools and
feeds the results back until the model answers. Provider-specific message objects stay
inside each class (`state` is opaque to the agent), which keeps Gemini details out of the
agent loop and lets tests run against a scripted fake model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MODEL = "gemini-2.5-flash"


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
        self._client = genai.Client(api_key=key)
        self.model = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
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
        response = self._client.models.generate_content(
            model=self.model, contents=state, config=self._config
        )
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
