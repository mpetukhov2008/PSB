"""Import a local organizer corpus. Originals stay outside the public repository."""
import argparse
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from psb.corpus import save_corpus


def main():
    parser = argparse.ArgumentParser(description='Импорт базы знаний ПСБ из ZIP')
    parser.add_argument('archive')
    parser.add_argument('--output', default='data/knowledge.json')
    args = parser.parse_args()
    try:
        if Path(args.archive).resolve() == Path(args.output).resolve():
            raise ValueError('Нельзя перезаписывать оригинал')
        value = save_corpus(args.archive, args.output)
        print(f"Импортировано документов: {len(value['documents'])}; база: provided")
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        parser.exit(2, f'Ошибка импорта: {exc}\n')


if __name__ == '__main__':
    main()
