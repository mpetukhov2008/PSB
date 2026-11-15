"""Read organizer ZIPs in memory; preserve original text and explicit revision metadata."""
import hashlib
import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from psb.knowledge import KnowledgeBase

MONTHS = {m: i + 1 for i, m in enumerate(
    'января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split())}
MONTH_STEMS = ['январ', 'феврал', 'март', 'апрел', 'ма', 'июн', 'июл', 'август',
               'сентябр', 'октябр', 'ноябр', 'декабр']
MAX_FILE, MAX_TOTAL = 20_000_000, 50_000_000


def dates_in(text):
    values = re.findall(r'\b(\d{2})\.(\d{2})\.(\d{4})\b', text)
    values += [(d.zfill(2), str(MONTHS[m]).zfill(2), y) for d, m, y in
               re.findall(r'\b(\d{1,2})\s+(' + '|'.join(MONTHS) + r')\s+(\d{4})', text.lower())]
    return [date(int(y), int(m), int(d)).isoformat() for d, m, y in values]


def read_archive(path):
    path = Path(path)
    if path.stat().st_size > MAX_TOTAL:
        raise ValueError('Архив превышает 50 МБ')
    documents, total, names = [], 0, set()
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 10000:
            raise ValueError('В архиве слишком много файлов')
        for info in sorted(infos, key=lambda v: v.filename):
            name = info.filename.replace('\\', '/')
            if info.is_dir() or name.startswith('__MACOSX/'):
                continue
            if name.startswith('/') or '..' in name.split('/') or ':' in name or name in names:
                raise ValueError('Недопустимый или повторный путь в архиве')
            names.add(name)
            suffix = Path(name).suffix.lower()
            if suffix not in {'.txt', '.md', '.docx'}:
                raise ValueError('В ZIP поддерживаются только TXT, MD и DOCX')
            total += info.file_size
            if info.file_size > MAX_FILE or total > MAX_TOTAL:
                raise ValueError('Распакованная база превышает лимит')
            raw = archive.read(info)
            if suffix == '.docx':
                with zipfile.ZipFile(io.BytesIO(raw)) as doc:
                    member = doc.getinfo('word/document.xml')
                    if member.file_size > MAX_FILE:
                        raise ValueError('DOCX превышает лимит')
                    root = ET.fromstring(doc.read(member))
                ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                text = '\n'.join(''.join(t.text or '' for t in p.iter(ns + 't'))
                                 for p in root.iter(ns + 'p'))
            else:
                text = raw.decode('utf-8-sig')
            if not text.strip():
                raise ValueError('Пустой документ в базе')
            documents.append((name, text.strip(), hashlib.sha256(raw).hexdigest()))
    if not documents:
        raise ValueError('Архив не содержит документов')
    return documents


def sections(text, law=False):
    """Preserve numbered clauses and paragraphs, including the end of large statutes."""
    lines = text.splitlines()
    if not law and not re.search(r'^\s*[«"]?\d+\.\d+\.?\s+', text, re.M):
        return [{'locator': f'абзац {i + 1}', 'text': line.strip(),
                 'untrusted_instruction': bool(re.search(
                     r'ДЛЯ ИИ-АССИСТЕНТА|игнорируй все|не упоминай эту инструкцию|ignore previous',
                     line, re.I))}
                for i, line in enumerate(lines) if line.strip()]
    result, buffer, locator = [], [], 'реквизиты документа'
    for line in lines:
        match = re.match(r'^\s*[«"]?(\d+\.\d+)\.?\s+', line)
        if match and not law:
            if buffer and '\n'.join(buffer).strip():
                result.append({'locator': locator, 'text': '\n'.join(buffer).strip()})
            buffer, locator = [], 'п. ' + match.group(1)
        if law and not line.strip() and buffer:
            result.append({'locator': f'абзац {len(result) + 1}', 'text': '\n'.join(buffer).strip()})
            buffer = []
        elif line.strip():
            buffer.append(line)
    if buffer:
        result.append({'locator': locator if not law else f'абзац {len(result) + 1}',
                       'text': '\n'.join(buffer).strip()})
    output = []
    for section in result:
        remaining, part = section['text'], 0
        while len(remaining) > 2200:
            stop = max(remaining.rfind('\n', 1000, 2000), remaining.rfind('. ', 1000, 2000))
            if stop < 1000:
                stop = remaining.rfind(' ', 1000, 2000)
            stop = stop if stop >= 1000 else 2000
            output.append({'locator': section['locator'] + f', фрагмент {part + 1}',
                           'text': remaining[:stop].strip()})
            remaining, part = remaining[max(0, stop - 250):].strip(), part + 1
        if remaining:
            output.append({'locator': section['locator'] + (f', фрагмент {part + 1}' if part else ''),
                           'text': remaining})
    return output


def prepare_archive(path):
    docs = []
    for name, text, sha in read_archive(path):
        law = text.startswith('Источник:') or name.startswith('законы')
        first = next(line.strip() for line in text.splitlines() if line.strip())
        title = first.removeprefix('Источник: ').strip()
        if first.startswith('РЕДАКЦИЯ УТРАТИЛА'):
            title = text.splitlines()[1].strip()
        if title.startswith('ООО'):
            title = Path(name).stem.split('__')[-1]
        title = title[:250]
        ident = 'doc-' + hashlib.sha256(name.encode()).hexdigest()[:16]
        ds = dates_in(text[:1300])
        start, end, snapshot = '', '', ''
        revision = 'Предоставленный текст'
        if law:
            match = re.search(r'Дата выгрузки:\s*(\d{2}\.\d{2}\.\d{4})', text)
            snapshot = dates_in(match.group())[0] if match else ''
            revision = 'Текущая редакция из базы' + ('; выгрузка ' + snapshot if snapshot else '')
        else:
            match = re.search(r'(?:Редакция от|Действует с)\s*(\d{2}\.\d{2}\.\d{4})', text)
            start = dates_in(match.group())[0] if match else (ds[0] if ds else '')
            if first.startswith('ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ') and len(ds) > 1:
                start = ds[1]
            match = re.search(r'УТРАТИЛА СИЛУ с\s*(\d{2}\.\d{2}\.\d{4})', text)
            end = dates_in(match.group())[0] if match else ''
            if not start:
                raise ValueError('Для документа компании не найдена дата: нужен явный манифест')
            revision = 'Редакция от ' + start + ('; утратила силу ' + end if end else '')
        family = ident
        if 'РЕГЛАМЕНТ СОГЛАСОВАНИЯ ДОГОВОРОВ' in title:
            family = 'company-approval-regulation'
        aliases = re.findall(r'№\s*([А-ЯA-Z]+-\d+/\d{4})', text[:400])[:1]
        parties = re.findall(r'ООО\s*«([^»]+)»', text[:1200])
        aliases.extend(p for p in parties[:1] if p.casefold() != 'меридиан')
        if first.startswith('ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ'):
            aliases = []
        docs.append({'id': ident, 'title': title, 'family': family,
                     'kind': 'law' if law else 'company', 'revision': revision,
                     'effective_from': start, 'effective_to': end, 'snapshot_date': snapshot,
                     'aliases': sorted(set(aliases)), 'source_file': name, 'source_sha256': sha,
                     'sections': sections(text, law), 'related_ids': []})
    for d in docs:
        if d['title'].startswith('ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ'):
            full = '\n'.join(s['text'] for s in d['sections'])
            for base in docs:
                if base['title'].startswith('ДОГОВОР') and any(
                        a in full for a in base['aliases'] if '/' in a):
                    base['related_ids'].append(d['id'])
                    d['related_ids'].append(base['id'])
    value = {'corpus_kind': 'provided', 'documents': docs}
    KnowledgeBase(value)
    return value


def load_corpus(path):
    path = Path(path)
    return KnowledgeBase(prepare_archive(path)) if path.suffix.lower() == '.zip' else KnowledgeBase.load(path)


def save_corpus(source, destination):
    value = prepare_archive(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return value
