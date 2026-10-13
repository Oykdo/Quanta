"""RFC 3161 via FreeTSA; only a SHA-256 imprint and nonce leave the machine."""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import urllib.request

from provenance.record import verify_proof
from v2.storage import OutputBudget

TSA_URL = 'https://freetsa.org/tsr'
CA_URL = 'https://freetsa.org/files/cacert.pem'
# Raw PEM fingerprint published at https://freetsa.org/index_en.php (October 2026).
CA_SHA256 = '2151b61137ffa86bf664691ba67e7da0b19f98c758e3d228d5d8ebf27e044438'
MAX_REPLY = 256_000


def openssl_path(explicit=None):
    candidates = ([explicit] if explicit else []) + [shutil.which('openssl'),
                  str(Path(sys.base_prefix)/'Library/bin/openssl.exe')]
    for path in candidates:
        if path and Path(path).is_file():
            return str(Path(path).resolve())
    raise ValueError('OpenSSL is required for independent RFC 3161 verification')


def run_openssl(executable, arguments):
    environment = os.environ.copy()
    environment.setdefault('OPENSSL_CONF', str(Path(__file__).with_name('openssl.cnf')))
    try:
        result = subprocess.run([executable, *arguments], capture_output=True, timeout=30, env=environment)
    except subprocess.TimeoutExpired as error:
        raise ValueError('OpenSSL verification timed out') from error
    if result.returncode:
        raise ValueError(result.stderr.decode('utf-8', errors='replace').strip())
    return result.stdout


def _fetch(url, payload=None):
    headers = {'User-Agent': 'Atelier-Provenance/1.0'}
    if payload is not None:
        headers.update({'Content-Type': 'application/timestamp-query', 'Accept': 'application/timestamp-reply'})
    request = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(request, timeout=30, context=ssl.create_default_context()) as response:
        body = response.read(MAX_REPLY+1)
    if not body or len(body) > MAX_REPLY:
        raise ValueError('Timestamp service response is empty or exceeds the size limit')
    return body


def _tsa_time(text):
    match = re.search(r'^Time stamp:\s+(\w{3})\s+(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})'
                      r'(?:\.(\d+))?\s+(\d{4})\s+GMT\s*$', text, re.MULTILINE)
    if not match:
        raise ValueError('The RFC 3161 response does not expose a readable UTC timestamp')
    month, day, hour, minute, second, fraction, year = match.groups()
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    return datetime(int(year), months.index(month)+1, int(day), int(hour), int(minute), int(second),
                    int((fraction or '').ljust(6, '0')[:6]), tzinfo=timezone.utc)


def verify_timestamp(folder, executable=None):
    folder = Path(folder).resolve()
    local = verify_proof(folder)
    ca = (folder/'freetsa_ca.pem').read_bytes()
    if hashlib.sha256(ca).hexdigest() != CA_SHA256:
        raise ValueError('The timestamp authority root differs from the independently pinned fingerprint')
    for name in ('timestamp.tsq', 'timestamp.tsr'):
        if (folder/name).stat().st_size > MAX_REPLY:
            raise ValueError('Oversized timestamp evidence')
    executable = openssl_path(executable)
    arguments = ['ts', '-verify', '-CAfile', str(folder/'freetsa_ca.pem'), '-in', str(folder/'timestamp.tsr')]
    # Validate both the request nonce and, independently, the actual binary record.
    run_openssl(executable, [*arguments, '-queryfile', str(folder/'timestamp.tsq')])
    run_openssl(executable, [*arguments, '-data', str(folder/'creation.bin')])
    details = run_openssl(executable, ['ts', '-reply', '-in', str(folder/'timestamp.tsr'), '-text']).decode('utf-8')
    when = _tsa_time(details)
    return {**local, 'timestamp_status': 'rfc3161_verified_freetsa',
            'tsa_url': TSA_URL, 'tsa_utc': when.isoformat().replace('+00:00', 'Z'),
            'tsa_ca_sha256': CA_SHA256,
            'trust_scope': 'FreeTSA authority signature and request imprint verified; no author identity certificate'}


def stamp_proof(folder, max_output_bytes=10_000_000, executable=None):
    folder = Path(folder).resolve()
    local = verify_proof(folder)
    if any((folder/name).exists() for name in ('timestamp.tsq', 'timestamp.tsr', 'freetsa_ca.pem', 'timestamp.json')):
        raise FileExistsError('Timestamp evidence already exists; it must not be overwritten')
    executable = openssl_path(executable)
    request = run_openssl(executable, ['ts', '-query', '-digest', local['record_sha256'], '-sha256', '-cert'])
    if not request or len(request) > 8192:
        raise ValueError('Unexpected RFC 3161 request size')
    ca = _fetch(CA_URL)
    if hashlib.sha256(ca).hexdigest() != CA_SHA256:
        raise ValueError('FreeTSA root fingerprint changed; independent confirmation is required')
    reply = _fetch(TSA_URL, request)
    storage = OutputBudget(folder.parent, max_output_bytes)
    storage._check(len(request)+len(ca)+len(reply)+8192)
    for name, payload in (('timestamp.tsq', request), ('freetsa_ca.pem', ca), ('timestamp.tsr', reply)):
        storage.write_bytes(folder.name+'/'+name, payload)
    result = verify_timestamp(folder, executable)
    storage.write_json(folder.name+'/timestamp.json', result)
    return result
