"""Bounded JSON HTTP API, strictly on IPv4 loopback."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
import threading
import ipaddress

from v2.storage import BudgetExceeded


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, node, port=0, host='127.0.0.1', tls_context=None):
        from testnet.source import source_archive
        self.node = node
        self.slots = threading.BoundedSemaphore(16)
        self.source_zip = source_archive()
        address = ipaddress.ip_address(host)
        if address.version != 4 or not (address.is_private or address.is_loopback) or address.is_unspecified:
            raise ValueError('Choose an explicit private IPv4 address for this pilot')
        if not address.is_loopback and tls_context is None:
            raise ValueError('A LAN listener requires mutual TLS')
        self.tls_context = tls_context
        super().__init__((host, port), Handler)

    def get_request(self):
        connection, address = super().get_request()
        if self.tls_context is not None:
            try:
                connection.settimeout(5)
                connection = self.tls_context.wrap_socket(connection, server_side=True)
            except Exception:
                connection.close()
                raise
        return connection, address

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    @property
    def url(self):
        scheme = 'https' if self.tls_context is not None else 'http'
        return f'{scheme}://{self.server_address[0]}:{self.server_port}'


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass

    def authenticate(self, payload=None):
        if self.server.tls_context is None:
            return
        from testnet.tls import peer_wallet
        who = peer_wallet(self.connection)
        node = self.server.node
        if who not in node.eligible and who != node.plan['reserve_account']:
            raise ValueError('Client certificate wallet is not admitted')
        if payload is not None:
            if not isinstance(payload, dict):
                raise ValueError('Exact signed payload required')
            parties = ({payload.get('payer'), payload.get('payee')} if payload.get('kind') == 'transfer'
                       else {payload.get('account')})
            if who not in parties:
                raise ValueError('Client certificate does not belong to an affected owner')

    def reply(self, status, body):
        payload = json.dumps(body, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('ascii')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def source_reply(self):
        payload = self.server.source_zip
        self.send_response(200)
        self.send_header('Content-Type', 'application/zip')
        self.send_header('Content-Disposition', 'attachment; filename="quanta-network-source.zip"')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def do_GET(self):
        try:
            self.authenticate()
            if self.path == '/health':
                health = self.server.node.health()
                health['software'] = {'license': 'AGPL-3.0-only', 'copyright': '2026 jeremy zgonec',
                                      'source_path': '/source', 'warranty': 'No warranty; see LICENSE'}
                self.reply(200, health)
            elif self.path == '/source':
                self.source_reply()
            elif self.path.startswith('/challenge/') and len(self.path) == len('/challenge/')+64:
                self.reply(200, self.server.node.challenge(self.path[len('/challenge/'):]))
            else:
                self.reply(404, {'error': 'Unknown route'})
        except (ValueError, TypeError, KeyError) as error:
            self.reply(403 if 'certificate' in str(error).lower() else 400, {'error': str(error)})

    def do_POST(self):
        try:
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                self.reply(415, {'error': 'JSON content type required'})
                return
            length = int(self.headers.get('Content-Length', '0'))
            if not 1 <= length <= 8192:
                self.reply(413, {'error': 'Request body must be between 1 and 8192 bytes'})
                return
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or set(body) != {'payload', 'signatures'}:
                raise ValueError('Exact payload and signatures fields are required')
            self.authenticate(body['payload'])
            if self.path == '/commit':
                result = self.server.node.commit(body['payload'], body['signatures'])
            elif self.path == '/account':
                if not isinstance(body['signatures'], dict) or set(body['signatures']) != {body['payload'].get('account')}:
                    raise ValueError('The account owner must sign the read challenge')
                result = self.server.node.read_account(body['payload'], body['signatures'][body['payload']['account']])
            else:
                self.reply(404, {'error': 'Unknown route'})
                return
            self.reply(200, result)
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as error:
            status = 403 if 'signature' in str(error).lower() or 'certificate' in str(error).lower() else 409
            self.reply(status, {'error': str(error)})
        except (BudgetExceeded, sqlite3.Error) as error:
            self.reply(507, {'error': str(error)})
