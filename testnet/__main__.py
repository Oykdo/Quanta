import argparse
from datetime import datetime, timezone
import json
import getpass
from pathlib import Path
import secrets
import statistics
import sys
import threading
import time

from exchange.crypto import sign
from provenance.record import ROOT, create_proof
from testnet.client import Client, Wallet, RemoteError
from testnet.http import Server
from testnet.node import Node
from v2.storage import OutputBudget, BudgetExceeded


def run_testnet(folder, count, allocation, port=0, max_output_bytes=32_000_000, serve=False,
                stamp_author='jeremy zgonec', vault_password=None):
    # These are artificial identities and approvals, never real owner consents.
    wallets, reserve = [Wallet() for _ in range(count)], Wallet()
    node = Node.create(folder, reserve.account, [w.account for w in wallets], allocation, max_output_bytes)
    server = None
    worker = None
    storage = node.storage
    try:
        if vault_password is not None:
            from testnet.vault import save_vault
            save_vault(Path(folder)/'wallets.vault', node.ledger.ledger_id, reserve, wallets, vault_password, storage)
        server = Server(node, port)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        client = Client(server.url, node.ledger.ledger_id)

        def progress(stage, completed):
            storage.write_json('status.json', {'stage': stage, 'completed': completed, 'wallets': count,
                                               'url': server.url, 'ledger_id': node.ledger.ledger_id,
                                               'synthetic_only': True})
            print(f'{stage} {completed}/{count} url={server.url}', flush=True)

        progress('registration', 0)
        start = time.perf_counter()
        client.join(reserve, count*allocation, 0)
        for index, wallet in enumerate(wallets, 1):
            client.join(wallet, allocation, 2*allocation)
            if index % 100 == 0 or index == count:
                progress('registration', index)
        registration_seconds = time.perf_counter()-start
        progress('distribution', 0)
        timings = []
        for index, wallet in enumerate(wallets, 1):
            start = time.perf_counter_ns()
            client.transfer(reserve, wallet, allocation, node.primary_resource)
            timings.append((time.perf_counter_ns()-start)/1e6)
            if index % 100 == 0 or index == count:
                progress('distribution', index)
        initial = node.audit()
        balances = [initial['balances'][w.account] for w in wallets]
        if not initial['distribution_complete'] or set(balances) != {allocation} \
                or initial['reserve_balance'] != -count*allocation or initial['balance_sum'] != 0:
            raise ValueError('Primary distribution invariant failed')
        # Read ownership uses a fresh one-time random challenge, distinct from the
        # persistent nonce counter consumed by monetary operations.
        state = client.account_state(wallets[0])
        if state['nonce'] != 1 or state['balance'] != allocation:
            raise ValueError('Authenticated wallet state is inconsistent')
        proposal = client.template.transfer_authorization(wallets[0].account, wallets[1].account, 1,
                                                         'test_exchange', wallets[0].nonce, wallets[1].nonce)
        accepted = client.submit(proposal, wallets[:2])
        repeated = client.submit(proposal, wallets[:2])
        if repeated['status'] != 'already_committed' or repeated['receipt']['hash'] != accepted['receipt']['hash']:
            raise ValueError('Exact HTTP retry did not return the original receipt')
        stale = {**proposal, 'request_id': secrets.token_hex(16)}
        stale_refused = False
        try:
            client.submit(stale, wallets[:2])
        except RemoteError:
            stale_refused = True
        if not stale_refused:
            raise ValueError('Stale wallet nonce was accepted')
        final = node.audit()
        if final['events'] != initial['events']+1 or final['balance_sum'] != 0:
            raise ValueError('Retry or replay changed the ledger incorrectly')
        report = {'mode': 'local_single_coordinator_synthetic_testnet', 'url': server.url,
                  'ledger_id': node.ledger.ledger_id, 'wallets': count, 'reserve_accounts': 1,
                  'allocation_quanta_per_wallet': allocation, 'allocated_total_quanta': count*allocation,
                  'primary_balances_min': min(balances), 'primary_balances_max': max(balances),
                  'initial_reserve_balance': initial['reserve_balance'], 'initial_balance_sum': initial['balance_sum'],
                  'primary_allocation_count': initial['allocation_count'], 'initial_events': initial['events'],
                  'final_events': final['events'], 'final_head': final['head'],
                  'authenticated_state_read': True, 'exact_retry_idempotent': True, 'stale_nonce_refused': True,
                  'registration_seconds': registration_seconds, 'distribution_seconds': sum(timings)/1000,
                  'median_http_commit_ms': statistics.median(timings),
                  'energy_joules': None, 'private_keys': 'Ephemeral synthetic client keys in RAM; never sent to API or saved',
                  'personhood_scope': 'One allocation per listed synthetic key, not proof of unique humans',
                  'max_output_bytes': max_output_bytes, 'ledger_file': str(node.path)}
        if vault_password is not None:
            report['private_keys'] = 'Synthetic keys in encrypted local AES-GCM/Scrypt vault; no public key export service'
            report['wallet_vault'] = str(Path(folder)/'wallets.vault')
        storage.write_json('report.json', report)
        progress('ready', count)
        proof = create_proof(ROOT, stamp_author, Path(folder)/'provenance',
                             min(max_output_bytes, 10_000_000), model_paths=[], storage=storage)
        report['provenance_folder'] = proof['folder']
        report['current_output_bytes'] = storage.used_bytes()
        # Keep report.json stable once it has been fingerprinted in the proof.
        print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)
        if serve:
            print('TESTNET READY - Ctrl+C pour arreter. Les cles synthetiques restent en RAM pendant cette session.', flush=True)
            threading.Event().wait()
        return report
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if worker is not None:
            worker.join(timeout=5)
        node.close()


