"""Official CSV contract; each question carries its own dialogue state."""
import csv
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from psb.config import integer, setting
from psb.corpus import load_corpus


def dialogue_request(text):
    matches = list(re.finditer(r'(?:^|\n)\s*(Пользователь|Ассистент):\s*', text, re.I))
    if not matches or matches[0].start() != 0:
        return {'question': text}
    turns = []
    for i, match in enumerate(matches):
        content = text[match.end():matches[i+1].start() if i+1 < len(matches) else len(text)].strip()
        turns.append({'role': 'user' if match.group(1).casefold() == 'пользователь' else 'assistant',
                      'content': content})
    if turns[-1]['role'] != 'user':
        raise ValueError('Последняя реплика должна принадлежать пользователю')
    if len(turns) > 13 or any(len(turn['content']) > 6000 for turn in turns):
        raise ValueError('История превышает лимит')
    return {'question': turns[-1]['content'], 'history': turns[:-1]}


def render_answer(result):
    parts, by_id = [], {item['id']: item for item in result.get('sources', [])}
    for claim in result.get('claims', []):
        refs = []
        for evidence in claim['evidence']:
            source = by_id.get(evidence['fragment_id'])
            if source:
                ref = source['title'] + ', ' + source['locator']
                if source['kind'] == 'company':
                    ref += ' (' + source['revision'] + ')'
                if ref not in refs:
                    refs.append(ref)
        parts.append(claim['text'] + (' Источник: ' + '; '.join(refs) + '.' if refs else ''))
    if result.get('message'):
        parts.append(result['message'])
    if result.get('missing'):
        parts.append('Для полного ответа нужно: ' + '; '.join(result['missing']) + '.')
    if result.get('status') == 'excerpts':
        for source in result.get('sources', [])[:4]:
            parts.append(source['text'] + ' Источник: ' + source['title'] + ', ' + source['locator'] + '.')
    return ' '.join(' '.join(parts).split()) or 'Подтверждённый ответ отсутствует.'


def read_questions(path):
    path = Path(path)
    if path.stat().st_size > 20_000_000:
        raise ValueError('CSV превышает 20 МБ')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ['id', 'question']:
            raise ValueError('В questions.csv нужны колонки id,question')
        rows = list(reader)
    if not rows or len(rows) > 10000:
        raise ValueError('Нужно от 1 до 10000 вопросов')
    ids = [row.get('id', '').strip() for row in rows]
    if any(not ident for ident in ids) or len(set(ids)) != len(ids):
        raise ValueError('ID должны быть непустыми и уникальными')
    if any(not isinstance(row.get('question'), str) or not 2 <= len(row['question']) <= 40000 or None in row for row in rows):
        raise ValueError('Некорректная строка вопросов')
    return [(ident, row['question']) for ident, row in zip(ids, rows)]


def find_inputs(root):
    directory = Path(setting('DATA_DIR', default='data'))
    if not directory.is_absolute():
        directory = Path(root) / directory
    questions = directory / 'questions.csv'
    if not questions.is_file():
        raise ValueError('В DATA_DIR не найден questions.csv')
    for name in ('kb.zip', 'knowledge-base.zip', 'knowledge_base.zip', 'knowledge.json'):
        corpus = directory / name
        if corpus.is_file():
            return questions, corpus
    raise ValueError('В DATA_DIR не найдена база знаний')


def run_csv(questions_path, corpus_path, output, assistant=None, offline=False, report=None):
    from psb.assistant import Assistant
    questions = read_questions(questions_path)
    destination = Path(output).resolve()
    inputs = {Path(questions_path).resolve(), Path(corpus_path).resolve()}
    if destination in inputs or report and Path(report).resolve() in inputs:
        raise ValueError('Нельзя перезаписывать входные данные')
    if report and Path(report).resolve() == destination:
        raise ValueError('Отчёт и CSV должны иметь разные пути')
    if assistant is None:
        if offline:
            class Offline:
                ready = False
            assistant = Assistant(load_corpus(corpus_path), Offline())
        else:
            assistant = Assistant(load_corpus(corpus_path))
    if not offline and not assistant.model.ready:
        raise ValueError('Для сабмита нужен API; для локальных выдержек используйте --offline')

    def work(item):
        ident, question = item
        try:
            result = assistant.answer(dialogue_request(question))
        except ValueError:
            result = {'status': 'invalid_request',
                      'message': 'Запрос требует уточнения: проверьте дату и историю диалога.',
                      'claims': [], 'sources': []}
        return ident, render_answer(result), result

    with ThreadPoolExecutor(max_workers=integer('MAX_WORKERS', 2, 1, 8)) as pool:
        results = list(pool.map(work, questions))
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(dir=destination.parent, suffix='.csv')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator='\n')
            writer.writerow(['id', 'answer'])
            writer.writerows((ident, answer) for ident, answer, _ in results)
        os.replace(temp, destination)
    finally:
        Path(temp).unlink(missing_ok=True)
    if report:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        Path(report).write_text(json.dumps({
            'mode': 'offline' if offline else 'model', 'corpus_fingerprint': assistant.kb.fingerprint,
            'results': [{'id': ident, **result} for ident, _, result in results]},
            ensure_ascii=False, indent=2), encoding='utf-8')
    return results
