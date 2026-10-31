"""Command-line chat: `python -m emporio.cli [--session NAME] [--debug]`."""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

from .agent import Agent
from .data import ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chat with the Empório da Música agent.")
    parser.add_argument("--session", default="default", help="conversation id; history is kept per id")
    parser.add_argument("--new", action="store_true", help="discard the saved history of this session")
    parser.add_argument("--debug", action="store_true", help="print each tool call and its result")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    def show_tool(name: str, call_args: dict, result: dict) -> None:
        if args.debug:
            print(f"  [tool] {name}({json.dumps(call_args, ensure_ascii=False)})")
            print(f"         -> {json.dumps(result, ensure_ascii=False)[:300]}")

    try:
        agent = Agent(on_tool=show_tool)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.new:
        agent.reset(args.session)

    print("Empório da Música. Digite sua mensagem (vazio ou 'sair' encerra).\n")
    if not agent.load_history(args.session):
        print(f"Maestro: {agent.respond(args.session, 'Olá')}\n")
    while True:
        try:
            text = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text or text.lower() in {"sair", "exit", "quit"}:
            return 0
        print(f"\nMaestro: {agent.respond(args.session, text)}\n")


if __name__ == "__main__":
    raise SystemExit(main())
