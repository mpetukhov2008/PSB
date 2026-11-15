"""Verify the expert Docker launch with isolated data, aliases and host-file override."""
import json
import os
import subprocess
import tempfile
import urllib.request
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run():
    project = 'psb-contract-' + uuid.uuid4().hex[:10]
    command = ['docker', 'compose', '-p', project]
    with tempfile.TemporaryDirectory() as directory:
        data = Path(directory) / 'provided'
        data.mkdir()
        env = {**os.environ, 'PSB_DATA_DIR': str(data), 'PSB_PORT': '0',
               'PSB_CORPUS_PATH': '', 'PSB_CORPUS_FILE': '', 'PSB_LLM_BASE_URL': '',
               'PSB_LLM_API_KEY': '', 'PSB_LLM_MODEL': '', 'LLM_BASE_URL': '',
               'LLM_API_KEY': '', 'LLM_MODEL': '', 'PSB_USE_EMBEDDINGS': 'false',
               'PSB_USE_RERANKER': 'false'}

        def compose(*args):
            result = subprocess.run(command + list(args), cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=240)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            return result.stdout.strip()

        def start(build=False):
            args = ['up', '-d', '--wait', '--force-recreate']
            if build:
                args.append('--build')
            compose(*args)
            address = compose('port', 'assistant', '8080').splitlines()[0]
            return 'http://' + address

        def get(base, path):
            with urllib.request.urlopen(base + path, timeout=10) as response:
                return json.load(response)

        try:
            base = start(build=True)
            health = get(base, '/api/health')
            assert health['corpus_kind'] == 'demo' and health['documents'] == 3
            print('Docker: clean one-command startup, demo fallback OK')
            with zipfile.ZipFile(data / 'knowledge-base.zip', 'w') as archive:
                archive.writestr('Договор.txt',
                    'ДОГОВОР ПОСТАВКИ № П-88/2024\nг. Москва — 12 февраля 2024 г.\n'
                    'ООО «Тестовый поставщик» и ООО «Меридиан».\n'
                    '4.1. Оплата производится в течение 11 календарных дней.')
            base = start()
            health = get(base, '/api/health')
            assert health['corpus_kind'] == 'provided' and health['documents'] == 1
            request = urllib.request.Request(base + '/api/chat',
                json.dumps({'question': 'Срок оплаты по П-88/2024?'}).encode(),
                {'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=10) as response:
                answer = json.load(response)
            assert any('11 календарных дней' in source['text'] for source in answer['sources'])
            print('Docker: provided ZIP auto-detected; web search and sources OK')

            env.update(LLM_BASE_URL='https://example.invalid/v1',
                       LLM_API_KEY='dummy-integration-key', LLM_MODEL='test-model')
            base = start()
            assert get(base, '/api/health')['model_ready'] is True
            # Only inspect configuration. No call or real key is sent to a model.
            compose('exec', '-T', 'assistant', 'python', '-c',
                'from psb.assistant import Model; m=Model(); '
                'assert m.name == "test-model" and m.key == "dummy-integration-key"')
            print('Docker: LLM_* settings reach the web app; no live API request')

            env['PSB_CORPUS_FILE'] = str(ROOT / 'samples' / 'psb-demo.json')
            base = start()
            assert get(base, '/api/health')['corpus_kind'] == 'demo'
            print('Docker: explicit host-file override retains priority OK')
        finally:
            compose('down', '--remove-orphans')


if __name__ == '__main__':
    run()
