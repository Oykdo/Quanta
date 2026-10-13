"""Owner-side consent, wallet state and two-party exchange files over mutual TLS."""
import argparse
import getpass
import json
from pathlib import Path

from exchange.crypto import account_id, canonical, load_key_file, public_hex, sign
from exchange.lab import approve
from exchange.ledger import TRANSFER, integer, clock, RESOURCE
from exchange.store import read_json, write_request
from testnet.client import Client, Wallet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--ledger-id', required=True)
    parser.add_argument('--ca', type=Path, required=True)
    parser.add_argument('--certificate', type=Path, required=True)
    parser.add_argument('--key', type=Path, required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('state')
    join = sub.add_parser('join')
    join.add_argument('--debt-limit', type=int, required=True)
    join.add_argument('--credit-limit', type=int, required=True)
    proposal = sub.add_parser('propose')
    proposal.add_argument('--to', required=True)
    proposal.add_argument('--payee-nonce', type=int, required=True)
    proposal.add_argument('--amount', type=int, required=True)
    proposal.add_argument('--resource-id', required=True)
    proposal.add_argument('--out', type=Path, required=True)
    signing = sub.add_parser('sign')
    signing.add_argument('--proposal', type=Path, required=True)
    signing.add_argument('--out', type=Path, required=True)
    commit = sub.add_parser('commit')
    commit.add_argument('--authorizations', type=Path, nargs=2, required=True)
    args = parser.parse_args()
    try:
        secret = getpass.getpass('Passphrase locale du wallet : ')
        wallet = Wallet(load_key_file(args.key, secret))
        client = Client(args.url, args.ledger_id, args.ca, args.certificate, args.key, secret)
        if args.command == 'state':
            result = client.account_state(wallet)
        elif args.command == 'join':
            p = client.template.join_proposal(public_hex(wallet.key), args.debt_limit, args.credit_limit)
            approve(p, client.health['header']['policy'], client.health['header']['charter'])
            result = client.submit(p, [wallet])
        elif args.command == 'propose':
            client.account_state(wallet)
            p = client.template.transfer_authorization(wallet.account, args.to, args.amount, args.resource_id,
                                                       wallet.nonce, args.payee_nonce)
            integer(p['amount'], 1)
            integer(p['payee_nonce'])
            write_request(args.out, p)
            result = {'status': 'unsigned_proposal', 'file': str(args.out), 'payload': p}
        elif args.command == 'sign':
            p = read_json(args.proposal, 8192)
            if not isinstance(p, dict) or set(p) != TRANSFER or p['ledger_id'] != args.ledger_id \
                    or p['version'] != client.health['header']['version'] or p['kind'] != 'transfer' \
                    or wallet.account not in (p['payer'], p['payee']):
                raise ValueError('An exact proposal for this wallet and ledger is required')
            integer(p['amount'], 1)
            integer(p['payer_nonce'])
            integer(p['payee_nonce'])
            if not RESOURCE.fullmatch(p['resource_id']) or not p['issued_at'] <= clock(None) < p['expires_at']:
                raise ValueError('Invalid resource or expired proposal')
            state = client.account_state(wallet)
            nonce = p['payer_nonce'] if wallet.account == p['payer'] else p['payee_nonce']
            if nonce != state['nonce']:
                raise ValueError('Owner nonce changed; prepare a fresh proposal')
            approve(p)
            write_request(args.out, {'payload': p, 'account': wallet.account, 'signature': sign(wallet.key, p)})
            result = {'status': 'authorized', 'file': str(args.out)}
        else:
            messages = [read_json(path, 8192) for path in args.authorizations]
            if any(set(m) != {'payload', 'account', 'signature'} for m in messages) \
                    or canonical(messages[0]['payload']) != canonical(messages[1]['payload']) \
                    or messages[0]['account'] == messages[1]['account']:
                raise ValueError('Two owners must authorize the same exact proposal')
            result = client.request('/commit', {'payload': messages[0]['payload'],
                                    'signatures': {m['account']: m['signature'] for m in messages}})
        print(json.dumps(result, ensure_ascii=True, indent=2))
    except (ValueError, TypeError, KeyError, OSError, EOFError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
