import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from provenance.record import ROOT, create_proof, decode_record, verify_proof
from provenance.timestamp import openssl_path, run_openssl, verify_timestamp
from v2.storage import BudgetExceeded


class ProvenanceTests(unittest.TestCase):
    def project(self, folder):
        root = Path(folder)/'project'
        root.mkdir()
        (root/'lab.py').write_text('print("project")\n', encoding='utf-8')
        (root/'resultats/checkpoints').mkdir(parents=True)
        (root/'resultats/checkpoints/model.pt').write_bytes(b'model-weights'*100)
        (root/'resultats/donnees.json').write_text('{"corpus": [1, 2, 3]}', encoding='utf-8')
        (root/'private.pem').write_text('PRIVATE KEY MUST NOT BE ARCHIVED', encoding='utf-8')
        return root

    def test_named_utc_binary_archive_and_data_fingerprints(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'provenance') as tmp:
            root = self.project(tmp)
            out = Path(tmp)/'proof'
            result = create_proof(root, output=out)
            self.assertEqual(result['author_declared'], 'jeremy zgonec')
            self.assertTrue(result['created_utc_local_clock'].endswith('Z'))
            manifest = json.loads(decode_record((out/'creation.bin').read_bytes()))
            self.assertEqual(manifest['archive']['sha256'], hashlib.sha256((out/'creation.zip').read_bytes()).hexdigest())
            with zipfile.ZipFile(out/'creation.zip') as archive:
                self.assertEqual(set(archive.namelist()), {'lab.py', 'resultats/checkpoints/model.pt'})
            self.assertEqual(verify_proof(out, root)['current_project_files_checked'], 3)
            self.assertEqual(result['fingerprinted_only_files'], 1)
            original = (out/'creation.bin').read_bytes()
            with self.assertRaises(FileExistsError):
                create_proof(root, output=out)
            self.assertEqual((out/'creation.bin').read_bytes(), original)

    def test_altered_binary_manifest_archive_and_live_project_are_detected(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'provenance') as tmp:
            root = self.project(tmp)
            out = Path(tmp)/'proof'
            create_proof(root, output=out)
            for name in ('creation.bin', 'manifest.json', 'creation.zip', 'SHA256SUMS.txt'):
                path = out/name
                original = path.read_bytes()
                path.write_bytes(original[:-1]+bytes([original[-1] ^ 1]))
                with self.assertRaises(ValueError):
                    verify_proof(out)
                path.write_bytes(original)
            (root/'lab.py').write_text('print("modified")\n', encoding='utf-8')
            self.assertTrue(verify_proof(out)['verified'])  # The historical snapshot remains valid.
            with self.assertRaisesRegex(ValueError, 'differs from snapshot'):
                verify_proof(out, root)

    def test_budget_refuses_before_creating_an_incomplete_pack(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'provenance') as tmp:
            root = self.project(tmp)
            out = Path(tmp)/'proof'
            with self.assertRaises(BudgetExceeded):
                create_proof(root, output=out, max_output_bytes=10)
            self.assertFalse(out.exists())

    def test_timestamp_needs_independent_root_and_checks_both_nonce_and_record(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'provenance') as tmp:
            root = self.project(tmp)
            out = Path(tmp)/'proof'
            create_proof(root, output=out)
            (out/'freetsa_ca.pem').write_bytes(b'not a trusted root')
            with self.assertRaisesRegex(ValueError, 'pinned fingerprint'):
                verify_timestamp(out)
            ca = b'unit-test-root'
            (out/'freetsa_ca.pem').write_bytes(ca)
            (out/'timestamp.tsq').write_bytes(b'request')
            (out/'timestamp.tsr').write_bytes(b'reply')
            with patch('provenance.timestamp.CA_SHA256', hashlib.sha256(ca).hexdigest()), \
                    patch('provenance.timestamp.openssl_path', return_value='openssl'), \
                    patch('provenance.timestamp.run_openssl', side_effect=[b'OK', b'OK',
                          b'Time stamp: Oct 12 19:00:00.123 2026 GMT\n']) as verify:
                result = verify_timestamp(out)
                self.assertEqual(result['tsa_utc'], '2026-10-12T19:00:00.123000Z')
                self.assertIn('-queryfile', verify.call_args_list[0].args[1])
                self.assertIn('-data', verify.call_args_list[1].args[1])
                self.assertEqual(result['timestamp_status'], 'rfc3161_verified_freetsa')

    def test_openssl_generates_real_nonce_bearing_sha256_request(self):
        executable = openssl_path()
        request = run_openssl(executable, ['ts', '-query', '-digest', '00'*32, '-sha256', '-cert'])
        self.assertGreater(len(request), 50)
        self.assertEqual(request[0], 0x30)  # DER sequence.
        with tempfile.TemporaryDirectory(dir=ROOT/'provenance') as tmp:
            path = Path(tmp)/'timestamp.tsq'
            path.write_bytes(request)
            text = run_openssl(executable, ['ts', '-query', '-in', str(path), '-text']).decode('utf-8')
            self.assertIn('Hash Algorithm: sha256', text)
            self.assertIn('Nonce: 0x', text)
