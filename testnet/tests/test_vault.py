from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

from exchange.crypto import public_hex, sign
from provenance.record import ROOT
from testnet.__main__ import run_testnet, resume_testnet
from testnet.client import Wallet
from testnet.node import Node
from testnet.source import source_archive
from testnet.vault import save_vault, load_vault

PASSWORD = 'synthetic_test_passphrase'


class VaultTests(unittest.TestCase):
    def setup_node(self, folder):
        reserve, wallets = Wallet(), [Wallet() for _ in range(3)]
        node = Node.create(folder, reserve.account, [w.account for w in wallets], 100)
        return node, reserve, wallets

    def enroll(self, node, wallet, reserve=False):
        limits = (300, 0) if reserve else (100, 200)
        p = node.ledger.join_proposal(public_hex(wallet.key), *limits)
        node.commit(p, {wallet.account: sign(wallet.key, p)})

    def test_encrypted_vault_restores_keys_and_nonce_from_ledger(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'testnet') as tmp:
            node, reserve, wallets = self.setup_node(Path(tmp)/'network')
            try:
                path = node.path.parent/'wallets.vault'
                save_vault(path, node.ledger.ledger_id, reserve, wallets, PASSWORD, node.storage)
                for wallet in [reserve, *wallets]:
                    self.enroll(node, wallet, wallet is reserve)
                p = node.ledger.transfer_authorization(reserve.account, wallets[0].account, 100,
                                                       node.primary_resource, 0, 0)
                node.commit(p, {w.account: sign(w.key, p) for w in (reserve, wallets[0])})
                restored_reserve, restored = load_vault(path, PASSWORD, node)
                self.assertEqual(restored_reserve.nonce, 1)
                self.assertEqual(restored[0].nonce, 1)
                self.assertEqual(public_hex(restored[0].key), public_hex(wallets[0].key))
                self.assertNotIn(wallets[0].account.encode('ascii'), path.read_bytes())
                self.assertNotIn(PASSWORD.encode('ascii'), path.read_bytes())
            finally:
                node.close()

    def test_wrong_password_tampering_and_overwrite_are_refused(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'testnet') as tmp:
            node, reserve, wallets = self.setup_node(Path(tmp)/'network')
            try:
                path = node.path.parent/'wallets.vault'
                save_vault(path, node.ledger.ledger_id, reserve, wallets, PASSWORD, node.storage)
                original = path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'Wrong passphrase'):
                    load_vault(path, 'another_test_passphrase', node)
                with self.assertRaises(FileExistsError):
                    save_vault(path, node.ledger.ledger_id, reserve, wallets, PASSWORD, node.storage)
                self.assertEqual(path.read_bytes(), original)
                path.write_bytes(original[:-1]+bytes([original[-1] ^ 1]))
                with self.assertRaisesRegex(ValueError, 'altered wallet vault'):
                    load_vault(path, PASSWORD, node)
            finally:
                node.close()

    def test_vault_is_bound_to_its_ledger(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'testnet') as tmp:
            node, reserve, wallets = self.setup_node(Path(tmp)/'first')
            other = Node.create(Path(tmp)/'second', reserve.account, [w.account for w in wallets], 100)
            try:
                path = node.path.parent/'wallets.vault'
                save_vault(path, node.ledger.ledger_id, reserve, wallets, PASSWORD, node.storage)
                with self.assertRaisesRegex(ValueError, 'does not belong'):
                    load_vault(path, PASSWORD, other)
            finally:
                node.close()
                other.close()

    def test_complete_run_can_restart_without_redistribution(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'testnet') as tmp:
            out = Path(tmp)/'network'
            with redirect_stdout(io.StringIO()):
                first = run_testnet(out, 6, 100, vault_password=PASSWORD)
                resumed = resume_testnet(out/'ledger.sqlite3', out/'wallets.vault', PASSWORD)
            self.assertEqual(resumed['head'], first['final_head'])
            self.assertEqual(resumed['events'], first['final_events'])
            self.assertEqual(resumed['allocation_count'], 6)
            self.assertEqual(resumed['balance_sum'], 0)
            self.assertEqual(resumed['nonces_source'], 'verified persistent ledger')

    def test_incomplete_registration_can_recover_and_complete_allocations_once(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'testnet') as tmp:
            node, reserve, wallets = self.setup_node(Path(tmp)/'network')
            path = node.path
            vault = node.path.parent/'wallets.vault'
            save_vault(vault, node.ledger.ledger_id, reserve, wallets, PASSWORD, node.storage)
            self.enroll(node, reserve, True)
            self.enroll(node, wallets[0])
            node.close()
            with redirect_stdout(io.StringIO()):
                result = resume_testnet(path, vault, PASSWORD)
                again = resume_testnet(path, vault, PASSWORD)
            self.assertEqual(result['allocation_count'], 3)
            self.assertEqual(result['events'], 7)
            self.assertEqual(again['head'], result['head'])
            self.assertEqual(again['events'], result['events'])

    def test_public_source_archive_excludes_runtime_and_secret_files(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'testnet') as tmp:
            root = Path(tmp)
            (root/'testnet/results').mkdir(parents=True)
            (root/'testnet/__init__.py').write_text('"""source"""', encoding='utf-8')
            (root/'LICENSE').write_text('license', encoding='utf-8')
            (root/'testnet/results/wallets.vault').write_bytes(b'PRIVATE VAULT')
            (root/'testnet/private.pem').write_bytes(b'PRIVATE KEY')
            archive = source_archive(root)
            with zipfile.ZipFile(io.BytesIO(archive)) as zip_file:
                self.assertEqual(set(zip_file.namelist()), {'LICENSE', 'testnet/__init__.py'})


if __name__ == '__main__':
    unittest.main()
