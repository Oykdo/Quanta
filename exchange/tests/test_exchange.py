import copy
from contextlib import redirect_stderr, redirect_stdout
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exchange.crypto import account_id, create_key_file, load_key_file, public_hex
from exchange.ledger import Ledger, digest, owner_signature
from exchange.store import LedgerStore
from v2.storage import BudgetExceeded, OutputBudget

ROOT = Path(__file__).resolve().parents[2]
TMP_PARENT = ROOT/'exchange'


def enroll(ledger, key, now=10, **limits):
    payload = ledger.join_proposal(public_hex(key), now=now, **limits)
    ledger.commit(payload, owner_signature(key, payload), now)
    return account_id(public_hex(key))


class MutualCreditTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger.create(now=10, max_debt=5000, max_credit=5000, max_total_debt=8000)
        self.keys = [Ed25519PrivateKey.generate() for _ in range(3)]
        self.ids = [enroll(self.ledger, key) for key in self.keys]

    def proposal(self, amount=1000, payer=0, payee=1, **kwargs):
        return self.ledger.transfer_proposal(self.ids[payer], self.ids[payee], amount, 'service', now=20, **kwargs)

    def signatures(self, payload, payer=0, payee=1):
        return {**owner_signature(self.keys[payer], payload), **owner_signature(self.keys[payee], payload)}

    def assert_refused_unchanged(self, payload, signatures, now=20):
        before = copy.deepcopy(self.ledger.state)
        with self.assertRaises(ValueError):
            self.ledger.commit(payload, signatures, now)
        self.assertEqual(self.ledger.state, before)

    def test_credit_has_equal_debt_and_can_settle_without_initial_cash(self):
        payload = self.proposal(1500)
        self.ledger.commit(payload, self.signatures(payload), 20)
        report = self.ledger.audit()
        self.assertEqual(report['balances'][self.ids[0]], -1500)
        self.assertEqual(report['balances'][self.ids[1]], 1500)
        self.assertEqual(report['balance_sum'], 0)
        reverse = self.proposal(1500, payer=1, payee=0)
        self.ledger.commit(reverse, self.signatures(reverse, 1, 0), 20)
        self.assertEqual(self.ledger.audit()['total_debt'], 0)

    def test_missing_wrong_and_modified_owner_authorizations_fail_atomically(self):
        payload = self.proposal()
        self.assert_refused_unchanged(payload, owner_signature(self.keys[0], payload))
        wrong = {**owner_signature(self.keys[0], payload), **owner_signature(self.keys[2], payload)}
        self.assert_refused_unchanged(payload, wrong)
        signatures = self.signatures(payload)
        for field, value in (('amount', 1001), ('resource_id', 'other'), ('payee', self.ids[2])):
            changed = {**payload, field: value}
            self.assert_refused_unchanged(changed, signatures)

    def test_replay_stale_nonce_and_cross_cooperative_exchange_fail(self):
        accepted = self.proposal()
        stale = self.proposal()
        signatures = self.signatures(accepted)
        self.ledger.commit(accepted, signatures, 20)
        self.assert_refused_unchanged(accepted, signatures)
        self.assert_refused_unchanged(stale, self.signatures(stale))
        foreign = Ledger.create(now=10)
        for key in self.keys:
            enroll(foreign, key)
        before = copy.deepcopy(foreign.state)
        with self.assertRaisesRegex(ValueError, 'another cooperative'):
            foreign.commit(accepted, signatures, 20)
        self.assertEqual(foreign.state, before)

    def test_expiration_future_time_and_malformed_amounts_fail(self):
        payload = self.proposal(ttl=5)
        self.assert_refused_unchanged(payload, self.signatures(payload), now=25)
        self.assert_refused_unchanged(payload, self.signatures(payload), now=19)
        for amount in (0, -1, True, 1.5, '1000', 10**13):
            payload = self.proposal(amount)
            self.assert_refused_unchanged(payload, self.signatures(payload))

    def test_personal_and_aggregate_limits_bound_debt(self):
        payload = self.proposal(5001)
        self.assert_refused_unchanged(payload, self.signatures(payload))
        ledger = Ledger.create(now=10, max_debt=5000, max_credit=10000, max_total_debt=8000)
        for key in self.keys:
            enroll(ledger, key)
        first = ledger.transfer_proposal(self.ids[0], self.ids[1], 5000, 'service', now=20)
        ledger.commit(first, self.signatures(first), 20)
        # A second debtor would create 9000 of debt, without exceeding the recipient's cap.
        second = ledger.transfer_proposal(self.ids[2], self.ids[1], 4000, 'service', now=20)
        before = copy.deepcopy(ledger.state)
        with self.assertRaisesRegex(ValueError, 'total debt limit'):
            ledger.commit(second, self.signatures(second, 2, 1), 20)
        self.assertEqual(ledger.state, before)
        self.assertEqual(ledger.audit()['total_debt'], 5000)

    def test_pause_revokes_previously_signed_but_uncommitted_requests(self):
        pending = self.proposal()
        signed = self.signatures(pending)
        control = self.ledger.control_proposal(self.ids[0], False, now=20)
        self.ledger.commit(control, owner_signature(self.keys[0], control), 20)
        self.assert_refused_unchanged(pending, signed)
        resume = self.ledger.control_proposal(self.ids[0], True, now=20)
        self.ledger.commit(resume, owner_signature(self.keys[0], resume), 20)
        self.assert_refused_unchanged(pending, signed)  # The old nonce remains invalid.
        fresh = self.proposal()
        self.ledger.commit(fresh, self.signatures(fresh), 20)

    def test_audit_detects_tampering_even_after_hash_recalculation_and_pinned_rollback(self):
        before = copy.deepcopy(self.ledger.state)
        payload = self.proposal(1)
        receipt = self.ledger.commit(payload, self.signatures(payload), 20)
        changed = copy.deepcopy(self.ledger.state)
        changed['accounts'][self.ids[1]]['balance'] = True
        with self.assertRaisesRegex(ValueError, 'Cached balances'):
            Ledger(changed)
        changed = copy.deepcopy(self.ledger.state)
        event = changed['events'][-1]
        event['payload']['amount'] = 2
        event['hash'] = digest({k: v for k, v in event.items() if k != 'hash'})
        changed['head'] = event['hash']
        with self.assertRaisesRegex(ValueError, 'Invalid owner signature'):
            Ledger(changed)
        earlier = Ledger(before)
        with self.assertRaisesRegex(ValueError, 'possible rollback'):
            earlier.audit(required_head=receipt['hash'])
        self.ledger.audit(required_head=receipt['hash'])

    def test_random_exchanges_match_independent_integer_balance_accounting(self):
        rng = random.Random(42)
        expected = {who: 0 for who in self.ids}
        for _ in range(100):
            payer, payee = rng.sample(range(3), 2)
            amount = rng.randint(1, 20)
            payload = self.proposal(amount, payer, payee)
            self.ledger.commit(payload, self.signatures(payload, payer, payee), 20)
            expected[self.ids[payer]] -= amount
            expected[self.ids[payee]] += amount
        self.assertEqual(self.ledger.audit()['balances'], expected)
        self.assertEqual(sum(expected.values()), 0)

    def test_capacity_and_owner_chosen_limits_are_not_silently_enlarged(self):
        ledger = Ledger.create(now=10, max_accounts=2, max_events=3)
        first = enroll(ledger, self.keys[0], debt_limit=0)
        second = enroll(ledger, self.keys[1])
        third = ledger.join_proposal(public_hex(self.keys[2]), now=20)
        with self.assertRaisesRegex(ValueError, 'capacity'):
            ledger.commit(third, owner_signature(self.keys[2], third), 20)
        payload = ledger.transfer_proposal(first, second, 1, 'service', now=20)
        with self.assertRaisesRegex(ValueError, 'balance limit'):
            ledger.commit(payload, self.signatures(payload), 20)
        control = ledger.control_proposal(first, False, now=20)
        ledger.commit(control, owner_signature(self.keys[0], control), 20)
        resume = ledger.control_proposal(first, True, now=20)
        with self.assertRaisesRegex(ValueError, 'event limit'):
            ledger.commit(resume, owner_signature(self.keys[0], resume), 20)


