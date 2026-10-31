"""The conversation loop: model <-> tools, with per-session history on disk."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from .data import ROOT
from .llm import LLM, GeminiLLM
from .prompt import build_system_prompt
from .tools import TOOL_SCHEMAS, call_tool

SESSIONS_DIR = ROOT / "sessions"
MAX_TOOL_ROUNDS = 6
HISTORY_LIMIT = 30  # messages sent back to the model on each turn
FALLBACK = (
    "Desculpe, tive um problema para consultar isso agora. Pode tentar de novo em instantes? "
    "Se preferir, fale com a equipe pelo WhatsApp (67) 3321-4500."
)


class Agent:
    def __init__(
        self,
        llm: LLM | None = None,
        sessions_dir: Path = SESSIONS_DIR,
        on_tool: Callable[[str, dict, dict], None] | None = None,
    ):
        self.llm = llm or GeminiLLM(build_system_prompt(), TOOL_SCHEMAS)
        self.sessions_dir = sessions_dir
        self.on_tool = on_tool

    # -- history -------------------------------------------------------------------
    # Only the visible conversation (customer and assistant text) is stored between turns.
    # Tool calls and results live inside a single turn: they are re-queried when needed,
    # which keeps stale prices or stock out of later answers.

    def _path(self, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id) or "default"
        return self.sessions_dir / f"{safe}.json"

    def load_history(self, session_id: str) -> list[dict[str, str]]:
        path = self._path(session_id)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, session_id: str, history: list[dict[str, str]]) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._path(session_id).write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")

    def reset(self, session_id: str) -> None:
        self._path(session_id).unlink(missing_ok=True)

    # -- one turn ------------------------------------------------------------------

    def respond(self, session_id: str, user_text: str) -> str:
        user_text = user_text.strip()
        if not user_text:
            return "Pode me dizer como posso ajudar?"
        history = self.load_history(session_id)
        reply, ok = self._run_turn(history[-HISTORY_LIMIT:], user_text)
        if ok:  # a failed turn is not stored, so the customer can simply retry
            history += [{"role": "user", "text": user_text}, {"role": "assistant", "text": reply}]
            self._save(session_id, history)
        return reply

    def _run_turn(self, history: list[dict[str, str]], user_text: str) -> tuple[str, bool]:
        try:
            state = self.llm.start(history, user_text)
            for _ in range(MAX_TOOL_ROUNDS):
                step = self.llm.step(state)
                if not step.tool_calls:
                    return (step.text, True) if step.text else (FALLBACK, False)
                results = []
                for call in step.tool_calls:
                    result = call_tool(call.name, call.args)
                    results.append(result)
                    if self.on_tool:
                        self.on_tool(call.name, call.args, result)
                self.llm.add_results(state, step.tool_calls, results)
            return FALLBACK, False
        except Exception as exc:  # noqa: BLE001 - network/quota errors must not crash the chat
            if self.on_tool:
                self.on_tool("llm_error", {}, {"erro": f"{type(exc).__name__}: {exc}"})
            return FALLBACK, False
