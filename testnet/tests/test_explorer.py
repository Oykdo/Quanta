import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from exchange.crypto import public_hex, sign
from provenance.record import ROOT
from testnet.client import Wallet
from testnet.explorer import catalogue, wallet_trace, branches, snapshot, write_export
from testnet.node import Node


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT/'testnet')
        self.wallets, self.reserve = [Wallet() for _ in range(12)], Wallet()
        self.node = Node.create(Path(self.tmp.name)/'network', self.reserve.account,
                                [w.account for w in self.wallets], 100)
        for wallet in [self.reserve, *self.wallets]:
            limits = (1200, 0) if wallet is self.reserve else (100, 200)
            p = self.node.ledger.join_proposal(public_hex(wallet.key), *limits)
            self.node.commit(p, {wallet.account: sign(wallet.key, p)})
        for wallet in self.wallets:
            self.transfer(self.reserve, wallet, 100, self.node.primary_resource)

    def tearDown(self):
        self.node.close()
        self.tmp.cleanup()

    def transfer(self, payer, payee, amount, resource):
        p = self.node.ledger.transfer_authorization(payer.account, payee.account, amount, resource,
              self.node.accounts[payer.account]['nonce'], self.node.accounts[payee.account]['nonce'])
        return self.node.commit(p, {w.account: sign(w.key, p) for w in (payer, payee)})

    def test_catalogue_maps_public_addresses_and_never_serializes_private_keys(self):
        state = snapshot(self.node.path)
        data = catalogue(state)
        self.assertEqual(data['wallet_count'], 12)
        self.assertEqual(data['registered_wallets'], 12)
        self.assertEqual(data['reserve']['balance_quanta'], -1200)
        text = json.dumps(data)
        for wallet in self.wallets:
            secret = wallet.key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                               serialization.NoEncryption()).hex()
            self.assertNotIn(secret, text)
        for wallet in data['wallets']:
            self.assertEqual(hashlib.sha256(bytes.fromhex(wallet['public_key_ed25519_hex'])).hexdigest(), wallet['address'])
            self.assertEqual(wallet['primary_allocation_quanta'], 100)

    def test_traces_reconstruct_incoming_outgoing_nonce_and_balance(self):
        self.transfer(self.wallets[0], self.wallets[1], 7, 'service')
        state = snapshot(self.node.path)
        first = wallet_trace(state, self.wallets[0].account)
        second = wallet_trace(state, self.wallets[1].account)
        self.assertEqual((first['balance_quanta'], second['balance_quanta']), (93, 107))
        self.assertEqual(first['operation_nonce'], 2)
        self.assertEqual(first['history_total'], 3)
        self.assertEqual(first['history'][-1]['direction'], 'outgoing')
        self.assertEqual(second['history'][-1]['direction'], 'incoming')
        self.assertEqual(first['history'][-1]['event_hash'], second['history'][-1]['event_hash'])
        self.assertEqual(wallet_trace(state, first['alias'])['address'], first['address'])
        page = wallet_trace(state, first['alias'], offset=1, limit=1)
        self.assertEqual(len(page['history']), 1)
        self.assertTrue(page['has_more'])
        self.assertEqual(wallet_trace(state, 'reserve')['balance_quanta'], -1200)

    def test_trace_checks_reconstructed_state_and_unknown_accounts(self):
        state = snapshot(self.node.path)
        altered = copy.deepcopy(state)
        altered['accounts'][self.wallets[0].account]['balance'] += 1
        with self.assertRaisesRegex(ValueError, 'Reconstructed wallet state'):
            wallet_trace(altered, self.wallets[0].account)
        with self.assertRaisesRegex(ValueError, 'Unknown wallet'):
            wallet_trace(state, 'wallet-999999')

    def test_balanced_branches_reference_one_head_and_change_no_balances(self):
        state = snapshot(self.node.path)
        before = copy.deepcopy(state)
        plan = branches(state, count=4)
        self.assertEqual(plan['branch_size_min'], 3)
        self.assertEqual(plan['branch_size_max'], 3)
        self.assertEqual((plan['peer_degree_min'], plan['peer_degree_max']), (5, 5))
        self.assertTrue(all(plan['connected_after_each_single_branch_removal'].values()))
        self.assertEqual(plan['ledger_id'], state['header']['ledger_id'])
        self.assertEqual(plan['head'], state['head'])
        self.assertEqual(state, before)
        nodes = {w['address']: set(w['peers']) for b in plan['branches'] for w in b['wallets']}
        self.assertEqual(len(nodes), 12)
        for who, peers in nodes.items():
            self.assertNotIn(who, peers)
            for peer in peers:
                self.assertIn(who, nodes[peer])
        self.assertEqual(plan, branches(state, count=4))

    def test_uneven_population_keeps_branch_sizes_within_one(self):
        state = snapshot(self.node.path)
        plan = branches(state, count=5)
        self.assertLessEqual(plan['branch_size_max']-plan['branch_size_min'], 1)
        self.assertTrue(plan['connected'])

    def test_export_is_exclusive_and_contains_no_wallet_secrets(self):
        out = Path(self.tmp.name)/'wallets.json'
        data = catalogue(snapshot(self.node.path))
        write_export(out, data, 1000000)
        saved = out.read_bytes()
        with self.assertRaises(FileExistsError):
            write_export(out, data, 1000000)
        self.assertEqual(out.read_bytes(), saved)
