"""Optional API ranking with deterministic local fallback and no shared dialogue state."""
import math
import threading
from psb.config import integer, setting


class Retriever:
    def __init__(self, model):
        self.model, self.cache = model, {}
        self.lock = threading.Lock()

    def rank(self, query, fragments):
        from psb.assistant import ModelError
        if not fragments:
            return [], []
        notes = []
        limit = integer('RERANKER_TOP_N', 12, 1, 18)
        candidates = fragments[:integer('TOP_K', 40, 1, 80)]
        if not self.model.ready or not hasattr(self.model, 'post'):
            return candidates[:limit], ['Локальное лексическое ранжирование']
        default = 'true' if setting('LLM_BASE_URL', 'BASE_URL', 'OPENAI_BASE_URL') else 'false'
        if setting('PSB_USE_EMBEDDINGS', default=default).lower() == 'true':
            try:
                with self.lock:
                    missing = [f for f in candidates if f.id not in self.cache]
                    texts = [query] + [f.title + '\n' + f.text for f in missing]
                    value = self.model.post('/embeddings', {
                        'model': setting('EMB_MODEL', default='baai/bge-m3'),
                        'input': texts, 'encoding_format': 'float'},
                        setting('EMBEDDER_API_KEY', default=self.model.key))
                    vectors = [None] * len(texts)
                    for pos, item in enumerate(value['data']):
                        index = item.get('index', pos)
                        if type(index) is not int or not 0 <= index < len(texts) or vectors[index] is not None:
                            raise ValueError
                        vector = [float(x) for x in item['embedding']]
                        if not vector or len(vector) > 10000 or not all(math.isfinite(x) for x in vector):
                            raise ValueError
                        norm = math.sqrt(sum(x*x for x in vector))
                        if not norm:
                            raise ValueError
                        vectors[index] = [x / norm for x in vector]
                    if any(v is None for v in vectors) or len({len(v) for v in vectors}) != 1:
                        raise ValueError
                    for item, vector in zip(missing, vectors[1:]):
                        if len(self.cache) < 2000:
                            self.cache[item.id] = vector
                    local = {item.id: v for item, v in zip(missing, vectors[1:])}
                    query_vector, dense = vectors[0], {}
                    for item in candidates:
                        vector = local.get(item.id, self.cache.get(item.id))
                        if vector is None or len(vector) != len(query_vector):
                            raise ValueError
                        dense[item.id] = sum(a*b for a, b in zip(query_vector, vector))
                order = sorted(candidates, key=lambda item: (-dense[item.id], item.id))
                ranks = {item.id: i for i, item in enumerate(order)}
                scores = {item.id: 1/(40+i) + 1/(40+ranks[item.id]) for i, item in enumerate(candidates)}
                candidates = sorted(candidates, key=lambda item: (-scores[item.id], item.id))
                notes.append('BM25 + embeddings, объединение рангов')
            except (ModelError, ValueError, TypeError, KeyError, IndexError, OverflowError):
                notes.append('Embeddings недоступны: сохранён локальный поиск')
        if setting('PSB_USE_RERANKER', default=default).lower() == 'true':
            try:
                pool = candidates[:20]
                value = self.model.post('/rerank', {
                    'model': setting('RERANKER_MODEL', default='cohere/rerank-5-fast'),
                    'query': query, 'documents': [item.title + '\n' + item.text for item in pool],
                    'top_n': min(limit, len(pool))},
                    setting('RERANKER_API_KEY', default=self.model.key))
                items = value.get('results', value.get('data', []))
                indices = [item['index'] for item in items]
                if not indices or any(type(i) is not int or not 0 <= i < len(pool) for i in indices) or len(set(indices)) != len(indices):
                    raise ValueError
                candidates = [pool[i] for i in indices]
                notes.append('Реранжирование фрагментов')
            except (ModelError, ValueError, TypeError, KeyError, IndexError):
                notes.append('Реранкер недоступен: сохранён предыдущий порядок')
        return candidates[:limit], notes
