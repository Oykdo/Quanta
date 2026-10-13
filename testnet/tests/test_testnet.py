from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile

from exchange.crypto import sign
from provenance.record import ROOT, verify_proof
from testnet.client import Client, RemoteError, Wallet
from testnet.http import Server
from testnet.node import Node
from v2.storage import BudgetExceeded


class TestnetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT/'testnet')
        self.wallets, self.reserve = [Wallet() for _ in range(3)], Wallet()
        self.node = Node.create(Path(self.tmp.name)/'network', self.reserve.account,
                                [w.account for w in self.wallets], 100, 2_000_000)
        self.server = Server(self.node)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = Client(self.server.url, self.node.ledger.ledger_id)
        self.client.join(self.reserve, 300, 0)
        for wallet in self.wallets:
            self.client.join(wallet, 100, 200)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.node.close()
        self.tmp.cleanup()

    def distribute(self):
        for wallet in self.wallets:
            self.client.transfer(self.reserve, wallet, 100, self.node.primary_resource)

    def test_primary_allocation_is_equal_balanced_and_once_per_wallet(self):
        self.distribute()
        report = self.node.audit()
        self.assertEqual(report['allocation_count'], 3)
        self.assertEqual(report['reserve_balance'], -300)
        self.assertEqual(report['balance_sum'], 0)
        self.assertEqual({report['balances'][w.account] for w in self.wallets}, {100})
        before = self.node.head
        with self.assertRaisesRegex(RemoteError, 'already received'):
            self.client.transfer(self.reserve, self.wallets[0], 100, self.node.primary_resource)
        self.assertEqual(self.node.head, before)
        with self.assertRaisesRegex(RemoteError, 'exact primary'):
            self.client.transfer(self.reserve, self.wallets[0], 1, 'ordinary_reserve_transfer')

    def test_missing_cosignature_and_unlisted_wallet_are_refused(self):
        p = self.client.template.transfer_authorization(self.reserve.account, self.wallets[0].account,
                                                       100, self.node.primary_resource, 0, 0)
        before = self.node.head
        with self.assertRaises(RemoteError):
            self.client.submit(p, [self.reserve])
        with self.assertRaisesRegex(RemoteError, 'not enrolled'):
            self.client.join(Wallet(), 100, 200)
        self.assertEqual(self.node.head, before)
        self.assertEqual(self.node.audit()['allocation_count'], 0)

    def test_idempotent_retry_and_stale_nonce_survive_restart(self):
        self.distribute()
        p = self.client.template.transfer_authorization(self.wallets[0].account, self.wallets[1].account,
                                                       1, 'service', 1, 1)
        sigs = {w.account: sign(w.key, p) for w in self.wallets[:2]}
        accepted = self.node.commit(p, sigs)
        path = self.node.path
        self.node.close()
        reopened = Node(path)
        try:
            result = reopened.commit(p, sigs)
            self.assertEqual(result['status'], 'already_committed')
            self.assertEqual(result['receipt']['hash'], accepted['receipt']['hash'])
            stale = {**p, 'request_id': secrets.token_hex(16)}
            with self.assertRaisesRegex(ValueError, 'stale authorization nonce'):
                reopened.commit(stale, {w.account: sign(w.key, stale) for w in self.wallets[:2]})
            self.assertEqual(reopened.accounts[self.wallets[0].account]['balance'], 99)
            self.assertEqual(reopened.accounts[self.wallets[1].account]['balance'], 101)
            self.assertEqual(reopened.audit()['balance_sum'], 0)
        finally:
            reopened.close()

    def test_signed_read_challenge_is_one_use_and_invalid_signature_does_not_consume_it(self):
        self.distribute()
        wallet = self.wallets[0]
        challenge = self.client.request('/challenge/'+wallet.account)
        with self.assertRaises(RemoteError) as error:
            self.client.request('/account', {'payload': challenge, 'signatures': {wallet.account: '00'*64}})
        self.assertEqual(error.exception.status, 403)
        body = {'payload': challenge, 'signatures': {wallet.account: sign(wallet.key, challenge)}}
        state = self.client.request('/account', body)
        self.assertEqual(state['nonce'], 1)
        self.assertEqual(state['balance'], 100)
        with self.assertRaisesRegex(RemoteError, 'Replayed'):
            self.client.request('/account', body)

    def test_parallel_uses_of_same_wallet_nonce_cannot_both_commit(self):
        self.distribute()
        proposals = [self.client.template.transfer_authorization(self.wallets[0].account,
                     self.wallets[n].account, 1, 'service', 1, 1) for n in (1, 2)]
        barrier = threading.Barrier(2)

        def submit(n):
            p = proposals[n]
            sigs = {w.account: sign(w.key, p) for w in (self.wallets[0], self.wallets[n+1])}
            barrier.wait()
            try:
                self.node.commit(p, sigs)
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(submit, (0, 1))), 1)
        self.assertEqual(self.node.accounts[self.wallets[0].account]['balance'], 99)
        self.assertEqual(self.node.audit()['balance_sum'], 0)

    def test_folder_budget_failure_rolls_back_and_cleans_no_user_files(self):
        p = self.client.template.transfer_authorization(self.reserve.account, self.wallets[0].account,
                                                       100, self.node.primary_resource, 0, 0)
        reserve = self.node.db_limit+self.node.db_limit//4+65536+8192
        extra = self.node.storage.max_bytes-self.node.storage.used_bytes()-reserve+1
        self.node.storage.write_bytes('test_padding.bin', b'x'*extra)
        before = self.node.path.read_bytes()
        with self.assertRaises(BudgetExceeded):
            self.node.commit(p, {w.account: sign(w.key, p) for w in (self.reserve, self.wallets[0])})
        self.assertEqual(self.node.path.read_bytes(), before)
        self.assertEqual(self.node.audit()['allocation_count'], 0)
        self.assertLessEqual(self.node.storage.used_bytes(), self.node.storage.max_bytes)

    def test_wrong_ledger_and_oversized_body_fail(self):
        with self.assertRaisesRegex(ValueError, 'expected testnet'):
            Client(self.server.url, '0'*64)
        with self.assertRaises(RemoteError) as error:
            self.client.request('/commit', {'payload': {'padding': 'x'*8193}, 'signatures': {}})
        self.assertEqual(error.exception.status, 413)

    def test_source_endpoint_exposes_agpl_sources_without_wallet_data(self):
        with self.client.opener.open(self.server.url+'/source', timeout=10) as response:
            self.assertEqual(response.headers['Content-Type'], 'application/zip')
            payload = response.read(2_000_001)
        self.assertLessEqual(len(payload), 2_000_000)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            self.assertIn('LICENSE', names)
            self.assertIn('testnet/vault.py', names)
            self.assertFalse(any(name.endswith(('.vault', '.pem', '.sqlite3')) for name in names))
            self.assertFalse(any('/results/' in name and not name.endswith('/.gitkeep') for name in names))
        self.assertEqual(self.client.health['software']['license'], 'AGPL-3.0-only')


