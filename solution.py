"""Local JSONL adapter; replace the outer contract with the organizers' sample."""

import json
import os
import sys
from pathlib import Path

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
    corpus = os.getenv("PSB_CORPUS_PATH", str(Path(__file__).parent / "samples/psb-demo.json"))
    assistant = Assistant(KnowledgeBase.load(corpus))
    for line in sys.stdin:
        try:
            result = solve(json.loads(line), assistant)
        except (ValueError, TypeError, UnicodeError):
            result = {"status": "invalid_request", "message": "Некорректный запрос", "claims": [], "sources": []}
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
