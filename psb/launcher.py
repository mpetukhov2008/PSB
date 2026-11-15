"""Local quick start: validate config, select an available port, open the browser."""

import argparse
import errno
import sys
import threading
import webbrowser

from psb.assistant import Assistant
from psb.config import ConfigError, corpus_path, load_environment
from psb.knowledge import KnowledgeBase
from psb.corpus import load_corpus
from psb.server import make_server


def available_server(assistant, first_port=8080, attempts=20):
    if not 0 <= first_port <= 65535:
        raise ValueError("Порт должен быть от 0 до 65535")
    ports = [0] if first_port == 0 else range(first_port, min(65536, first_port + attempts))
    for port in ports:
        try:
            return make_server("127.0.0.1", port, assistant)
        except OSError as exc:
            if exc.errno not in {errno.EADDRINUSE, errno.EACCES} and getattr(exc, "winerror", None) not in {10048, 10013}:
                raise
    raise ValueError("Свободный порт не найден. Укажите другой: --port 8090")


def main(argv=None):
    # Windows consoles and redirected output must both support Russian messages.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="ОПОРА · быстрый запуск PSB")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--corpus", help="JSON базы знаний; относительный путь от корня проекта")
    parser.add_argument("--no-browser", action="store_true", help="Не открывать браузер")
    parser.add_argument("--check", action="store_true", help="Проверить конфигурацию и завершиться")
    args = parser.parse_args(argv)
    try:
        load_environment()
        kb = load_corpus(corpus_path(args.corpus))
        assistant = Assistant(kb)
        print("ОПОРА · PSB 1.2.1", flush=True)
        print(f"База: {'учебная (вымышленные документы)' if kb.kind == 'demo' else 'предоставленная'}; документов: {len(kb.documents)}", flush=True)
        print("Модель: настроена; доступ проверяется при запросе" if assistant.model.ready else "Модель: отключена; доступны только выдержки", flush=True)
        if args.check:
            print("Конфигурация проверена. Запрос к модели не выполнялся.", flush=True)
            return 0
        server = available_server(assistant, args.port)
    except ConfigError as exc:
        print(f"Ошибка настройки: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("База знаний не найдена. Проверьте PSB_CORPUS_PATH / PSB_CORPUS_FILE в .env или параметр --corpus.", file=sys.stderr)
        return 1
    except (ValueError, OSError, TypeError):
        print("Не удалось запустить PSB. Проверьте формат .env, путь и структуру базы, адрес API и пару URL/имя модели. Значения ключей не выводятся.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Сайт: {url}", flush=True)
    if args.port and server.server_port != args.port:
        print(f"Порт {args.port} недоступен; выбран {server.server_port}.", flush=True)
    print("Оставьте это окно открытым. Остановка: Ctrl+C.", flush=True)
    if not args.no_browser:
        def open_browser():
            try:
                webbrowser.open(url)
            except (OSError, webbrowser.Error):
                pass  # The printed URL remains available if no browser is configured.
        timer = threading.Timer(0.3, open_browser)
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPSB остановлен.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
