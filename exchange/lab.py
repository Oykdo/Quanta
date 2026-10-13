"""Low-resource local mutual credit: python -B -m exchange.lab --help."""
import argparse
import getpass
import json
import math
from pathlib import Path
import statistics
import sys
import time


def approve(payload, policy=None, charter=None):
    if charter is not None:
        from exchange.charter import print_charter
        print_charter(charter)
    if policy is not None:
        print('Politique de la cooperative :')
        print(json.dumps(policy, ensure_ascii=True, indent=2))
    print('Autorisation exacte a signer (1 LOCAL = 1000 quanta, echanges communautaires sans conversion fiduciaire) :')
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    if input('Tapez AUTORISER pour donner votre accord, ou toute autre reponse pour refuser : ').strip() != 'AUTORISER':
        raise ValueError('Owner declined: nothing was signed or committed')


def demo(cycles, out=None):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from exchange.crypto import account_id, canonical, public_hex
    from exchange.ledger import Ledger, owner_signature
    from v2.storage import OutputBudget
    if not 1 <= cycles <= 300:
        raise ValueError('Choose 1 to 300 demonstration cycles')
    ledger = Ledger.create()
    keys = [Ed25519PrivateKey.generate() for _ in range(3)]
    names = ('participant_a', 'participant_b', 'participant_c')
    ids = [account_id(public_hex(key)) for key in keys]
    for key in keys:
        payload = ledger.join_proposal(public_hex(key))
        ledger.commit(payload, owner_signature(key, payload))
    timings, authorization_bytes = [], 0
    stories = ((1, 0, 'repair'), (0, 2, 'produce'), (2, 1, 'tool_share'))
    for _ in range(cycles):
        for payer, payee, resource in stories:
            start = time.perf_counter_ns()
            payload = ledger.transfer_proposal(ids[payer], ids[payee], 1000, resource)
            signatures = {**owner_signature(keys[payer], payload), **owner_signature(keys[payee], payload)}
            authorization_bytes += len(canonical({'payload': payload, 'signatures': signatures}))
            ledger.commit(payload, signatures)
            timings.append((time.perf_counter_ns()-start)/1e6)
    audit = ledger.audit()
    result = {'mode': 'local_simulation', 'identities': 'Ephemeral synthetic owners, not real consent or payments',
              'transactions': len(timings), 'exchanged_quanta': len(timings)*1000,
              'balances_quanta': {name: audit['balances'][who] for name, who in zip(names, ids)},
              'balance_sum': audit['balance_sum'], 'total_debt': audit['total_debt'],
              'median_authorize_commit_ms': statistics.median(timings),
              'p95_authorize_commit_ms': sorted(timings)[math.ceil(.95*len(timings))-1],
              'canonical_authorization_bytes': authorization_bytes,
              'serialized_ledger_bytes': len(json.dumps(ledger.state, ensure_ascii=False, indent=2).encode('utf-8')),
              'model_inferences': 0, 'protocol_fee_quanta': 0, 'interest_quanta': 0,
              'charter': audit['charter'],
              'energy_joules': None, 'energy_scope': 'Not measured; timings are not energy estimates',
              'head': audit['head'], 'storage': 'RAM only', 'persisted_bytes': 0}
    if out is not None:
        out = Path(out).resolve()
        out.mkdir(parents=True, exist_ok=False)
        storage = OutputBudget(out, ledger.state['header']['policy']['max_output_bytes'])
        result['storage'] = str(out)
        storage.write_json('ledger.json', ledger.state)
        # The complete measured size includes both the ledger and this report.
        result['persisted_bytes'] = storage.used_bytes()
        for _ in range(3):
            encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
            result['persisted_bytes'] = storage.used_bytes() + len(encoded)
        storage.write_json('demo_report.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    charter = sub.add_parser('charter', help='Read the moral charter and its signed-admission fingerprint')
    charter.add_argument('--ledger', type=Path, help='Inspect the charter of a particular ledger')
    charter.add_argument('--json', action='store_true')
    show = sub.add_parser('demo')
    show.add_argument('--cycles', type=int, default=1)
    show.add_argument('--out', type=Path, help='Optional new demo directory; ephemeral keys are not saved')
    init = sub.add_parser('init')
    init.add_argument('--out', type=Path, required=True)
    init.add_argument('--max-debt', type=int, default=100000)
    init.add_argument('--max-credit', type=int, default=100000)
    init.add_argument('--max-total-debt', type=int, default=1000000)
    init.add_argument('--max-accounts', type=int, default=100)
    init.add_argument('--max-events', type=int, default=1000)
    init.add_argument('--max-output-bytes', type=int, default=10000000)
    keygen = sub.add_parser('keygen')
    keygen.add_argument('--out', type=Path, required=True)
    for command in ('join', 'propose', 'sign', 'commit', 'control', 'audit'):
        show = sub.add_parser(command)
        show.add_argument('--ledger', type=Path, required=True)
        show.add_argument('--require-head', help='A previously retained receipt hash that must still be in the journal')
        if command in ('join', 'sign', 'control'):
            show.add_argument('--key', type=Path, required=True)
        if command == 'join':
            show.add_argument('--debt-limit', type=int)
            show.add_argument('--credit-limit', type=int)
        elif command == 'propose':
            show.add_argument('--payer', required=True)
            show.add_argument('--payee', required=True)
            show.add_argument('--amount', type=int, required=True, help='Positive integer quanta; 1000 = 1 LOCAL')
            show.add_argument('--resource-id', required=True)
            show.add_argument('--out', type=Path, required=True)
        elif command == 'sign':
            show.add_argument('--proposal', type=Path, required=True)
            show.add_argument('--out', type=Path, required=True)
        elif command == 'commit':
            show.add_argument('--authorizations', type=Path, nargs=2, required=True)
        elif command == 'control':
            show.add_argument('--state', choices=('pause', 'resume'), required=True)
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if args.command == 'charter' and args.ledger is None:
        from exchange.charter import community_charter, charter_hash, print_charter
        document = community_charter()
        if args.json:
            print(json.dumps({'charter': document, 'hash': charter_hash(document)}, ensure_ascii=True, indent=2))
        else:
            print_charter(document)
        return
    try:
        from exchange.crypto import account_id, canonical, create_key_file, load_key_file, public_hex, sign
        from exchange.ledger import owner_signature
        from exchange.store import LedgerStore, read_json, write_request
        from v2.storage import BudgetExceeded
    except ModuleNotFoundError as error:
        if error.name and error.name.startswith('cryptography'):
            parser.error('Use a Python environment with cryptography 49 installed; see requirements-network.txt')
        raise
    try:
        if args.command == 'demo':
            result = demo(args.cycles, args.out)
        elif args.command == 'init':
            store = LedgerStore.create(args.out, max_debt=args.max_debt, max_credit=args.max_credit,
                                       max_total_debt=args.max_total_debt, max_accounts=args.max_accounts,
                                       max_events=args.max_events, max_output_bytes=args.max_output_bytes)
            ledger = store.load()
            result = {**ledger.audit(), 'ledger_file': str(store.path), 'policy': ledger.state['header']['policy']}
        elif args.command == 'keygen':
            password = getpass.getpass('Passphrase du proprietaire (12 caracteres minimum) : ')
            if password != getpass.getpass('Confirmez la passphrase : '):
                raise ValueError('Passphrases do not match')
            result = create_key_file(args.out, password)
        elif args.command == 'charter':
            from exchange.charter import charter_hash, print_charter
            ledger = LedgerStore(args.ledger).load()
            document = ledger.charter
            if document is None:
                result = {'protocol_version': 1, 'charter': None,
                          'status': 'Historical ledger: no signed moral-charter acceptance'}
            elif not args.json:
                print_charter(document)
                return
            else:
                result = {'charter': document, 'hash': charter_hash(document)}
        else:
            store = LedgerStore(args.ledger)
            ledger = store.load(args.require_head)
            if args.command == 'audit':
                result = ledger.audit(args.require_head)
            elif args.command == 'propose':
                payload = ledger.transfer_proposal(args.payer, args.payee, args.amount, args.resource_id)
                ledger.validate_proposal(payload)
                write_request(args.out, payload)
                result = {'status': 'unsigned_proposal', 'proposal': str(args.out), 'payload': payload}
            elif args.command == 'commit':
                envelopes = [read_json(path, 8192) for path in args.authorizations]
                if any(not isinstance(e, dict) or set(e) != {'payload', 'account', 'signature'} for e in envelopes):
                    raise ValueError('Two explicit owner authorizations are required')
                if canonical(envelopes[0]['payload']) != canonical(envelopes[1]['payload']):
                    raise ValueError('Owners authorized different proposals')
                payload = envelopes[0]['payload']
                if not isinstance(payload, dict) or payload.get('kind') != 'transfer' \
                        or envelopes[0]['account'] == envelopes[1]['account']:
                    raise ValueError('Both different owners must authorize the exchange')
                signatures = {e['account']: e['signature'] for e in envelopes}
                result = {'status': 'committed', 'receipt': store.commit(payload, signatures, required_head=args.require_head)}
            else:
                password = getpass.getpass('Passphrase du proprietaire : ')
                key = load_key_file(args.key, password)
                who = account_id(public_hex(key))
                if args.command == 'join':
                    payload = ledger.join_proposal(public_hex(key), args.debt_limit, args.credit_limit)
                    ledger.validate_proposal(payload)
                    approve(payload, ledger.state['header']['policy'], ledger.charter)
                    result = {'status': 'joined', 'account_id': who,
                              'receipt': store.commit(payload, owner_signature(key, payload), required_head=args.require_head)}
                elif args.command == 'control':
                    payload = ledger.control_proposal(who, args.state == 'resume')
                    ledger.validate_proposal(payload)
                    approve(payload)
                    result = {'status': args.state,
                              'receipt': store.commit(payload, owner_signature(key, payload), required_head=args.require_head)}
                else:
                    payload = read_json(args.proposal, 8192)
                    ledger.validate_proposal(payload)
                    if payload['kind'] != 'transfer' or who not in (payload['payer'], payload['payee']):
                        raise ValueError('This key does not belong to a participant in this proposal')
                    approve(payload)
                    write_request(args.out, {'payload': payload, 'account': who, 'signature': sign(key, payload)})
                    result = {'status': 'authorized', 'account_id': who, 'authorization': str(args.out)}
        print(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False))
    except EOFError:
        parser.error('Owner consent was not provided; no authorization was created')
    except (ValueError, TypeError, KeyError, OSError, BudgetExceeded) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
