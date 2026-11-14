"""Optional PDF importer verification. Run after requirements-import.txt installation."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.import_corpus import extract


def pdf_bytes(text):
    content = (f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET").encode("ascii") if text else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    result, offsets = bytearray(b"%PDF-1.4\n"), [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(result)


class PDFTests(unittest.TestCase):
    def test_text_and_page_locator(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reg.pdf"
            path.write_bytes(pdf_bytes("Contract approval requires complete documents."))
            sections = extract(path)
            self.assertEqual(sections[0]["locator"], "стр. 1")
            self.assertIn("Contract approval requires complete documents.", sections[0]["text"])

    def test_empty_page_is_not_silently_lost(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scan.pdf"
            path.write_bytes(pdf_bytes(""))
            with self.assertRaisesRegex(ValueError, "OCR"):
                extract(path)


if __name__ == "__main__":
    unittest.main()
