"""Synthetic client wallets: keys stay in the client process, signatures cross HTTP."""
from dataclasses import dataclass, field
import json
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exchange.crypto import account_id, canonical, public_hex, sign
from exchange.ledger import Ledger, digest


class RemoteError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


@dataclass
class Wallet:
    key: object = field(default_factory=Ed25519PrivateKey.generate, repr=False)
    nonce: int = 0

    @property
    def account(self):
        return account_id(public_hex(self.key))


class Client:
    def __init__(self, url, expected_ledger_id=None, ca=None, certificate=None, key=None, password=None):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username \
                or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise ValueError('Use an exact HTTP loopback or authenticated HTTPS pilot URL')
        if parsed.scheme == 'http' and parsed.hostname != '127.0.0.1':
            raise ValueError('Plain HTTP is only allowed on 127.0.0.1')
        handlers = [urllib.request.ProxyHandler({})]
        if parsed.scheme == 'https':
            if not all((ca, certificate, key)):
                raise ValueError('HTTPS requires a trusted CA and the owner client certificate and key')
            from testnet.tls import client_context
            handlers.append(urllib.request.HTTPSHandler(context=client_context(ca, certificate, key, password)))
        self.url = url.rstrip('/')
        self.opener = urllib.request.build_opener(*handlers)
        self.health = self.request('/health')
        if expected_ledger_id is not None and self.health['ledger_id'] != expected_ledger_id:
            raise ValueError('Ledger identity differs from the expected testnet')
        header = self.health['header']
        self.template = Ledger({'header': header, 'accounts': {}, 'events': [], 'head': digest(header)})

    def request(self, route, body=None):
        data = None if body is None else canonical(body)
        request = urllib.request.Request(self.url+route, data=data,
                                         headers={'Content-Type': 'application/json', 'Connection': 'close'})
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(65537)
        except urllib.error.HTTPError as error:
            detail = json.loads(error.read(8192))
            raise RemoteError(error.code, detail.get('error', 'Testnet request refused')) from error
        if len(raw) > 65536:
            raise ValueError('Oversized testnet response')
        return json.loads(raw)

    def submit(self, payload, wallets):
        signatures = {wallet.account: sign(wallet.key, payload) for wallet in wallets}
        result = self.request('/commit', {'payload': payload, 'signatures': signatures})
        if payload['kind'] == 'transfer':
            for wallet in wallets:
                field = 'payer_nonce' if wallet.account == payload['payer'] else 'payee_nonce'
                wallet.nonce = max(wallet.nonce, payload[field]+1)
        return result

    def join(self, wallet, debt_limit, credit_limit):
        proposal = self.template.join_proposal(public_hex(wallet.key), debt_limit, credit_limit)
        return self.submit(proposal, [wallet])

    def transfer(self, payer, payee, amount, resource_id):
        proposal = self.template.transfer_authorization(payer.account, payee.account, amount,
                                                       resource_id, payer.nonce, payee.nonce)
        return self.submit(proposal, [payer, payee])

    def account_state(self, wallet):
        challenge = self.request('/challenge/'+wallet.account)
        state = self.request('/account', {'payload': challenge,
                             'signatures': {wallet.account: sign(wallet.key, challenge)}})
        wallet.nonce = state['nonce']
        return state
