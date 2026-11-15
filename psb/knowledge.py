"""Immutable version-aware corpus and local BM25 search; no network."""
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

STOP = set("и в во на по для из к с со о об а но или не что это как какой какие ли у до от при за мы вы он она они наш нас нам мне меня свой этот того нужно можно должен только уже его их все чем кто какого какая каком который пожалуйста пользователь ассистент".split())
SYNONYMS = [
    'аванс предоплата', 'дефект недостаток претензия', 'ночью круглосуточно доступ',
    'проверить качество приемка', 'запустить инициатор', 'компьютеры техника',
    'сдать ключи возврат акт', 'пропускать доступ',
]


def stem(word):
    if re.search('[а-я]', word) and len(word) > 4:
        word = re.sub(r'(иями|ами|ями|ого|его|ому|ему|ыми|ими|иях|ах|ях|ия|ие|ий|ый|ой|ая|яя|ое|ее|ые|их|ых|ую|юю|ов|ев|ам|ям|ом|ем|ым|им|ы|и|а|я|у|ю|е|о|ь)$', '', word)
    if word.endswith('ийн'):
        word = word[:-3]
    return word[:7] if len(word) > 7 else word


def tokens(text):
    words = re.findall(r"[a-zа-я0-9]+", text.lower().replace("ё", "е"))
    return [stem(w) for w in words if w not in STOP and len(w) > 1]


def query_tokens(text):
    terms = set(tokens(text))
    for group in SYNONYMS:
        related = set(tokens(group))
        if terms & related:
            terms |= related
    return terms


def parse_date(value):
    if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Дата должна иметь формат ГГГГ-ММ-ДД")
    return date.fromisoformat(value) if value else None


@dataclass(frozen=True)
class Fragment:
    id: str
    document_id: str
    title: str
    family: str
    kind: str
    revision: str
    effective_from: str
    effective_to: str
    locator: str
    text: str
    snapshot_date: str = ''

    def public(self):
        return asdict(self)

    def applies(self, at):
        start, end = parse_date(self.effective_from), parse_date(self.effective_to)
        return (start is None or start <= at) and (end is None or at < end)


class KnowledgeBase:
    def __init__(self, value):
        if not isinstance(value, dict) or value.get("corpus_kind") not in {"demo", "provided"}:
            raise ValueError("Укажите corpus_kind: demo или provided")
        self.kind = value["corpus_kind"]
        documents = value.get("documents")
        if not isinstance(documents, list) or len(documents) > 10000:
            raise ValueError("documents должен быть массивом до 10000 документов")
        self.documents, self.fragments = {}, []
        for document in documents:
            self._add(document)
        self._validate_versions()
        self.fingerprint = hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        self._terms = [Counter(tokens(f.title + " " + f.locator + " " + f.text))
                       for f in self.fragments]
        self._df = Counter(t for bag in self._terms for t in bag)
        self._avg = sum(sum(b.values()) for b in self._terms) / max(1, len(self._terms))

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size > 50_000_000:
            raise ValueError("База знаний превышает 50 МБ")
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def _add(self, d):
        if not isinstance(d, dict):
            raise ValueError("Некорректный документ")
        required = ("id", "title", "family", "kind", "revision")
        if any(not isinstance(d.get(k), str) or not d[k].strip() for k in required):
            raise ValueError("У документа нужны id, title, family, kind, revision")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", d["id"]) or d["id"] in self.documents:
            raise ValueError("Идентификатор документа некорректен или повторяется")
        if d["kind"] not in {"law", "company"}:
            raise ValueError("kind должен быть law или company")
        start, end = d.get("effective_from", ""), d.get("effective_to", "")
        if not isinstance(start, str) or not isinstance(end, str):
            raise ValueError("Даты должны быть строками ISO")
        parse_date(start)
        parse_date(end)
        if d["kind"] == "company" and not start:
            raise ValueError("У документа компании нужна дата начала редакции")
        if end and start and end <= start:
            raise ValueError("Конец редакции должен быть позже начала")
        sections = d.get("sections")
        if not isinstance(sections, list) or not sections or len(sections) > 10000:
            raise ValueError("Нужен непустой массив sections")
        for index, section in enumerate(sections):
            if not isinstance(section, dict):
                raise ValueError("Некорректный раздел")
            text, locator = section.get("text"), section.get("locator")
            if not isinstance(text, str) or not text.strip() or len(text) > 50000:
                raise ValueError("Текст раздела должен содержать 1–50000 символов")
            if not isinstance(locator, str) or not locator.strip() or len(locator) > 300:
                raise ValueError("Укажите положение или страницу источника")
            if section.get('untrusted_instruction') is True:
                continue
            for offset in range(0, len(text), 1400):
                self.fragments.append(Fragment(
                    f"{d['id']}-{index + 1}-{offset}", d["id"], d["title"], d["family"],
                    d["kind"], d["revision"], start, end, locator, text[offset:offset + 1800],
                    d.get("snapshot_date", ""),
                ))
        self.documents[d["id"]] = {**d, "effective_from": start, "effective_to": end}

    def _validate_versions(self):
        families = {}
        for d in self.documents.values():
            for old in families.setdefault(d["family"], []):
                if old["kind"] != d["kind"]:
                    raise ValueError("Редакции одной family должны иметь одинаковый kind")
                lo = max(old["effective_from"], d["effective_from"])
                hi = min(old["effective_to"] or "9999-12-31",
                         d["effective_to"] or "9999-12-31")
                if lo < hi:
                    raise ValueError("Редакции одной family пересекаются")
            families[d["family"]].append(d)

    def search(self, query, at, document_ids=(), limit=10):
        if set(document_ids) - self.documents.keys():
            raise ValueError("Выбран неизвестный документ")
        terms = query_tokens(query)
        if not terms:
            return []
        n, scored = len(self.fragments), []
        for fragment, bag in zip(self.fragments, self._terms):
            if document_ids and fragment.document_id not in document_ids:
                continue
            if not fragment.applies(at):
                continue
            score, length = 0.0, sum(bag.values())
            for term in terms:
                tf = bag[term]
                if tf:
                    idf = math.log(1 + (n - self._df[term] + 0.5) / (self._df[term] + 0.5))
                    score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / max(1, self._avg)))
            if score > 0:
                score *= 1 + len(terms & bag.keys()) / max(1, len(terms))
                scored.append((score, fragment))
        scored.sort(key=lambda item: (-item[0], item[1].id))
        return [f for _, f in scored[:limit]]

    def resolve_scope(self, question, history=()):
        """Latest explicit party/contract wins; word boundaries distinguish similar names."""
        for text in [question] + [t['content'] for t in reversed(history) if t['role'] == 'user']:
            matches = []
            for doc in self.documents.values():
                for alias in doc.get('aliases', []):
                    pattern = r'(?<![\w-])' + re.escape(alias).replace(r'\ ', r'\s+') + r'(?![\w-])'
                    alias_terms = set(tokens(alias))
                    inflected = ('/' not in alias and len(alias_terms) >= 2
                                 and alias_terms <= set(tokens(text)))
                    if re.search(pattern, text, re.I) or inflected:
                        matches.append(doc['id'])
                        break
            if matches:
                scope = set(matches)
                for ident in matches:
                    scope.update(self.documents[ident].get('related_ids', []))
                return sorted(scope)
        return []
