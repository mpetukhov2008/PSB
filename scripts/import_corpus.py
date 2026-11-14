"""Local import with explicit revision metadata; no API calls or inferred law."""
import argparse
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from psb.knowledge import KnowledgeBase  # noqa: E402

MAX_BYTES = 20_000_000


def extract(path):
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Исходный файл превышает 20 МБ")
    extension = path.suffix.lower()
    if extension in {".txt", ".md"}:
        parts = path.read_text(encoding="utf-8").split("\n\n")
        return [{"locator": f"абзац {i + 1}", "text": p.strip()}
                for i, p in enumerate(parts) if p.strip()]
    if extension == ".docx":
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_BYTES:
                raise ValueError("Распакованный документ превышает 20 МБ")
            root = ElementTree.fromstring(archive.read(info))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        parts = ["".join(t.text or "" for t in p.findall(".//w:t", ns))
                 for p in root.findall(".//w:p", ns)]
        return [{"locator": f"абзац {i + 1}", "text": p.strip()}
                for i, p in enumerate(parts) if p.strip()]
    if extension == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ValueError("Для PDF установите requirements-import.txt") from None
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError("Зашифрованный PDF не поддерживается")
        if len(reader.pages) > 2000:
            raise ValueError("PDF содержит более 2000 страниц")
        sections = []
        for index, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if not text.strip():
                raise ValueError(f"Страница {index + 1} без текста: нужен OCR или ручная подготовка")
            sections.append({"locator": f"стр. {index + 1}", "text": text})
        return sections
    raise ValueError("Поддерживаются TXT, MD, DOCX и PDF")


def prepare(manifest):
    manifest = Path(manifest).resolve()
    if manifest.stat().st_size > MAX_BYTES:
        raise ValueError("Манифест превышает 20 МБ")
    value = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("documents"), list):
        raise ValueError("Некорректный манифест")
    documents = []
    for item in value["documents"]:
        if not isinstance(item, dict):
            raise ValueError("Некорректный документ")
        if "file" in item:
            if not isinstance(item["file"], str):
                raise ValueError("file должен быть относительным путём")
            source = (manifest.parent / item["file"]).resolve()
            if not source.is_relative_to(manifest.parent) or not source.is_file():
                raise ValueError("Исходный файл должен находиться внутри папки манифеста")
            sections = extract(source)
            documents.append({k: v for k, v in item.items() if k != "file"} | {
                "sections": sections, "source_file": source.relative_to(manifest.parent).as_posix()})
        else:
            documents.append(item)
    output = {"corpus_kind": value.get("corpus_kind"), "documents": documents}
    KnowledgeBase(output)
    return output


def main():
    parser = argparse.ArgumentParser(description="Подготовка закрытой базы знаний")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        output = Path(args.output).resolve()
        source = Path(args.manifest).resolve()
        if output == source:
            raise ValueError("Нельзя перезаписывать манифест результатом")
        value = prepare(source)
        # Refuse to overwrite an original referenced by the manifest.
        manifest_data = json.loads(source.read_text(encoding="utf-8"))
        originals = {(source.parent / d["file"]).resolve()
                     for d in manifest_data["documents"] if "file" in d}
        if output in originals:
            raise ValueError("Нельзя перезаписывать исходный документ")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Documents: {len(value['documents'])}; corpus: {value['corpus_kind']}")
    except (ValueError, OSError, zipfile.BadZipFile, ElementTree.ParseError, KeyError) as exc:
        parser.exit(2, f"Import error: {exc}\n")


if __name__ == "__main__":
    main()
