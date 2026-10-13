"""Source/model snapshots; no private keys, virtual environments or corpus copies."""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import zipfile

from v2.storage import OutputBudget, BudgetExceeded

ROOT = Path(__file__).resolve().parents[1]
AUTHOR = 'jeremy zgonec'
MAGIC = b'ATPROV1\x00'
HEADER = struct.Struct('>8sI32s')
SOURCE_PATTERNS = ('*.py', '*.md', 'LICENSE', '.gitignore', '.gitattributes', 'GUIDE*', 'requirements*.txt',
                   'scripts/*.py', 'scripts/*.ps1', '.github/workflows/*.yml', 'tests/*.py',
                   'v2/*.py', 'v2/*.txt', 'v2/tests/*.py',
                   'exchange/*.py', 'exchange/*.md', 'exchange/*.txt', 'exchange/tests/*.py', 'exchange/tests/fixtures/*.json',
                   'testnet/*.py', 'testnet/*.md', 'testnet/tests/*.py',
                   'economy/*.py', 'economy/*.md', 'economy/tests/*.py',
                   'provenance/*.py', 'provenance/*.md', 'provenance/*.cnf', 'provenance/tests/*.py')
DATA_PATTERNS = ('resultats/*.json', 'v2/results/**/data.json', 'v2/results/**/protocol.json',
                 'v2/results/**/report.json', 'v2/results/**/consensus_report.json',
                 'exchange/results/**/ledger.json', 'exchange/results/**/demo_report.json',
                 'testnet/results/**/ledger.sqlite3', 'testnet/results/**/report.json',
                 'testnet/results/**/wallets.json', 'testnet/results/**/branches.json',
                 'testnet/results/**/trace_wallet-*.json', 'economy/results/**/report.json')
MODEL_PATTERNS = ('resultats/checkpoints/*.pt', 'v2/results/**/checkpoints/*.pt')


def sha256(payload):
    return hashlib.sha256(payload).hexdigest()


def encode_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')


def encode_record(manifest_bytes):
    return HEADER.pack(MAGIC, len(manifest_bytes), hashlib.sha256(manifest_bytes).digest()) + manifest_bytes


def decode_record(payload):
    if len(payload) < HEADER.size:
        raise ValueError('Truncated binary provenance record')
    magic, size, expected = HEADER.unpack(payload[:HEADER.size])
    body = payload[HEADER.size:]
    if magic != MAGIC or size != len(body) or expected != hashlib.sha256(body).digest():
        raise ValueError('Altered binary provenance record')
    return body


def _safe_name(name):
    path = PurePosixPath(name)
    if not isinstance(name, str) or not name or path.is_absolute() or '..' in path.parts \
            or '\\' in name or ':' in name:
        raise ValueError('Unsafe snapshot member path')
    return name


def _selected(root, patterns):
    selected = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file():
                resolved = path.resolve()
                resolved.relative_to(root)
                selected.add(resolved)
    return sorted(selected, key=lambda p: p.relative_to(root).as_posix())


def _file_digest(path):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(1024*1024), b''):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f'File changed during snapshot: {path.name}')
    return digest.hexdigest(), before.st_size


