"""Source archive of the licensed network only, with a strict file selection."""
import io
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DOCS = ('README.md', 'LICENSE', 'NOTICE.md', 'CHANGELOG.md', 'CONTRIBUTING.md', 'GOVERNANCE.md',
        'SECURITY.md', 'PUBLICATION.md', 'requirements-network.txt', '.gitignore', '.gitattributes')


def public_files(root=ROOT):
    root = Path(root).resolve()
    paths = [root/name for name in DOCS]
    paths.append(root/'v2/storage.py')
    paths.extend(root/package/'results/.gitkeep' for package in ('exchange', 'testnet', 'provenance', 'economy'))
    for package in ('exchange', 'testnet', 'provenance', 'economy'):
        for pattern in ('*.py', '*.md', 'requirements*.txt', '*.cnf', 'tests/*.py'):
            paths.extend((root/package).glob(pattern))
    paths.append(root/'exchange/tests/fixtures/legacy_v1.json')
    paths.extend((root/'scripts').glob('*.py'))
    paths.extend((root/'scripts').glob('*.ps1'))
    paths.extend((root/'.github/workflows').glob('*.yml'))
    result = []
    for path in sorted(set(paths)):
        if path.is_file():
            path.resolve().relative_to(root)
            result.append(path)
    return result


def source_archive(root=ROOT):
    root = Path(root).resolve()
    buffer, total = io.BytesIO(), 0
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in public_files(root):
            total += path.stat().st_size
            if total > 2_000_000:
                raise ValueError('Public source archive exceeds its bounded size')
            archive.write(path, path.relative_to(root).as_posix())
    return buffer.getvalue()
