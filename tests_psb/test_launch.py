import contextlib
import io
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from psb.assistant import Assistant, Model
from psb.config import ConfigError, ENV_KEYS, corpus_path, load_environment, read_env
from psb.knowledge import KnowledgeBase
from psb.launcher import available_server, main

ROOT = Path(__file__).resolve().parents[1]


def offline_env():
    return {**os.environ, **{key: "" for key in ENV_KEYS}, "PSB_LLM_TIMEOUT_SECONDS": "35", "PSB_CORPUS_FILE": "samples/psb-demo.json"}


class ConfigTests(unittest.TestCase):
    def test_quotes_bom_and_literal_values(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / ".env"
            p.write_text('\ufeff# comment\nPSB_LLM_API_KEY="fake#key=literal"\nPSB_CORPUS_FILE=folder with spaces/knowledge.json\n', encoding="utf-8")
            values = read_env(p)
            self.assertEqual(values["PSB_LLM_API_KEY"], "fake#key=literal")
            self.assertEqual(values["PSB_CORPUS_FILE"], "folder with spaces/knowledge.json")

    def test_process_environment_wins(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"PSB_LLM_MODEL": "from-process"}):
            (Path(directory) / ".env").write_text("PSB_LLM_MODEL=from-file\n", encoding="utf-8")
            load_environment(directory)
            self.assertEqual(os.environ["PSB_LLM_MODEL"], "from-process")

    def test_env_file_is_data_not_code(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / ".env"
            p.write_text('PSB_LLM_MODEL=$(touch never-created)\nUNRELATED_KEY=ignored\n', encoding="utf-8")
            self.assertEqual(read_env(p), {"PSB_LLM_MODEL": "$(touch never-created)"})
            self.assertFalse((Path(directory) / "never-created").exists())

    def test_bad_env_errors_do_not_include_secret(self):
        for text in ['PSB_LLM_API_KEY="sensitive-value', 'PSB_LLM_API_KEY=secret\nPSB_LLM_API_KEY=other', 'sensitive-value']:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                p = Path(directory) / ".env"
                p.write_text(text, encoding="utf-8")
                with self.assertRaises(ConfigError) as error:
                    read_env(p)
                self.assertNotIn("sensitive-value", str(error.exception))
                self.assertNotIn("secret", str(error.exception))

    def test_relative_corpus_is_relative_to_project(self):
        with patch.dict(os.environ, {"PSB_CORPUS_PATH": "", "PSB_CORPUS_FILE": "data/knowledge.json"}):
            self.assertEqual(corpus_path(root=Path("/project")), Path("/project/data/knowledge.json"))
            self.assertEqual(corpus_path("other.json", root=Path("/project")), Path("/project/other.json"))

    def test_incomplete_model_configuration(self):
        with patch.dict(os.environ, offline_env(), clear=True):
            os.environ["PSB_LLM_API_KEY"] = "do-not-print-this"
            with self.assertRaises(ConfigError) as error:
                Model()
            self.assertNotIn("do-not-print-this", str(error.exception))

    def test_invalid_timeout(self):
        for value in ["zero", "0", "121", "nan", "inf"]:
            with self.subTest(value=value), patch.dict(os.environ, offline_env(), clear=True):
                os.environ["PSB_LLM_TIMEOUT_SECONDS"] = value
                with self.assertRaises(ConfigError):
                    Model()


class LaunchTests(unittest.TestCase):
    def test_diagnostic_mode_does_not_open_browser(self):
        with patch.dict(os.environ, offline_env(), clear=True), patch("psb.launcher.webbrowser.open") as opened:
            # Do not replace the real console encoding while capturing this call.
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["--check"])
            self.assertEqual(code, 0)
            opened.assert_not_called()

    def test_missing_corpus_returns_failure(self):
        with patch.dict(os.environ, offline_env(), clear=True), contextlib.redirect_stderr(io.StringIO()) as error:
            code = main(["--check", "--corpus", "does-not-exist.json"])
        self.assertEqual(code, 1)
        self.assertIn("не найдена", error.getvalue())

    def test_port_collision_falls_back(self):
        kb = KnowledgeBase.load(ROOT / "samples/psb-demo.json")
        class Offline:
            ready = False
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            port = occupied.getsockname()[1]
            if port > 65515:
                self.skipTest("No port range available after this ephemeral port")
            server = available_server(Assistant(kb, Offline()), port)
            try:
                self.assertNotEqual(server.server_port, port)
                self.assertLess(server.server_port, port + 20)
            finally:
                server.server_close()

    def test_launcher_subprocess_is_healthy(self):
        process = subprocess.Popen([sys.executable, "-m", "psb.launcher", "--port", "0", "--no-browser"],
                                   cwd=ROOT, env=offline_env(), stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, encoding="utf-8")
        lines = queue.Queue()
        def read_lines():
            for line in process.stdout:
                lines.put(line)
        thread = threading.Thread(target=read_lines, daemon=True)
        thread.start()
        try:
            url = None
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                line = lines.get(timeout=max(0.1, deadline - time.monotonic()))
                match = re.search(r"http://127\.0\.0\.1:\d+/", line)
                if match:
                    url = match.group()
                    break
            self.assertIsNotNone(url)
            with urllib.request.urlopen(url + "api/health", timeout=5) as response:
                health = json.load(response)
            self.assertEqual(health["application"], "psb")
            self.assertEqual(health["version"], "1.2.1")
            self.assertFalse(health["model_ready"])
        finally:
            process.terminate()
            process.wait(timeout=10)
            thread.join(timeout=3)
            process.stdout.close()

    def test_jsonl_bad_and_oversized_cases_do_not_poison_next_case(self):
        cases = "broken-json\n" + json.dumps("x" * 100010) + '\n{"question":"Согласование договора"}\n'
        result = subprocess.run([sys.executable, "solution.py", "--jsonl"], cwd=ROOT, input=cases,
                                env=offline_env(), encoding="utf-8", capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r["status"] for r in lines], ["invalid_request", "invalid_request", "excerpts"])


@unittest.skipUnless(os.name == "nt", "Windows CMD integration runs in the Windows CI job")
class WindowsQuickStartTests(unittest.TestCase):
    def test_real_cmd_from_unrelated_directory_with_spaces_and_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ПСБ project with spaces"
            root.mkdir()
            for name in ("psb", "samples"):
                shutil.copytree(ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copyfile(ROOT / "START_PSB.cmd", root / "START_PSB.cmd")
            (root / ".env").write_text("PSB_CORPUS_FILE=samples/psb-demo.json\n", encoding="utf-8")
            for explicit_python in (False, True):
                env = offline_env()
                env.pop("PSB_PYTHON", None)
                if explicit_python:
                    env["PSB_PYTHON"] = sys.executable
                result = subprocess.run(["cmd.exe", "/d", "/c", "call", str(root / "START_PSB.cmd"), "--check"],
                                        cwd=directory, env=env, capture_output=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Конфигурация проверена", result.stdout)

    def test_bad_explicit_python_has_clear_nonzero_exit(self):
        env = offline_env()
        env["PSB_PYTHON"] = r"C:\not-installed\python.exe"
        result = subprocess.run(["cmd.exe", "/d", "/c", "START_PSB.cmd", "--check"], cwd=ROOT,
                                env=env, capture_output=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Python 3.10+ was not found", result.stdout)


if __name__ == "__main__":
    unittest.main()
