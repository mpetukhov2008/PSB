"""Literal .env configuration shared by all entry points; never executes code."""

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_KEYS = {
    "PSB_CORPUS_PATH", "PSB_CORPUS_FILE", "PSB_LLM_BASE_URL", "PSB_LLM_API_KEY",
    "PSB_LLM_MODEL", "PSB_LLM_TIMEOUT_SECONDS",
    "DATA_DIR", "LLM_BASE_URL", "BASE_URL", "OPENAI_BASE_URL", "LLM_API_KEY", "OPENAI_API_KEY",
    "LLM_MODEL", "GEN_MODEL", "OPENAI_MODEL", "EMBEDDER_API_KEY", "RERANKER_API_KEY",
    "EMB_MODEL", "RERANKER_MODEL", "PSB_USE_EMBEDDINGS", "PSB_USE_RERANKER",
    "TOP_K", "RERANKER_TOP_N", "MAX_TOKENS", "MAX_WORKERS", "PSB_CORPUS_ZIP",
}


class ConfigError(ValueError):
    """Public configuration error without the offending value."""


def read_env(path):
    path = Path(path)
    if not path.is_file():
        return {}
    if path.stat().st_size > 100_000:
        raise ConfigError("Файл .env превышает 100 КБ")
    values = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"В .env строка {number}: ожидается ИМЯ=значение")
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ConfigError(f"В .env строка {number}: некорректное имя переменной")
        if name not in ENV_KEYS:
            continue
        if name in values:
            raise ConfigError(f"В .env строка {number}: повторяющаяся переменная {name}")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ConfigError(f"В .env строка {number}: незакрытые кавычки")
            value = value[1:-1]
        values[name] = value
    return values


def load_environment(root=ROOT):
    for name, value in read_env(Path(root) / ".env").items():
        os.environ.setdefault(name, value)


def corpus_path(explicit=None, root=ROOT):
    value = explicit or os.getenv("PSB_CORPUS_PATH") or os.getenv("PSB_CORPUS_ZIP") or os.getenv("PSB_CORPUS_FILE")
    if not value:
        for name in ('knowledge.json', 'kb.zip', 'knowledge-base.zip', 'knowledge_base.zip'):
            candidate = Path(root) / 'data' / name
            if candidate.is_file():
                return candidate
    path = Path(value) if value else Path("samples/psb-demo.json")
    return path if path.is_absolute() else Path(root) / path

def setting(*names, default=''):
    for name in names:
        value = os.getenv(name, '').strip()
        if value and value != name:
            return value
    return default


def integer(name, default, low, high):
    raw = setting(name)
    if not raw:
        return default
    try:
        value = int(raw)
        if low <= value <= high:
            return value
    except ValueError:
        pass
    raise ConfigError(f'{name} должен быть целым числом от {low} до {high}')
