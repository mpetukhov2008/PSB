"""Organizer CSV entry point; --jsonl retains the independent local JSONL API."""

import argparse
import json
from pathlib import Path
import sys
from psb.config import corpus_path, load_environment

from psb.assistant import Assistant
from psb.corpus import load_corpus
from psb.submission import dialogue_request, find_inputs, run_csv


def solve(request, assistant):
    if isinstance(request, str):
        request = dialogue_request(request)
    if isinstance(request, dict) and "messages" in request:
        messages = request["messages"]
        if (not isinstance(messages, list) or not messages or not isinstance(messages[-1], dict)
                or messages[-1].get("role") != "user"):
            raise ValueError("Последняя реплика должна принадлежать пользователю")
        request = {**request, "question": messages[-1].get("content", ""),
                   "history": messages[:-1]}
    # A request carries all its state; no history is retained between calls.
    return assistant.answer(request)


def jsonl_main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        load_environment()
        assistant = Assistant(load_corpus(corpus_path()))
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


def main(argv=None):
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='ОПОРА: questions.csv -> submission.csv')
    parser.add_argument('--jsonl', action='store_true')
    parser.add_argument('--questions')
    parser.add_argument('--corpus')
    parser.add_argument('--output', default='submission.csv')
    parser.add_argument('--report', help='Локальный JSON-отчёт; не включать в сабмит')
    parser.add_argument('--offline', action='store_true', help='Только локальные выдержки, без LLM')
    args = parser.parse_args(argv)
    if args.jsonl:
        return jsonl_main()
    try:
        load_environment()
        root = Path(__file__).resolve().parent
        if args.questions:
            questions = Path(args.questions)
            corpus = Path(args.corpus) if args.corpus else corpus_path()
        else:
            questions, corpus = find_inputs(root)
            if args.corpus:
                corpus = Path(args.corpus)
        results = run_csv(questions, corpus, args.output, offline=args.offline, report=args.report)
        print(f'Создан {Path(args.output).name}: {len(results)} ответов; режим: ' +
              ('локальные выдержки' if args.offline else 'модель с проверкой'), flush=True)
        return 0
    except (ValueError, TypeError, OSError, KeyError):
        print('PSB: проверьте входные CSV/ZIP, .env и настройки API. Секреты не выводятся.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
