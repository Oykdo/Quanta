import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exchange.charter import charter_hash, community_charter
from exchange.crypto import account_id, create_key_file, public_hex
from exchange.ledger import Ledger, digest, owner_signature
from exchange.store import LedgerStore

ROOT = Path(__file__).resolve().parents[2]


class CharterTests(unittest.TestCase):
    def test_join_authorizes_exact_charter_and_missing_or_wrong_acceptance_fails(self):
        ledger = Ledger.create(now=10)
        key = Ed25519PrivateKey.generate()
        proposal = ledger.join_proposal(public_hex(key), now=10)
        self.assertEqual(proposal['version'], 2)
        self.assertEqual(proposal['charter_hash'], charter_hash(ledger.charter))
        self.assertEqual(charter_hash(ledger.charter), digest(ledger.charter))
        before = copy.deepcopy(ledger.state)
        missing = {k: v for k, v in proposal.items() if k != 'charter_hash'}
        with self.assertRaisesRegex(ValueError, 'Malformed authorization'):
            ledger.commit(missing, owner_signature(key, missing), 10)
        wrong = {**proposal, 'charter_hash': '0'*64}
        with self.assertRaisesRegex(ValueError, 'community charter'):
            ledger.commit(wrong, owner_signature(key, wrong), 10)
        self.assertEqual(ledger.state, before)
        ledger.commit(proposal, owner_signature(key, proposal), 10)
        report = ledger.audit()
        self.assertEqual(report['protocol_version'], 2)
        self.assertFalse(report['charter']['fiat_conversion_allowed'])

    def test_charter_cannot_be_changed_or_removed_from_signed_membership(self):
        ledger = Ledger.create(now=10)
        key = Ed25519PrivateKey.generate()
        proposal = ledger.join_proposal(public_hex(key), now=10)
        ledger.commit(proposal, owner_signature(key, proposal), 10)
        altered = copy.deepcopy(ledger.state)
        altered['header']['charter']['protocol_commitments']['fiat_conversion_allowed'] = True
        with self.assertRaisesRegex(ValueError, 'altered community charter'):
            Ledger(altered)
        # Attempt to downgrade to historical V1 and repair every hash: the owner's
        # signature still proves they authorized V2 and its charter, not V1.
        downgraded = copy.deepcopy(ledger.state)
        downgraded['header']['version'] = 1
        del downgraded['header']['charter']
        event = downgraded['events'][0]
        event['payload']['version'] = 1
        del event['payload']['charter_hash']
        event['previous_hash'] = digest(downgraded['header'])
        event['hash'] = digest({k: v for k, v in event.items() if k != 'hash'})
        downgraded['head'] = event['hash']
        with self.assertRaisesRegex(ValueError, 'Invalid owner signature'):
            Ledger(downgraded)

    def test_returned_charter_is_a_copy_and_fiat_fields_are_rejected(self):
        ledger = Ledger.create(now=10)
        expected = charter_hash(ledger.charter)
        returned = ledger.charter
        returned['motto'] = 'changed'
        self.assertEqual(charter_hash(ledger.charter), expected)
        keys = [Ed25519PrivateKey.generate() for _ in range(2)]
        ids = []
        for key in keys:
            proposal = ledger.join_proposal(public_hex(key), now=10)
            ledger.commit(proposal, owner_signature(key, proposal), 10)
            ids.append(account_id(public_hex(key)))
        proposal = ledger.transfer_proposal(ids[0], ids[1], 1, 'repair', now=20)
        before = copy.deepcopy(ledger.state)
        for field, value in (('fiat_currency', 'EUR'), ('exchange_rate', 1), ('bank_account', 'external')):
            invalid = {**proposal, field: value}
            signatures = {**owner_signature(keys[0], invalid), **owner_signature(keys[1], invalid)}
            with self.assertRaisesRegex(ValueError, 'Malformed authorization'):
                ledger.commit(invalid, signatures, 20)
        self.assertEqual(ledger.state, before)

    def test_historical_ledger_stays_valid_without_inventing_charter_consent(self):
        path = Path(__file__).with_name('fixtures')/'legacy_v1.json'
        original = path.read_bytes()
        ledger = LedgerStore(path).load()
        self.assertEqual(ledger.audit()['protocol_version'], 1)
        self.assertIsNone(ledger.charter)
        self.assertIsNone(ledger.audit()['charter'])
        key = Ed25519PrivateKey.generate()
        now = ledger.state['events'][-1]['committed_at']+1
        proposal = ledger.join_proposal(public_hex(key), now=now)
        self.assertEqual(proposal['version'], 1)
        self.assertNotIn('charter_hash', proposal)
        ledger.commit(proposal, owner_signature(key, proposal), now)
        ledger.audit()
        self.assertEqual(path.read_bytes(), original)

    def test_cli_displays_charter_before_owner_acceptance_and_refusal_is_atomic(self):
        from exchange import lab
        with tempfile.TemporaryDirectory(dir=ROOT/'exchange') as tmp:
            tmp = Path(tmp)
            store = LedgerStore.create(tmp/'group')
            key_path = tmp/'owner.pem'
            create_key_file(key_path, 'example_test_password')
            before = store.path.read_bytes()

            def join(answer):
                output = io.StringIO()
                with patch('sys.argv', ['exchange.lab', 'join', '--ledger', str(store.path), '--key', str(key_path)]), \
                        patch('getpass.getpass', return_value='example_test_password'), \
                        patch('builtins.input', return_value=answer), redirect_stdout(output), redirect_stderr(io.StringIO()):
                    lab.main()
                return output.getvalue()

            with self.assertRaises(SystemExit) as error:
                join('REFUSER')
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(store.path.read_bytes(), before)
            output = join('AUTORISER')
            self.assertIn(community_charter()['motto'], output)
            self.assertIn('conversion fiduciaire', output)
            signed = store.load().state['events'][-1]['payload']
            self.assertEqual(signed['charter_hash'], charter_hash(store.load().charter))

    def test_charter_command_needs_no_neural_or_cryptographic_runtime(self):
        script = ("import sys; from exchange.lab import main; "
                  "sys.argv = ['exchange.lab', 'charter', '--json']; main(); "
                  "assert 'torch' not in sys.modules; assert 'cryptography' not in sys.modules")
        result = subprocess.run([sys.executable, '-B', '-c', script], cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout)
        self.assertEqual(document['hash'], charter_hash(document['charter']))
        self.assertFalse(document['charter']['protocol_commitments']['fiat_conversion_allowed'])