class TestnetScaleTests(unittest.TestCase):
    def test_genesis_supports_thousand_wallets_plus_reserve(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'testnet') as tmp:
            reserve = Wallet()
            ids = [hashlib.sha256(f'test-{n}'.encode()).hexdigest() for n in range(1000)]
            node = Node.create(Path(tmp)/'network', reserve.account, ids)
            try:
                self.assertEqual(node.header['policy']['max_accounts'], 1001)
                self.assertEqual(node.health()['wallet_target'], 1000)
            finally:
                node.close()

    def test_cli_distribution_persistence_and_creator_provenance(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'testnet') as tmp:
            out = Path(tmp)/'network'
            result = subprocess.run([sys.executable, '-B', '-m', 'testnet', 'run', '--wallets', '20',
                                     '--allocation', '100', '--out', str(out)],
                                     cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout[result.stdout.index('{\n'):])
            self.assertEqual(report['primary_allocation_count'], 20)
            self.assertEqual(report['initial_reserve_balance'], -2000)
            self.assertTrue(report['exact_retry_idempotent'])
            self.assertTrue(report['stale_nonce_refused'])
            node = Node(out/'ledger.sqlite3', writable=False)
            try:
                self.assertEqual(node.audit()['balance_sum'], 0)
                self.assertEqual(node.audit()['allocation_count'], 20)
            finally:
                node.close()
            self.assertFalse((out/'ledger.sqlite3.lock').exists())
            self.assertEqual(verify_proof(out/'provenance')['author_declared'], 'jeremy zgonec')
