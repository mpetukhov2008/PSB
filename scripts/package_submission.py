"""Build platform ZIP from an explicit code-only allowlist."""
import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    files = [ROOT / 'solution.py', ROOT / 'requirements.txt']
    files += sorted((ROOT / 'psb').glob('*.py'))
    files += sorted((ROOT / 'psb' / 'static').glob('*'))
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if path.is_file():
                archive.write(path, path.relative_to(ROOT).as_posix())
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='ZIP для платформы без ключей и данных')
    parser.add_argument('--output', default=str(ROOT / 'artifacts' / 'PSB_submission.zip'))
    print(build(parser.parse_args().output))
