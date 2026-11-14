"""Local JSONL adapter; replace the outer contract with the organizers' sample."""

import json
import sys
from psb.config import corpus_path, load_environment

from psb.assistant import Assistant
from psb.knowledge import KnowledgeBase


def solve(request, assistant):
    if isinstance(request, str):
        request = {"question": request}
    if isinstance(request, dict) and "messages" in request:
        messages = request["messages"]
        if (not isinstance(messages, list) or not messages or not isinstance(messages[-1], dict)
                or messages[-1].get("role") != "user"):
            raise ValueError("Последняя реплика должна принадлежать пользователю")
        request = {**request, "question": messages[-1].get("content", ""),
                   "history": messages[:-1]}
    # A request carries all its state; no history is retained between calls.
    return assistant.answer(request)


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        load_environment()
        assistant = Assistant(KnowledgeBase.load(corpus_path()))
    except (ValueError, TypeError, OSError):
        print("PSB: проверьте .env и базу знаний", file=sys.stderr)
        return 1
    while True:
        line = sys.stdin.readline(100001)
        if not line:
            break
        try:
            if len(line) > 100000:
                # Drain this case only; the next line remains an independent request.
                while line and not line.endswith("\n"):
                    line = sys.stdin.readline(100001)
                raise ValueError("Слишком длинная строка JSONL")
            result = solve(json.loads(line), assistant)
        except (ValueError, TypeError, UnicodeError):
            result = {"status": "invalid_request", "message": "Некорректный запрос", "claims": [], "sources": []}
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

