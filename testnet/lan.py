"""Owner-created keys, public CSRs, and an explicit mutual-TLS LAN pilot."""
import argparse
import getpass
import json
from pathlib import Path
import threading

from exchange.crypto import create_key_file, load_key_file, public_hex, account_id
from exchange.store import read_json, write_request
from testnet.http import Server
from testnet.node import Node
from testnet.tls import make_ca, make_csr, issue_client, server_context
from v2.storage import OutputBudget


def password(confirm=False):
    value = getpass.getpass('Passphrase locale de la cle privee : ')
    if confirm and value != getpass.getpass('Confirmez la passphrase : '):
        raise ValueError('Passphrases do not match')
    return value


def initialize(folder, public_files, server_ip, secret, allocation=1000):
    public = [read_json(path, 8192) for path in public_files]
    ids = []
    for entry in public:
        if entry.get('account_id') != account_id(entry.get('public_key')):
            raise ValueError('A participant public document does not match its key')
        ids.append(entry['account_id'])
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    identity = create_key_file(folder/'reserve.key.pem', secret)
    reserve_key = load_key_file(folder/'reserve.key.pem', secret)
    node = Node.create(folder/'network', identity['account_id'], ids, allocation)
    try:
        make_ca(folder/'pki', secret, [server_ip, '127.0.0.1', 'localhost'])
        who, cert = issue_client(folder/'pki', make_csr(reserve_key), secret, {identity['account_id'], *ids})
        with (folder/'reserve.crt').open('xb') as file:
            file.write(cert)
        info = {'ledger_id': node.ledger.ledger_id, 'server_ip': server_ip, 'port': 8443,
                'allocation_quanta': allocation, 'participants': public, 'reserve_account': who,
                'primary_resource': node.primary_resource, 'charter': node.header['charter']}
        write_request(folder/'network.json', info)
        return info
    finally:
        node.close()


def serve(path, pki, secret, host, port=8443):
    pki = Path(pki)
    context = server_context(pki/'ca.crt', pki/'server.crt', pki/'server.key.pem', secret)
    node = Node(path)
    server = None
    try:
        server = Server(node, port, host=host, tls_context=context)
        print(json.dumps({'url': server.url, 'ledger_id': node.ledger.ledger_id,
                          'transport': 'TLS 1.3 with required wallet client certificates',
                          'source_path': '/source'}, indent=2), flush=True)
        server.serve_forever()
    finally:
        if server is not None:
            server.server_close()
        node.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    keygen = sub.add_parser('keygen')
    keygen.add_argument('--out', type=Path, required=True)
    init = sub.add_parser('init')
    init.add_argument('--out', type=Path, required=True)
    init.add_argument('--public', type=Path, nargs='+', required=True)
    init.add_argument('--server-ip', required=True)
    init.add_argument('--allocation', type=int, default=1000)
    issue = sub.add_parser('issue')
    issue.add_argument('--ledger', type=Path, required=True)
    issue.add_argument('--pki', type=Path, required=True)
    issue.add_argument('--csr', type=Path, required=True)
    issue.add_argument('--out', type=Path, required=True)
    host = sub.add_parser('serve')
    host.add_argument('--ledger', type=Path, required=True)
    host.add_argument('--pki', type=Path, required=True)
    host.add_argument('--host', required=True)
    host.add_argument('--port', type=int, default=8443)
    args = parser.parse_args()
    try:
        if args.command == 'keygen':
            secret = password(True)
            args.out.mkdir(parents=True, exist_ok=False)
            identity = create_key_file(args.out/'wallet.key.pem', secret)
            key = load_key_file(args.out/'wallet.key.pem', secret)
            write_request(args.out/'wallet.public.json', identity)
            with (args.out/'wallet.csr').open('xb') as file:
                file.write(make_csr(key))
            print(json.dumps({'public_identity': identity, 'public_document': str(args.out/'wallet.public.json'),
                              'public_csr': str(args.out/'wallet.csr')}, indent=2))
        elif args.command == 'init':
            print(json.dumps(initialize(args.out, args.public, args.server_ip, password(True), args.allocation), indent=2))
        elif args.command == 'issue':
            node = Node(args.ledger, writable=False)
            try:
                who, certificate = issue_client(args.pki, args.csr.read_bytes(), password(),
                                                 {node.plan['reserve_account'], *node.eligible})
                if not args.out.parent.is_dir():
                    raise ValueError('Certificate output parent must exist')
                OutputBudget(args.out.parent, 1_000_000)._check(len(certificate))
                with args.out.open('xb') as file:
                    file.write(certificate)
                print(json.dumps({'account': who, 'public_certificate': str(args.out)}, indent=2))
            finally:
                node.close()
        else:
            serve(args.ledger, args.pki, password(), args.host, args.port)
    except KeyboardInterrupt:
        print('Serveur LAN arrete proprement.')
    except (ValueError, OSError, EOFError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
