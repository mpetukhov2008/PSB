"""Real HTTP adapter tests against a local synthetic API, not a legal quality score."""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from psb.assistant import Assistant, Model, ModelError
from psb.knowledge import KnowledgeBase


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "data": data})
        if self.server.behavior == "redirect":
            self.send_response(302)
            self.send_header("Location", "/other-endpoint")
            self.end_headers()
            return
        if self.server.behavior == "invalid":
            raw = b'{"choices":[{"message":{"content":null}}]}'
        else:
            payload = json.loads(data["messages"][1]["content"])
            if "answer" in payload:
                result = {"approved": True, "supported_claims": [0]}
            else:
                source = payload["fragments"][0]
                result = {"status": "answered", "claims": [{
                    "text": source["text"], "evidence": [{
                        "fragment_id": source["id"], "quote": source["text"]}]}],
                          "message": "", "missing": []}
            raw = json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class ModelAPITests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.seen = []
        self.server.behavior = "valid"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.env = patch.dict(os.environ, {
            "PSB_LLM_BASE_URL": f"http://127.0.0.1:{self.server.server_port}/v1",
            "PSB_LLM_MODEL": "synthetic-test-model",
            "PSB_LLM_API_KEY": "synthetic-test-key",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_end_to_end_two_calls_same_model_and_exact_citations(self):
        kb = KnowledgeBase.load(Path(__file__).resolve().parents[1] / "samples/psb-demo.json")
        result = Assistant(kb).answer({"question": "Срок согласования договора?"})
        self.assertEqual(result["status"], "answered")
        self.assertTrue(result["verified"])
        self.assertEqual(len(self.server.seen), 2)
        self.assertTrue(all(r["data"]["model"] == "synthetic-test-model" for r in self.server.seen))
        self.assertTrue(all(r["path"] == "/v1/chat/completions" for r in self.server.seen))
        self.assertTrue(all(r["auth"] == "Bearer synthetic-test-key" for r in self.server.seen))

    def test_invalid_model_response_is_sanitized(self):
        self.server.behavior = "invalid"
        with self.assertRaises(ModelError) as error:
            Model().complete("test", {})
        self.assertNotIn("synthetic-test-key", str(error.exception))

    def test_redirect_not_followed(self):
        self.server.behavior = "redirect"
        with self.assertRaises(ModelError):
            Model().complete("test", {})
        self.assertEqual(len(self.server.seen), 1)

    def test_unconfigured_model_not_ready(self):
        with patch.dict(os.environ, {"PSB_LLM_BASE_URL": "", "PSB_LLM_MODEL": "", "PSB_LLM_API_KEY": ""}):
            self.assertFalse(Model().ready)


if __name__ == "__main__":
    unittest.main()

