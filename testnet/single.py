"""Small one-computer harness: two TLS identities, wallet batch and economic scenarios."""
import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import getpass
import io
import json
from pathlib import Path
import secrets
import sys
import threading

from cryptography.hazmat.primitives import serialization
from economy.data import example, write
from economy.__main__ import run as economic_run
from economy.engine import SCENARIOS
from provenance.record import ROOT
from testnet.__main__ import run_testnet
from testnet.client import Wallet, Client
from testnet.http import Server
from testnet.node import Node
from testnet.tls import make_ca, make_csr, issue_client, server_context
from v2.storage import OutputBudget, BudgetExceeded


def run(folder, wallets=100, replications=5, max_run_mib=128, interactive=False):
    if type(wallets) is not int or not 2 <= wallets <= 1000 or not 1 <= replications <= 20:
        raise ValueError('Choose 2..1000 batch wallets and 1..20 economic replications')
    if not 16 <= max_run_mib <= 512:
        raise ValueError('Choose a total run quota of 16..512 MiB, below the requested disk ceiling')
    total_quota = max_run_mib*1024*1024
    component_quota = total_quota//4
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    storage = OutputBudget(folder, total_quota)
    # Automatic credentials are random, simulation-only and never printed.
    password = secrets.token_urlsafe(32)
    if interactive:
        password = getpass.getpass('Passphrase locale des clients synthetiques (12 caracteres minimum) : ')
        if len(password) < 12 or password != getpass.getpass('Confirmez la passphrase : '):
            raise ValueError('A confirmed local passphrase is required')
    a, b, reserve = Wallet(), Wallet(), Wallet()
    node = Node.create(folder/'transport', reserve.account, [a.account, b.account], 1000, component_quota)
    server = None
    worker = None
    try:
        pki = node.path.parent/'pki'
        make_ca(pki, password, ['127.0.0.1'])
        identities = {}
        for name, wallet in (('client_a', a), ('client_b', b), ('reserve', reserve)):
            key_path, cert_path = node.path.parent/(name+'.key.pem'), node.path.parent/(name+'.crt')
            payload = wallet.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.BestAvailableEncryption(password.encode('utf-8')))
            node.storage._check(len(payload))
            with key_path.open('xb') as file:
                file.write(payload)
            _, certificate = issue_client(pki, make_csr(wallet.key), password, {a.account, b.account, reserve.account})
            node.storage._check(len(certificate))
            with cert_path.open('xb') as file:
                file.write(certificate)
            identities[name] = {'account': wallet.account, 'certificate': str(cert_path), 'key': str(key_path)}
        server = Server(node, tls_context=server_context(pki/'ca.crt', pki/'server.crt', pki/'server.key.pem', password))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def client(name):
            identity = identities[name]
            return Client(server.url, node.ledger.ledger_id, pki/'ca.crt', identity['certificate'], identity['key'], password)

        ca, cb, cr = client('client_a'), client('client_b'), client('reserve')
        cr.join(reserve, 2000, 0)
        ca.join(a, 1000, 2000)
        cb.join(b, 1000, 2000)
        cr.transfer(reserve, a, 1000, node.primary_resource)
        cr.transfer(reserve, b, 1000, node.primary_resource)
        ca.transfer(a, b, 100, 'single_machine_exchange')
        first_state, second_state = ca.account_state(a), cb.account_state(b)
        if (first_state['balance'], second_state['balance']) != (900, 1100):
            raise ValueError('Two-client TLS exchange invariant failed')
        if node.audit()['balance_sum'] != 0:
            raise ValueError('Transport ledger is not balanced')
        print('Two TLS clients verified: A=900, B=1100, reserve=-2000; sum=0.', flush=True)

        write(folder/'economic_inputs', example(30, 30), max_bytes=component_quota)
        economics = economic_run(folder/'economic_inputs', folder/'economic_reports', 42, replications,
                                 SCENARIOS, max_bytes=component_quota)
        print('Economic scenarios verified.', flush=True)
        with redirect_stdout(io.StringIO()):
            batch = run_testnet(folder/'wallet_batch', wallets, 1000, max_output_bytes=component_quota)
        storage._check(8192)
        report = {'mode': 'one_computer_synthetic_harness', 'platform': sys.platform, 'tls_url': server.url,
                  'ledger_id': node.ledger.ledger_id, 'transport_balances_quanta': {'client_a': 900, 'client_b': 1100, 'reserve': -2000},
                  'clients': identities, 'ca_certificate': str(pki/'ca.crt'),
                  'client_runtime': 'Distinct client keys and real loopback TLS connections in one Python process',
                  'credentials': 'Operator-chosen local passphrase' if interactive else 'Ephemeral random test passphrase, not retained',
                  'wallet_batch_count': wallets, 'wallet_batch_allocation_once': batch['primary_allocation_count'] == wallets,
                  'wallet_batch_stale_nonce_refused': batch['stale_nonce_refused'],
                  'economic_scenarios': [{'name': s['scenario'], 'fulfillment_ratio': s['metrics']['mean_need_fulfillment_ratio']['mean'],
                                         'settled_quanta': s['metrics']['settled_value_quanta']['mean'],
                                         'unpaid_quanta': s['metrics']['delivered_unpaid_value_quanta']['mean']}
                                        for s in economics['scenarios']],
                  'max_run_bytes': total_quota, 'actual_bytes_before_report': storage.used_bytes(),
                  'synthetic_only': True, 'live_existing_ledger_modified': False, 'energy_joules': None}
        storage.write_json('single_report.json', report)
        report['actual_output_bytes'] = storage.used_bytes()
        print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)
        if interactive:
            print('Loopback TLS server remains available. Use the client paths from single_report.json; Ctrl+C stops it.', flush=True)
            threading.Event().wait()
        return report
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if worker is not None:
            worker.join(timeout=5)
        node.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--wallets', type=int, default=100)
    parser.add_argument('--replications', type=int, default=5)
    parser.add_argument('--max-run-mib', type=int, default=128)
    parser.add_argument('--interactive', action='store_true')
    args = parser.parse_args()
    folder = args.out or ROOT/'testnet/results'/datetime.now(timezone.utc).strftime('single_%Y%m%dT%H%M%S%fZ')
    try:
        run(folder, args.wallets, args.replications, args.max_run_mib, args.interactive)
    except KeyboardInterrupt:
        print('Single-machine test stopped cleanly.')
    except (ValueError, OSError, EOFError, BudgetExceeded) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
