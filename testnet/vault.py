"""Encrypted recovery of SYNTHETIC client keys, never a public custody service."""
import json
from pathlib import Path
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from exchange.crypto import canonical, public_hex
from testnet.client import Wallet

MAGIC = b'QWVAULT1'
MAX_BYTES = 2_000_000


def validate_password(password):
    if not isinstance(password, str) or len(password) < 12 or len(password.encode('utf-8')) > 1024:
        raise ValueError('Vault passphrase must contain at least 12 characters and at most 1024 UTF-8 bytes')


def _key(password, salt):
    validate_password(password)
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode('utf-8'))


def _entry(wallet):
    seed = wallet.key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                   serialization.NoEncryption())
    return {'account': wallet.account, 'seed_hex': seed.hex()}


def save_vault(path, ledger_id, reserve, wallets, password, storage):
    validate_password(password)
    path = Path(path).resolve()
    path.relative_to(storage.root)
    if path.exists():
        raise FileExistsError('A wallet vault must not be overwritten')
    document = {'version': 1, 'scope': 'synthetic_wallet_testnet_only', 'ledger_id': ledger_id,
                'reserve': _entry(reserve), 'wallets': [_entry(wallet) for wallet in wallets]}
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    header = MAGIC+salt+nonce
    payload = header+AESGCM(_key(password, salt)).encrypt(nonce, canonical(document), header)
    if len(payload) > MAX_BYTES:
        raise ValueError('Synthetic wallet vault exceeds its size limit')
    storage._check(len(payload))
    with path.open('xb') as file:
        file.write(payload)


def load_vault(path, password, node):
    path = Path(path)
    if not 52 <= path.stat().st_size <= MAX_BYTES:
        raise ValueError('Invalid wallet vault size')
    payload = path.read_bytes()
    if payload[:8] != MAGIC:
        raise ValueError('Unsupported wallet vault format')
    salt, nonce = payload[8:24], payload[24:36]
    try:
        clear = AESGCM(_key(password, salt)).decrypt(nonce, payload[36:], payload[:36])
    except InvalidTag as error:
        raise ValueError('Wrong passphrase or altered wallet vault') from error
    document = json.loads(clear)
    if not isinstance(document, dict) or set(document) != {'version', 'scope', 'ledger_id', 'reserve', 'wallets'} \
            or type(document['version']) is not int or document['version'] != 1 \
            or document['scope'] != 'synthetic_wallet_testnet_only' or document['ledger_id'] != node.ledger.ledger_id:
        raise ValueError('Vault does not belong to this synthetic ledger')

    def restore(entry):
        if not isinstance(entry, dict) or set(entry) != {'account', 'seed_hex'}:
            raise ValueError('Malformed wallet vault entry')
        seed = bytes.fromhex(entry['seed_hex'])
        if len(seed) != 32:
            raise ValueError('Invalid wallet seed length')
        wallet = Wallet(Ed25519PrivateKey.from_private_bytes(seed))
        if wallet.account != entry['account']:
            raise ValueError('Vault key does not match its recorded public address')
        current = node.accounts.get(wallet.account)
        if current is not None:
            if current['public_key'] != public_hex(wallet.key):
                raise ValueError('Vault key differs from the enrolled ledger key')
            # Nonces are recovered from the VERIFIED ledger, never from the vault.
            wallet.nonce = current['nonce']
        return wallet

    reserve = restore(document['reserve'])
    wallets = [restore(entry) for entry in document['wallets']]
    ids = [wallet.account for wallet in wallets]
    if reserve.account != node.plan['reserve_account'] or len(ids) != len(set(ids)) or set(ids) != node.eligible:
        raise ValueError('Vault wallet set differs from the original distribution plan')
    return reserve, wallets