def create_proof(root=ROOT, author=AUTHOR, output=None, max_output_bytes=10_000_000,
                 model_paths=None, storage=None):
    root = Path(root).resolve()
    if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= 1_000_000_000:
        raise ValueError('Snapshot output budget must be between 1 byte and 1 GB')
    if not root.is_dir():
        raise ValueError('Project root must exist')
    if not isinstance(author, str) or not author.strip() or len(author) > 128 \
            or any(ord(c) < 32 for c in author):
        raise ValueError('A printable declared author name is required')
    author = author.strip()
    now = datetime.now(timezone.utc)
    tag = now.strftime('%Y%m%dT%H%M%S%fZ')
    slug = re.sub(r'[^a-zA-Z0-9_-]+', '_', author).strip('_') or 'author'
    folder = Path(output).resolve() if output is not None else root/'provenance/results'/f'{slug}_{tag}'
    if folder.exists():
        raise FileExistsError('A provenance snapshot must never overwrite an existing folder')
    if storage is None:
        folder.parent.mkdir(parents=True, exist_ok=True)
        storage = OutputBudget(folder.parent, max_output_bytes)
    folder.relative_to(storage.root)
    archive_name = 'creation.zip'
    archived, inventory = {}, []
    source_paths = _selected(root, SOURCE_PATTERNS)
    selected_models = _selected(root, MODEL_PATTERNS) if model_paths is None else [Path(p).resolve() for p in model_paths]
    seen, raw_size = set(), 0
    for kind, paths in (('source', source_paths), ('model', selected_models)):
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            try:
                name = path.relative_to(root).as_posix()
                source_path = name
            except ValueError:
                if kind != 'model':
                    raise
                name, source_path = 'external_models/'+path.name, None
            _safe_name(name)
            if name in archived:
                raise ValueError('Duplicate model archive name')
            before = path.stat()
            size = before.st_size
            if raw_size + size > max_output_bytes:
                raise BudgetExceeded('Raw sources/models exceed the snapshot input budget')
            with path.open('rb') as file:
                payload = file.read(max_output_bytes-raw_size+1)
            if len(payload) > max_output_bytes-raw_size:
                raise BudgetExceeded('Snapshot input grew beyond its budget')
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError(f'File changed during snapshot: {path.name}')
            raw_size += len(payload)
            archived[name] = payload
            inventory.append({'path': name, 'source_path': source_path, 'kind': kind,
                              'bytes': len(payload), 'sha256': sha256(payload), 'archived': True})
    if not source_paths:
        raise ValueError('No project sources were selected')
    for path in _selected(root, DATA_PATTERNS):
        if path not in seen:
            digest, size = _file_digest(path)
            name = path.relative_to(root).as_posix()
            inventory.append({'path': name, 'source_path': name, 'kind': 'data_fingerprint_only',
                              'bytes': size, 'sha256': digest, 'archived': False})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, payload in sorted(archived.items()):
            info = zipfile.ZipInfo(name, now.timetuple()[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, payload)
    archive_bytes = buffer.getvalue()
    manifest = {'format': 1, 'project': root.name, 'author_declared': author,
                'created_utc_local_clock': now.isoformat().replace('+00:00', 'Z'),
                'attribution': 'Creator name declared by the user; not an identity certificate',
                'timestamp_scope': 'Local clock; an independently verified RFC 3161 token can anchor this record',
                'archive': {'file': archive_name, 'bytes': len(archive_bytes), 'sha256': sha256(archive_bytes)},
                'files': sorted(inventory, key=lambda row: row['path']),
                'storage_policy': 'Sources and selected models archived; datasets/journals fingerprinted without copying',
                'max_output_bytes': max_output_bytes}
    manifest_bytes = encode_json(manifest)
    record_bytes = encode_record(manifest_bytes)
    fingerprints = ''.join(f'{sha256(payload)}  {name}\n' for name, payload in
                           ((archive_name, archive_bytes), ('manifest.json', manifest_bytes), ('creation.bin', record_bytes)))
    payloads = {archive_name: archive_bytes, 'manifest.json': manifest_bytes,
                'creation.bin': record_bytes, 'SHA256SUMS.txt': fingerprints.encode('ascii')}
    # Check the entire new pack before creating its directory.
    storage._check(sum(len(value) for value in payloads.values()))
    folder.mkdir(parents=True, exist_ok=False)
    for name, payload in payloads.items():
        storage.write_bytes((folder/name).relative_to(storage.root), payload)
    return {'folder': str(folder), 'author_declared': author,
            'created_utc_local_clock': manifest['created_utc_local_clock'],
            'record_sha256': sha256(record_bytes), 'archived_files': len(archived),
            'fingerprinted_only_files': len(inventory)-len(archived),
            'proof_bytes': sum(len(p) for p in payloads.values()), 'timestamp_status': 'local_only'}


def verify_proof(folder, project_root=None):
    folder = Path(folder).resolve()
    record = folder/'creation.bin'
    if record.stat().st_size > 10_000_000:
        raise ValueError('Unexpectedly large provenance record')
    record_bytes = record.read_bytes()
    manifest_bytes = decode_record(record_bytes)
    if (folder/'manifest.json').read_bytes() != manifest_bytes:
        raise ValueError('Manifest differs from the binary record')
    manifest = json.loads(manifest_bytes)
    if manifest.get('format') != 1 or not isinstance(manifest.get('files'), list):
        raise ValueError('Unsupported provenance format')
    budget = manifest.get('max_output_bytes')
    if type(budget) is not int or not 1 <= budget <= 1_000_000_000:
        raise ValueError('Invalid provenance budget')
    if manifest['archive']['file'] != 'creation.zip':
        raise ValueError('Unsupported archive name')
    archive_path = folder/'creation.zip'
    archive_digest, archive_size = _file_digest(archive_path)
    if archive_digest != manifest['archive']['sha256'] or archive_size != manifest['archive']['bytes']:
        raise ValueError('Archive integrity check failed')
    expected_checksums = (f'{archive_digest}  creation.zip\n'
                          f'{sha256(manifest_bytes)}  manifest.json\n'
                          f'{sha256(record_bytes)}  creation.bin\n').encode('ascii')
    if (folder/'SHA256SUMS.txt').read_bytes() != expected_checksums:
        raise ValueError('Fingerprint list differs from the verified artifacts')
    names = [row['path'] for row in manifest['files']]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate manifest paths')
    expected = {row['path']: row for row in manifest['files'] if row['archived'] is True}
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) != len(expected) or {member.filename for member in members} != set(expected):
            raise ValueError('Archive members differ from the manifest')
        for member in members:
            _safe_name(member.filename)
            row = expected[member.filename]
            if member.file_size != row['bytes'] or member.file_size > budget:
                raise ValueError('Unexpected archive member size')
            digest, size = hashlib.sha256(), 0
            with archive.open(member) as file:
                for chunk in iter(lambda: file.read(1024*1024), b''):
                    size += len(chunk)
                    if size > row['bytes']:
                        raise ValueError('Archive member exceeds its declared size')
                    digest.update(chunk)
            if size != row['bytes'] or digest.hexdigest() != row['sha256']:
                raise ValueError('Archived file integrity check failed')
    current_checked = 0
    if project_root is not None:
        root = Path(project_root).resolve()
        for row in manifest['files']:
            if row['source_path'] is not None:
                _safe_name(row['source_path'])
                path = (root/row['source_path']).resolve()
                path.relative_to(root)
                digest, size = _file_digest(path)
                if digest != row['sha256'] or size != row['bytes']:
                    raise ValueError(f'Current project differs from snapshot: {row["source_path"]}')
                current_checked += 1
    return {'verified': True, 'author_declared': manifest['author_declared'],
            'created_utc_local_clock': manifest['created_utc_local_clock'],
            'record_sha256': sha256(record_bytes), 'archived_files_verified': len(expected),
            'fingerprinted_only_files': len(names)-len(expected),
            'current_project_files_checked': current_checked, 'timestamp_status': 'local_only'}
