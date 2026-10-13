"""Standard Ed25519 signatures; private keys never enter the clearing ledger."""
import hashlib
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

DOMAIN = b'atelier-mutual-credit-v1\x00'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def public_hex(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw,
                                         serialization.PublicFormat.Raw).hex()


def account_id(public_key):
    if not isinstance(public_key, str) or len(public_key) != 64:
        raise ValueError('An Ed25519 public key must contain 32 bytes')
    raw = bytes.fromhex(public_key)
    if len(raw) != 32:
        raise ValueError('An Ed25519 public key must contain 32 bytes')
    return hashlib.sha256(raw).hexdigest()


def sign(key, payload):
    return key.sign(DOMAIN + canonical(payload)).hex()


def verify(public_key, payload, signature):
    try:
        raw, sig = bytes.fromhex(public_key), bytes.fromhex(signature)
        if len(raw) != 32 or len(sig) != 64:
            raise ValueError('Invalid signature or public key length')
        Ed25519PublicKey.from_public_bytes(raw).verify(sig, DOMAIN + canonical(payload))
    except (InvalidSignature, ValueError, TypeError) as error:
        raise ValueError('Invalid owner signature') from error


def create_key_file(path, password):
    if len(password) < 12 or len(password.encode('utf-8')) > 1024:
        raise ValueError('Choose a passphrase of at least 12 characters (maximum 1024 UTF-8 bytes)')
    path = Path(path)
    if not path.parent.is_dir():
        raise ValueError('The key file parent directory must already exist')
    key = Ed25519PrivateKey.generate()
    encrypted = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.BestAvailableEncryption(password.encode('utf-8')))
    from v2.storage import OutputBudget
    OutputBudget(path.parent, 10_000_000)._check(len(encrypted))
    # Exclusive creation; never replace a participant's existing key.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as file:
        file.write(encrypted)
    return {'account_id': account_id(public_hex(key)), 'public_key': public_hex(key)}


def load_key_file(path, password):
    path = Path(path)
    if path.stat().st_size > 8192:
        raise ValueError('Unexpectedly large private key file')
    key = serialization.load_pem_private_key(path.read_bytes(), password.encode('utf-8'))
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('An Ed25519 owner key is required')
    return key
