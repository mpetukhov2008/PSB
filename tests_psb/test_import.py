import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.import_corpus import extract, prepare


class ImportTests(unittest.TestCase):
    def test_txt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "law.txt"
            path.write_text("Первое положение\n\nВторое положение", encoding="utf-8")
            result = extract(path)
            self.assertEqual(len(result), 2)
            self.assertEqual(result[1]["locator"], "абзац 2")

    def test_docx(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reg.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Точное положение документа</w:t></w:r></w:p></w:body></w:document>')
            self.assertEqual(extract(path)[0]["text"], "Точное положение документа")

    def test_manifest_validation_and_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reg.txt").write_text("Полный текст предоставленного положения.", encoding="utf-8")
            manifest = {"corpus_kind": "provided", "documents": [{
                "id": "reg", "title": "Регламент", "family": "reg", "kind": "company",
                "revision": "1", "effective_from": "2026-01-01", "file": "reg.txt"}]}
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            result = prepare(path)
            self.assertEqual(result["documents"][0]["source_file"], "reg.txt")
            self.assertNotIn("file", result["documents"][0])

    def test_source_outside_manifest_root_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "private.txt").write_text("Not part of corpus", encoding="utf-8")
            folder = root / "source"
            folder.mkdir()
            path = folder / "manifest.json"
            path.write_text(json.dumps({"corpus_kind": "provided", "documents": [{"file": "../private.txt"}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                prepare(path)


if __name__ == "__main__":
    unittest.main()