class PersistenceAndCliTests(unittest.TestCase):
    def test_encrypted_owner_key_refuses_wrong_password_and_overwrite(self):
        with tempfile.TemporaryDirectory(dir=TMP_PARENT) as tmp:
            path = Path(tmp)/'owner.pem'
            identity = create_key_file(path, 'example_test_password')
            original = path.read_bytes()
            self.assertIn(b'ENCRYPTED PRIVATE KEY', original)
            self.assertEqual(account_id(public_hex(load_key_file(path, 'example_test_password'))), identity['account_id'])
            with self.assertRaises(ValueError):
                load_key_file(path, 'incorrect_password')
            with self.assertRaises(FileExistsError):
                create_key_file(path, 'another_test_password')
            self.assertEqual(path.read_bytes(), original)

    def setup_store(self, tmp, budget=20000):
        store = LedgerStore.create(Path(tmp)/'group', max_output_bytes=budget, now=10)
        keys = [Ed25519PrivateKey.generate() for _ in range(3)]
        for key in keys:
            payload = store.load().join_proposal(public_hex(key), now=10)
            store.commit(payload, owner_signature(key, payload), 10)
        return store, keys, [account_id(public_hex(key)) for key in keys]

    def test_budget_failure_preserves_ledger_and_cleans_lock(self):
        with tempfile.TemporaryDirectory(dir=TMP_PARENT) as tmp:
            store, keys, ids = self.setup_store(tmp)
            original = store.path.read_bytes()
            budget = OutputBudget(store.path.parent, 20000)
            budget.write_bytes('padding.bin', b'x'*(budget.max_bytes-budget.used_bytes()-1))
            payload = store.load().transfer_proposal(ids[0], ids[1], 1, 'service', now=20)
            signatures = {**owner_signature(keys[0], payload), **owner_signature(keys[1], payload)}
            with self.assertRaises(BudgetExceeded):
                store.commit(payload, signatures, 20)
            self.assertEqual(store.path.read_bytes(), original)
            self.assertFalse(store.path.with_name('ledger.json.lock').exists())
            self.assertLessEqual(budget.used_bytes(), 20000)

    def test_concurrent_writers_cannot_double_spend_one_authorization_nonce(self):
        with tempfile.TemporaryDirectory(dir=TMP_PARENT) as tmp:
            store, keys, ids = self.setup_store(tmp, budget=1000000)
            snapshot = store.load()
            proposals = [snapshot.transfer_proposal(ids[0], ids[n], 1000, 'service', now=20) for n in (1, 2)]
            signatures = [{**owner_signature(keys[0], p), **owner_signature(keys[n], p)}
                          for n, p in zip((1, 2), proposals)]
            barrier = threading.Barrier(2)

            def submit(index):
                barrier.wait()
                try:
                    store.commit(proposals[index], signatures[index], 20)
                    return True
                except ValueError:
                    return False

            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(submit, (0, 1)))
            self.assertEqual(sum(outcomes), 1)
            report = store.load().audit()
            self.assertEqual(report['balances'][ids[0]], -1000)
            self.assertEqual(report['balance_sum'], 0)

    def test_cli_owner_refusal_then_bilateral_signatures_and_commit(self):
        from exchange import lab
        with tempfile.TemporaryDirectory(dir=TMP_PARENT) as tmp:
            tmp = Path(tmp)
            store = LedgerStore.create(tmp/'group')
            paths, ids = [], []
            for name in ('a', 'b'):
                path = tmp/f'{name}.pem'
                identity = create_key_file(path, 'example_test_password')
                key = load_key_file(path, 'example_test_password')
                payload = store.load().join_proposal(public_hex(key))
                store.commit(payload, owner_signature(key, payload))
                paths.append(path)
                ids.append(identity['account_id'])
            proposal = tmp/'proposal.json'

            def run(args, answer='AUTORISER'):
                stdout = io.StringIO()
                with patch('sys.argv', ['exchange.lab', *args]), patch('getpass.getpass', return_value='example_test_password'), \
                        patch('builtins.input', return_value=answer), redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    lab.main()
                return stdout.getvalue()

            common = ['--ledger', str(store.path)]
            run(['propose', *common, '--payer', ids[0], '--payee', ids[1], '--amount', '1500',
                 '--resource-id', 'service', '--out', str(proposal)])
            before = store.path.read_bytes()
            authorizations = [tmp/'a.json', tmp/'b.json']
            with self.assertRaises(SystemExit) as error:
                run(['sign', *common, '--key', str(paths[0]), '--proposal', str(proposal),
                     '--out', str(authorizations[0])], answer='REFUSER')
            self.assertEqual(error.exception.code, 2)
            self.assertFalse(authorizations[0].exists())
            self.assertEqual(store.path.read_bytes(), before)
            for key, authorization in zip(paths, authorizations):
                run(['sign', *common, '--key', str(key), '--proposal', str(proposal), '--out', str(authorization)])
            output = json.loads(run(['commit', *common, '--authorizations', *map(str, authorizations)]))
            self.assertEqual(output['status'], 'committed')
            report = json.loads(run(['audit', *common, '--require-head', output['receipt']['hash']]))
            self.assertEqual(report['balances'][ids[0]], -1500)
            self.assertEqual(report['balances'][ids[1]], 1500)

    def test_demo_is_reloadable_bounded_and_does_not_import_torch(self):
        with tempfile.TemporaryDirectory(dir=TMP_PARENT) as tmp:
            out = Path(tmp)/'demo'
            result = subprocess.run([sys.executable, '-B', '-m', 'exchange.lab', 'demo', '--cycles', '3',
                                     '--out', str(out)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary['transactions'], 9)
            self.assertEqual(summary['balance_sum'], 0)
            self.assertEqual(summary['persisted_bytes'], OutputBudget(out, 10000000).used_bytes())
            self.assertIsNone(summary['energy_joules'])
            LedgerStore(out/'ledger.json').load().audit()
            probe = subprocess.run([sys.executable, '-B', '-c',
                "import sys; from exchange.lab import demo; demo(1); print('torch' in sys.modules)"],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertEqual(probe.stdout.strip(), 'False')

    def test_malformed_consent_files_fail_cleanly_without_touching_ledger(self):
        from exchange import lab
        with tempfile.TemporaryDirectory(dir=TMP_PARENT) as tmp:
            store, keys, ids = self.setup_store(tmp)
            before = store.path.read_bytes()
            files = [Path(tmp)/f'bad_{index}.json' for index in (0, 1)]
            for path, who in zip(files, ids):
                path.write_text(json.dumps({'payload': [], 'account': who, 'signature': '00'*64}), encoding='utf-8')
            with patch('sys.argv', ['exchange.lab', 'commit', '--ledger', str(store.path),
                                   '--authorizations', *map(str, files)]), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    lab.main()
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(store.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
