"""Dependency-free HTTP entry point. Knowledge base is read-only in the browser."""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from psb import __version__
from psb.assistant import Assistant, RequestError
from psb.config import corpus_path, load_environment
from psb.knowledge import KnowledgeBase

STATIC = Path(__file__).parent / "static"


def make_server(host, port, assistant):
    slots = threading.BoundedSemaphore(4)

    class Handler(BaseHTTPRequestHandler):
        server_version = "PSBAssistant/" + __version__

        def log_message(self, format, *args):
            # Do not log questions, source texts, or model credentials.
            pass

        def send(self, status, body, mime="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # The client may stop waiting while the model is running.

        def host_allowed(self):
            try:
                host = urlsplit("http://" + self.headers.get("Host", ""))
                return (host.hostname in {"localhost", "127.0.0.1", "::1"}
                        and not host.username and not host.password
                        and not host.path and not host.query and not host.fragment)
            except ValueError:
                return False

        def do_GET(self):
            if not self.host_allowed():
                return self.send(403, {"detail": "Недопустимый Host"})
            path = unquote(urlsplit(self.path).path)
            if path == "/api/health":
                return self.send(200, {"status": "ok", "application": "psb",
                                       "version": __version__,
                                       "corpus_fingerprint": assistant.kb.fingerprint,
                                       "documents": len(assistant.kb.documents),
                                       "fragments": len(assistant.kb.fragments),
                                       "corpus_kind": assistant.kb.kind,
                                       "model_ready": assistant.model.ready})
            if path == "/api/documents":
                docs = [{k: v for k, v in d.items() if k != "sections"}
                        for d in assistant.kb.documents.values()]
                return self.send(200, {"documents": docs, "corpus_kind": assistant.kb.kind})
            if path.startswith("/api/documents/"):
                ident = path.removeprefix("/api/documents/")
                document = assistant.kb.documents.get(ident)
                return self.send(200, document) if document else self.send(404, {"detail": "Документ не найден"})
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/static/style.css": ("style.css", "text/css; charset=utf-8"),
                     "/static/chat.js": ("chat.js", "text/javascript; charset=utf-8")}
            if path in files:
                name, mime = files[path]
                return self.send(200, (STATIC / name).read_bytes(), mime)
            return self.send(404, {"detail": "Страница не найдена"})

        def do_POST(self):
            if not self.host_allowed():
                return self.send(403, {"detail": "Недопустимый Host"})
            if urlsplit(self.path).path != "/api/chat":
                return self.send(404, {"detail": "Маршрут не найден"})
            origin = self.headers.get("Origin")
            # Disallow browser requests from foreign sites, even through localhost.
            if origin:
                try:
                    parsed = urlsplit(origin)
                    same_origin = (parsed.scheme in {"http", "https"}
                                   and parsed.netloc == self.headers.get("Host")
                                   and not parsed.path and not parsed.query and not parsed.fragment)
                except ValueError:
                    same_origin = False
                if not same_origin:
                    return self.send(403, {"detail": "Запрос с другого сайта запрещён"})
            if self.headers.get_content_type() != "application/json":
                return self.send(415, {"detail": "Нужен Content-Type: application/json"})
            if self.headers.get("Transfer-Encoding"):
                return self.send(400, {"detail": "Нужен Content-Length"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 100000:
                    return self.send(413, {"detail": "Запрос должен занимать до 100 КБ"})
            except ValueError:
                return self.send(400, {"detail": "Некорректная длина запроса"})
            if not slots.acquire(blocking=False):
                return self.send(429, {"detail": "Сервис занят. Повторите запрос позднее."})
            try:
                self.connection.settimeout(10)
                raw = self.rfile.read(length)
                value = json.loads(raw)
                result = assistant.answer(value)
                self.send(200, result)
            except RequestError as exc:
                self.send(422, {"detail": str(exc)})
            except (ValueError, TypeError, UnicodeError):
                self.send(422, {"detail": "Проверьте формат запроса, дату, историю и выбранные документы."})
            except (TimeoutError, OSError):
                self.send(408, {"detail": "Время чтения запроса истекло"})
            except Exception:
                # Never send model output, secrets or a Python traceback to the client.
                self.send(500, {"detail": "Не удалось обработать запрос. Попробуйте ещё раз или начните новый диалог."})
            finally:
                slots.release()

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(10)
            return connection, address

    return Server((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description="ПСБ · юридический ассистент")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--corpus")
    args = parser.parse_args()
    try:
        load_environment()
        kb = KnowledgeBase.load(corpus_path(args.corpus))
        server = make_server(args.host, args.port, Assistant(kb))
    except (ValueError, OSError, TypeError):
        parser.exit(1, "Не удалось запустить PSB. Проверьте .env, базу знаний и свободный порт.\n")
    print(f"PSB: http://{args.host}:{args.port}; corpus={kb.kind}; documents={len(kb.documents)}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

