"""Measure retrieval separately from legal answer correctness using private annotations."""
import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from psb.assistant import Assistant
from psb.corpus import load_corpus
from psb.submission import dialogue_request, read_questions


def evaluate(corpus, questions, labels, limit=12):
    class Offline:
        ready = False
    assistant = Assistant(load_corpus(corpus), Offline())
    annotations = json.loads(Path(labels).read_text(encoding='utf-8'))
    results, elapsed, recalls, complete, reciprocal = [], [], [], [], []
    for ident, question in read_questions(questions):
        if ident not in annotations:
            raise ValueError('Для каждого вопроса нужна явная разметка, включая пустой evidence')
        start = time.perf_counter()
        result = assistant.answer(dialogue_request(question))
        elapsed.append((time.perf_counter()-start)*1000)
        sources = result['sources'][:limit]
        expected = annotations[ident]['evidence']
        ranks = []
        for item in expected:
            ranks.append(next((i+1 for i, source in enumerate(sources)
                if (not item.get('source_file') or assistant.kb.documents[source['document_id']].get('source_file') == item['source_file'])
                and item.get('text_contains', '').casefold() in source['text'].casefold()
                and item.get('locator', '') in source['locator']), None))
        if expected:
            recalls.append(sum(rank is not None for rank in ranks)/len(ranks))
            complete.append(all(rank is not None for rank in ranks))
            reciprocal.append(1/min(rank for rank in ranks if rank is not None) if any(ranks) else 0)
        results.append({'id': ident, 'expected_evidence': len(expected), 'ranks': ranks,
                        'status': result['status'], 'date': result['event_date']})
    return {'evaluation': 'offline retrieval only; not answer accuracy',
            'corpus_fingerprint': assistant.kb.fingerprint,
            'questions_sha256': hashlib.sha256(Path(questions).read_bytes()).hexdigest(),
            'labels_sha256': hashlib.sha256(Path(labels).read_bytes()).hexdigest(),
            'questions': len(results), 'positive_questions': len(recalls), 'k': limit,
            'macro_evidence_recall_at_k': statistics.mean(recalls) if recalls else None,
            'complete_questions_at_k': sum(complete),
            'mrr_at_k': statistics.mean(reciprocal) if reciprocal else None,
            'latency_p50_ms': statistics.median(elapsed),
            'latency_p95_ms': sorted(elapsed)[max(0, int(len(elapsed)*.95)-1)],
            'negative_questions': len(results)-len(recalls),
            'negative_answer_accuracy': None, 'legal_answer_accuracy': None,
            'results': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--corpus', required=True)
    parser.add_argument('--questions', required=True)
    parser.add_argument('--labels', required=True)
    parser.add_argument('--output', default='artifacts/retrieval.json')
    args = parser.parse_args()
    path = Path(args.output)
    if path.resolve() in {Path(item).resolve() for item in [args.corpus, args.questions, args.labels]}:
        parser.error('Нельзя перезаписывать входной файл')
    output = evaluate(args.corpus, args.questions, args.labels)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key:value for key,value in output.items() if key != 'results'}, ensure_ascii=False))
