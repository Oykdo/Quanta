from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from provenance.record import ROOT
from testnet.single import run
from v2.storage import OutputBudget


class SingleMachineTests(unittest.TestCase):
    def test_transport_economics_and_wallet_batch_fit_one_small_run(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'testnet') as tmp:
            folder = Path(tmp)/'single'
            with redirect_stdout(io.StringIO()):
                result = run(folder, wallets=4, replications=1, max_run_mib=16)
            self.assertEqual(result['transport_balances_quanta'], {'client_a': 900, 'client_b': 1100, 'reserve': -2000})
            self.assertTrue(result['wallet_batch_allocation_once'])
            self.assertTrue(result['wallet_batch_stale_nonce_refused'])
            self.assertEqual(len(result['economic_scenarios']), 7)
            self.assertLessEqual(OutputBudget(folder, 16*1024*1024).used_bytes(), 16*1024*1024)
            stored = json.loads((folder/'single_report.json').read_text(encoding='utf-8'))
            self.assertTrue(stored['synthetic_only'])
            self.assertFalse((folder/'transport/ledger.sqlite3.lock').exists())

    def test_oversized_run_quota_is_refused_before_file_creation(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'testnet') as tmp:
            out = Path(tmp)/'single'
            with self.assertRaises(ValueError):
                run(out, max_run_mib=1024)
            self.assertFalse(out.exists())
