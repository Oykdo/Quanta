from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
import io
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from exchange.crypto import sign
from provenance.record import ROOT
from testnet.client import Client, Wallet, RemoteError
from testnet.http import Server
from testnet.node import Node
from testnet.tls import make_ca, make_csr, issue_client, server_context

PASSWORD = 'synthetic_tls_test_password'


class MutualTlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT/'testnet')
        self.folder = Path(self.tmp.name)
        self.a, self.b, self.reserve = Wallet(), Wallet(), Wallet()
        self.node = Node.create(self.folder/'network', self.reserve.account, [self.a.account, self.b.account], 100)
        self.pki = self.folder/'pki'
        make_ca(self.pki, PASSWORD, ['127.0.0.1'])
        self.credentials = {}
        for name, wallet in (('a', self.a), ('b', self.b), ('reserve', self.reserve)):
            key = self.folder/f'{name}.key.pem'
            key.write_bytes(wallet.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                     serialization.BestAvailableEncryption(PASSWORD.encode())))
            _, cert = issue_client(self.pki, make_csr(wallet.key), PASSWORD,
                                   {self.a.account, self.b.account, self.reserve.account})
            certificate = self.folder/f'{name}.crt'
            certificate.write_bytes(cert)
            self.credentials[name] = (certificate, key)
        self.server = Server(self.node, tls_context=server_context(self.pki/'ca.crt', self.pki/'server.crt',
                                                                 self.pki/'server.key.pem', PASSWORD))
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.ca = self.connect('a')
        self.cb = self.connect('b')
        self.cr = self.connect('reserve')
        self.cr.join(self.reserve, 200, 0)
        self.ca.join(self.a, 100, 200)
        self.cb.join(self.b, 100, 200)
        self.cr.transfer(self.reserve, self.a, 100, self.node.primary_resource)
        self.cr.transfer(self.reserve, self.b, 100, self.node.primary_resource)

    def connect(self, name, ca=None):
        cert, key = self.credentials[name]
        return Client(self.server.url, self.node.ledger.ledger_id, ca or self.pki/'ca.crt', cert, key, PASSWORD)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=5)
        self.node.close()
        self.tmp.cleanup()

    def test_two_distinct_owner_clients_exchange_over_mutual_tls(self):
        self.assertTrue(self.server.url.startswith('https://'))
        self.assertEqual(self.ca.account_state(self.a)['balance'], 100)
        self.ca.transfer(self.a, self.b, 5, 'service')
        self.assertEqual(self.cb.account_state(self.b)['balance'], 105)
        self.assertEqual(self.node.audit()['balance_sum'], 0)

    def test_client_without_certificate_cannot_connect(self):
        import ssl
        context = ssl.create_default_context(cafile=str(self.pki/'ca.crt'))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
        with self.assertRaises((OSError, urllib.error.URLError)):
            opener.open(self.server.url+'/health', timeout=5)

    def test_wrong_authority_is_rejected(self):
        other = self.folder/'other_ca'
        make_ca(other, PASSWORD, ['127.0.0.1'])
        with self.assertRaises((OSError, urllib.error.URLError)):
            self.connect('a', other/'ca.crt')

    def test_certificate_cannot_relay_another_owners_authenticated_read(self):
        challenge = self.ca.request('/challenge/'+self.b.account)
        with self.assertRaises(RemoteError) as error:
            self.ca.request('/account', {'payload': challenge, 'signatures': {self.b.account: sign(self.b.key, challenge)}})
        self.assertEqual(error.exception.status, 403)
        state = self.cb.request('/account', {'payload': challenge, 'signatures': {self.b.account: sign(self.b.key, challenge)}})
        self.assertEqual(state['account'], self.b.account)

    def test_plain_lan_listener_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'requires mutual TLS'):
            Server(self.node, host='192.168.1.10')

    def test_server_hostname_must_match_certificate(self):
        pki = self.folder/'wrong_name'
        make_ca(pki, PASSWORD, ['wrong.example'])
        _, cert = issue_client(pki, make_csr(self.a.key), PASSWORD, {self.a.account})
        path = self.folder/'wrong_name_client.crt'
        path.write_bytes(cert)
        server = Server(self.node, tls_context=server_context(pki/'ca.crt', pki/'server.crt', pki/'server.key.pem', PASSWORD))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises((OSError, urllib.error.URLError)) as error:
                Client(server.url, self.node.ledger.ledger_id, pki/'ca.crt', path, self.credentials['a'][1], PASSWORD)
            self.assertIn('mismatch', str(error.exception).lower())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_owner_cli_requires_explicit_consent_for_both_signatures(self):
        from testnet import owner
        proposal, first, second = (self.folder/name for name in ('proposal.json', 'first.json', 'second.json'))

        def command(identity, action, answer='AUTORISER'):
            certificate, key = self.credentials[identity]
            args = ['testnet.owner', '--url', self.server.url, '--ledger-id', self.node.ledger.ledger_id,
                    '--ca', str(self.pki/'ca.crt'), '--certificate', str(certificate), '--key', str(key), *action]
            with patch('sys.argv', args), patch('getpass.getpass', return_value=PASSWORD), \
                    patch('builtins.input', return_value=answer), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                owner.main()

        command('a', ['propose', '--to', self.b.account, '--payee-nonce', '1', '--amount', '3',
                      '--resource-id', 'service', '--out', str(proposal)])
        before = self.node.head
        with self.assertRaises(SystemExit) as error:
            command('a', ['sign', '--proposal', str(proposal), '--out', str(first)], 'REFUSER')
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(first.exists())
        self.assertEqual(self.node.head, before)
        command('a', ['sign', '--proposal', str(proposal), '--out', str(first)])
        command('b', ['sign', '--proposal', str(proposal), '--out', str(second)])
        command('a', ['commit', '--authorizations', str(first), str(second)])
        self.assertEqual(self.ca.account_state(self.a)['balance'], 97)
        self.assertEqual(self.cb.account_state(self.b)['balance'], 103)