def resume_testnet(path, vault, password, port=0, serve=False):
    from testnet.vault import load_vault
    node, server, worker = Node(path), None, None
    try:
        reserve, wallets = load_vault(vault, password, node)
        server = Server(node, port)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        client = Client(server.url, node.ledger.ledger_id)
        q = node.plan['allocation_quanta']
        if reserve.account not in node.accounts:
            client.join(reserve, len(wallets)*q, 0)
        for wallet in wallets:
            if wallet.account not in node.accounts:
                client.join(wallet, q, 2*q)
        for wallet in wallets:
            if node.db.execute('SELECT 1 FROM allocations WHERE account=?', (wallet.account,)).fetchone() is None:
                client.transfer(reserve, wallet, q, node.primary_resource)
        audit = node.audit()
        result = {'status': 'resumed', 'url': server.url, 'ledger_id': node.ledger.ledger_id,
                  'wallets_restored': len(wallets), 'allocation_count': audit['allocation_count'],
                  'balance_sum': audit['balance_sum'], 'events': audit['events'], 'head': audit['head'],
                  'nonces_source': 'verified persistent ledger', 'synthetic_only': True}
        node.storage.write_json('resume_status.json', result)
        print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)
        if serve:
            print('TESTNET RESUMED - Ctrl+C pour arreter.', flush=True)
            threading.Event().wait()
        return result
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if worker is not None:
            worker.join(timeout=5)
        node.close()


def main():
    parser = argparse.ArgumentParser(description='Testnet local de quanta, reserve equilibree et wallets synthetiques signes.')
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    run.add_argument('--wallets', type=int, default=1000)
    run.add_argument('--allocation', type=int, default=1000, help='Integer quanta per wallet; 1000 quanta = 1 LOCAL')
    run.add_argument('--out', type=Path)
    run.add_argument('--port', type=int, default=0)
    run.add_argument('--max-output-bytes', type=int, default=32_000_000)
    run.add_argument('--serve', action='store_true', help='Keep the loopback API and synthetic client keys alive after the test')
    run.add_argument('--stamp-author', default='jeremy zgonec')
    run.add_argument('--persist-wallets', action='store_true', help='Ask locally for a passphrase and save an encrypted synthetic-key vault')
    resume = sub.add_parser('resume')
    resume.add_argument('--ledger', type=Path, required=True)
    resume.add_argument('--vault', type=Path, required=True)
    resume.add_argument('--port', type=int, default=0)
    resume.add_argument('--serve', action='store_true')
    sub.add_parser('legal', help='Display creator, AGPL notice and license location')
    ping = sub.add_parser('ping')
    ping.add_argument('--url', required=True)
    audit = sub.add_parser('audit')
    audit.add_argument('--ledger', type=Path, required=True)
    for command in ('wallets', 'trace', 'branches'):
        show = sub.add_parser(command)
        show.add_argument('--ledger', type=Path, required=True)
        show.add_argument('--out', type=Path, help='Optional new local JSON export; no private keys')
        if command == 'trace':
            show.add_argument('--account', required=True, help='Public address, wallet-000001 alias, or reserve')
            show.add_argument('--offset', type=int, default=0)
            show.add_argument('--limit', type=int, default=100)
        elif command == 'branches':
            show.add_argument('--count', type=int, default=10)
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        if args.command == 'run':
            if not 2 <= args.wallets <= 3000 or not 1 <= args.allocation <= 1_000_000 or not 0 <= args.port <= 65535:
                parser.error('Choose 2..3000 wallets, 1..1000000 quanta and a valid loopback port')
            folder = args.out or ROOT/'testnet/results'/datetime.now(timezone.utc).strftime('testnet_%Y%m%dT%H%M%SZ')
            password = None
            if args.persist_wallets:
                from testnet.vault import validate_password
                password = getpass.getpass('Passphrase du coffre synthetique (12 caracteres minimum) : ')
                if password != getpass.getpass('Confirmez la passphrase : '):
                    raise ValueError('Vault passphrases do not match')
                validate_password(password)
            run_testnet(folder, args.wallets, args.allocation, args.port, args.max_output_bytes, args.serve,
                        args.stamp_author, password)
        elif args.command == 'resume':
            resume_testnet(args.ledger, args.vault, getpass.getpass('Passphrase du coffre synthetique : '), args.port, args.serve)
        elif args.command == 'legal':
            print((ROOT/'NOTICE.md').read_text(encoding='utf-8'))
            print(f'Texte complet : {ROOT/"LICENSE"}')
        elif args.command == 'ping':
            print(json.dumps(Client(args.url).health, ensure_ascii=True, indent=2))
        elif args.command == 'audit':
            node = Node(args.ledger, writable=False)
            try:
                result = node.audit()
                result.pop('balances')
                print(json.dumps(result, ensure_ascii=True, indent=2))
            finally:
                node.close()
        else:
            from testnet.explorer import snapshot, catalogue, wallet_trace, branches, write_export
            state = snapshot(args.ledger)
            if args.command == 'wallets':
                result = catalogue(state)
            elif args.command == 'trace':
                result = wallet_trace(state, args.account, args.offset, args.limit)
            else:
                result = branches(state, args.count)
            if args.out:
                write_export(args.out, result, state['header']['policy']['max_output_bytes'])
                print(json.dumps({'export': str(args.out), 'ledger_id': state['header']['ledger_id'],
                                  'head': state['head'], 'private_key_exported': False}, indent=2))
            else:
                print(json.dumps(result, ensure_ascii=True, indent=2))
    except KeyboardInterrupt:
        print('Testnet arrete proprement.', flush=True)
    except EOFError:
        parser.error('A local owner passphrase is required; no wallet vault was created')
    except (ValueError, OSError, BudgetExceeded) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
