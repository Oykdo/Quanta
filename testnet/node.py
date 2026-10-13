"""Single-coordinator SQLite ledger with nonce checks and one primary grant per wallet."""
import copy
import json
from pathlib import Path
import secrets
import sqlite3
import threading

from exchange.crypto import canonical, verify
from exchange.ledger import Ledger, clock, digest, integer, HEX64
from v2.storage import OutputBudget


class Node:
    def __init__(self, path, writable=True):
        self.path = Path(path).resolve()
        self.lock = threading.RLock()
        self.challenges = {}
        self.writable = writable
        self.lease = self.path.with_name(self.path.name+'.lock') if writable else None
        if self.lease is not None:
            try:
                self.lease.mkdir()
            except FileExistsError as error:
                raise ValueError('Another writer or a stale testnet lock exists') from error
        self.db = None
        try:
            self.db = sqlite3.connect(self.path.as_uri()+'?mode='+('rw' if writable else 'ro'),
                                      uri=True, isolation_level=None, check_same_thread=False, timeout=5)
            self.db.execute('PRAGMA busy_timeout=5000')
            self.db.execute('BEGIN')
            self.header = self._meta('header')
            self.plan = self._meta('plan')
            self.head = self._meta('head')
            self.count = self._meta('event_count')
            self.last_time = self._meta('last_time')
            self.accounts = {who: json.loads(body) for who, body in self.db.execute('SELECT id, body FROM accounts')}
            events = [json.loads(body) for (body,) in self.db.execute('SELECT body FROM events ORDER BY idx')]
            self._validate_plan()
            Ledger({'header': self.header, 'accounts': self.accounts, 'events': events, 'head': self.head})
            if self.count != len(events) or self.last_time != (events[-1]['committed_at'] if events else self.header['created_at']):
                raise ValueError('SQLite journal counters differ from the signed events')
            self.ledger = Ledger({'header': self.header, 'accounts': {}, 'events': [], 'head': digest(self.header)})
            self.storage = OutputBudget(self.path.parent, self.header['policy']['max_output_bytes'])
            self._check_allocation_rows(events)
            # Metadata, accounts, receipts and allocations are validated in one
            # SQLite read snapshot, including when another process is writing.
            self.snapshot_events = events if not writable else None
            self.db.commit()
            if writable:
                self.db.execute('PRAGMA synchronous=FULL')
                self.db.execute('PRAGMA journal_mode=DELETE')
                page_size = self.db.execute('PRAGMA page_size').fetchone()[0]
                self.db_limit = (self.storage.max_bytes//4//page_size)*page_size
                self.db.execute(f'PRAGMA max_page_count={self.db_limit//page_size}')
        except Exception:
            self.close()
            raise

    @classmethod
    def create(cls, folder, reserve_id, eligible_ids, allocation=1000, max_output_bytes=32_000_000):
        ids = sorted(eligible_ids)
        integer(len(ids), 2, 3000)
        integer(allocation, 1, 1_000_000)
        integer(max_output_bytes, 1_000_000, 1_000_000_000)
        if len(set(ids)) != len(ids) or reserve_id in ids or any(not HEX64.fullmatch(who) for who in [reserve_id, *ids]):
            raise ValueError('Unique reserve and synthetic wallet identities are required')
        ledger = Ledger.create(max_debt=len(ids)*allocation, max_credit=max(2*allocation, 1),
                               max_total_debt=2*len(ids)*allocation, max_accounts=len(ids)+1,
                               max_events=min(10000, 3*len(ids)+100), max_output_bytes=max_output_bytes)
        plan = {'version': 1, 'reserve_account': reserve_id, 'eligible_accounts': ids,
                'allocation_quanta': allocation, 'scope': 'synthetic_wallet_testnet_only'}
        folder = Path(folder).resolve()
        folder.mkdir(parents=True, exist_ok=False)
        path = folder/'ledger.sqlite3'
        db = sqlite3.connect(path, isolation_level=None)
        try:
            db.execute('PRAGMA page_size=4096')
            db.execute(f'PRAGMA max_page_count={max_output_bytes//4//4096}')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA journal_mode=DELETE')
            db.executescript('CREATE TABLE meta (key TEXT PRIMARY KEY, body TEXT NOT NULL);'
                             'CREATE TABLE accounts (id TEXT PRIMARY KEY, body TEXT NOT NULL);'
                             'CREATE TABLE events (idx INTEGER PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, body TEXT NOT NULL);'
                             'CREATE TABLE allocations (account TEXT PRIMARY KEY, amount INTEGER NOT NULL, event_idx INTEGER UNIQUE NOT NULL);')
            db.execute('BEGIN IMMEDIATE')
            values = {'header': ledger.state['header'], 'plan': plan, 'head': ledger.state['head'],
                      'event_count': 0, 'last_time': ledger.state['header']['created_at']}
            db.executemany('INSERT INTO meta VALUES (?, ?)', [(key, canonical(value).decode('ascii')) for key, value in values.items()])
            db.commit()
        finally:
            db.close()
        return cls(path)

    def _meta(self, key):
        row = self.db.execute('SELECT body FROM meta WHERE key=?', (key,)).fetchone()
        if row is None:
            raise ValueError('Missing testnet metadata')
        return json.loads(row[0])

    def _validate_plan(self):
        if set(self.plan) != {'version', 'reserve_account', 'eligible_accounts', 'allocation_quanta', 'scope'} \
                or self.plan['version'] != 1 or self.plan['scope'] != 'synthetic_wallet_testnet_only':
            raise ValueError('Unsupported primary distribution plan')
        ids = self.plan['eligible_accounts']
        integer(len(ids), 2, 3000)
        integer(self.plan['allocation_quanta'], 1, 1_000_000)
        if len(ids) != len(set(ids)) or self.plan['reserve_account'] in ids \
                or any(not isinstance(who, str) or not HEX64.fullmatch(who) for who in [self.plan['reserve_account'], *ids]):
            raise ValueError('Malformed primary distribution identities')
        self.eligible = set(ids)
        self.primary_resource = 'primary_'+digest(self.plan)[:40]

    def _check_allocation_rows(self, events):
        expected = {}
        for event in events:
            p = event['payload']
            self._rules(p, expected)
            if p['kind'] == 'transfer' and p['resource_id'] == self.primary_resource:
                expected[p['payee']] = (p['amount'], event['index'])
        actual = {who: (amount, index) for who, amount, index in self.db.execute('SELECT account, amount, event_idx FROM allocations')}
        if actual != expected:
            raise ValueError('Allocation index differs from signed primary receipts')

    def _rules(self, payload, prior=None):
        kind = payload.get('kind')
        reserve, q = self.plan['reserve_account'], self.plan['allocation_quanta']
        if kind == 'join':
            who = payload.get('account')
            if who not in self.eligible and who != reserve:
                raise ValueError('Wallet is not enrolled in this synthetic test plan')
            limits = (len(self.eligible)*q, 0) if who == reserve else (q, 2*q)
            if (payload.get('debt_limit'), payload.get('credit_limit')) != limits:
                raise ValueError('Wallet limits differ from the agreed test distribution plan')
        elif kind == 'transfer':
            payer, payee = payload.get('payer'), payload.get('payee')
            if reserve in (payer, payee) or str(payload.get('resource_id', '')).startswith('primary_'):
                if payer != reserve or payee not in self.eligible or payload.get('amount') != q \
                        or payload.get('resource_id') != self.primary_resource:
                    raise ValueError('Reserve can only perform the exact primary distribution')
                duplicate = (payee in prior if prior is not None else
                             self.db.execute('SELECT 1 FROM allocations WHERE account=?', (payee,)).fetchone() is not None)
                if duplicate:
                    raise ValueError('Wallet already received its primary allocation')
        elif kind != 'control':
            raise ValueError('Unsupported testnet operation')

    def commit(self, payload, signatures, now=None):
        if not self.writable:
            raise ValueError('Read-only testnet')
        if not isinstance(payload, dict) or not isinstance(signatures, dict):
            raise ValueError('An exact signed operation is required')
        with self.lock:
            existing = self.db.execute('SELECT body FROM events WHERE request_id=?', (payload.get('request_id'),)).fetchone()
            if existing:
                receipt = json.loads(existing[0])
                if canonical(receipt['payload']) == canonical(payload) and canonical(receipt['signatures']) == canonical(signatures):
                    return {'status': 'already_committed', 'receipt': receipt}
                raise ValueError('Request identity reused for a different authorization')
            now = clock(now)
            if now < self.last_time or self.count >= self.header['policy']['max_events']:
                raise ValueError('Journal time or event limit prevents this operation')
            self._rules(payload)
            candidate = self.ledger.transition_accounts(self.accounts, payload, signatures, now)
            event = {'index': self.count+1, 'previous_hash': self.head, 'committed_at': now,
                     'payload': copy.deepcopy(payload), 'signatures': copy.deepcopy(signatures)}
            event['hash'] = digest(event)
            # SQLite is restricted to one quarter of the folder quota. Reserve space
            # for its rollback journal (page data + headers) BEFORE opening a write.
            self.storage._check(self.db_limit+self.db_limit//4+65536+8192)
            affected = ([payload['account']] if payload['kind'] in ('join', 'control')
                        else [payload['payer'], payload['payee']])
            try:
                self.db.execute('BEGIN IMMEDIATE')
                if self._meta('head') != self.head:
                    raise ValueError('Another writer changed the ledger head')
                for who in affected:
                    self.db.execute('INSERT INTO accounts VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                                    (who, canonical(candidate[who]).decode('ascii')))
                self.db.execute('INSERT INTO events VALUES (?, ?, ?)',
                                (event['index'], payload['request_id'], canonical(event).decode('ascii')))
                if payload['kind'] == 'transfer' and payload['resource_id'] == self.primary_resource:
                    self.db.execute('INSERT INTO allocations VALUES (?, ?, ?)', (payload['payee'], payload['amount'], event['index']))
                for key, value in (('head', event['hash']), ('event_count', event['index']), ('last_time', now)):
                    self.db.execute('UPDATE meta SET body=? WHERE key=?', (canonical(value).decode('ascii'), key))
                self.db.commit()
            except Exception:
                if self.db.in_transaction:
                    self.db.rollback()
                raise
            self.accounts, self.head, self.count, self.last_time = candidate, event['hash'], event['index'], now
            return {'status': 'committed', 'receipt': event}

    def health(self):
        with self.lock:
            count = self.db.execute('SELECT COUNT(*) FROM allocations').fetchone()[0]
            return {'mode': 'loopback_synthetic_testnet', 'ledger_id': self.ledger.ledger_id,
                    'header': self.header, 'plan_hash': digest(self.plan), 'primary_resource': self.primary_resource,
                    'head': self.head, 'events': self.count, 'registered_accounts': len(self.accounts),
                    'primary_allocations': count, 'wallet_target': len(self.eligible),
                    'allocation_quanta': self.plan['allocation_quanta'],
                    'balance_sum': sum(a['balance'] for a in self.accounts.values())}

    def challenge(self, who):
        with self.lock:
            if who not in self.accounts:
                raise ValueError('Unknown wallet')
            now = clock(None)
            self.challenges = {nonce: p for nonce, p in self.challenges.items() if p['expires_at'] > now}
            if len(self.challenges) >= 2*(len(self.eligible)+1):
                raise ValueError('Challenge capacity reached; retry after expiration')
            p = {'version': 1, 'kind': 'read_account', 'ledger_id': self.ledger.ledger_id,
                 'account': who, 'nonce': secrets.token_hex(32), 'expires_at': now+60}
            self.challenges[p['nonce']] = p
            return p

    def read_account(self, payload, signature):
        with self.lock:
            if not isinstance(payload, dict):
                raise ValueError('A signed challenge is required')
            pending = self.challenges.get(payload.get('nonce'))
            if pending is None or canonical(pending) != canonical(payload) or clock(None) >= pending['expires_at']:
                raise ValueError('Replayed, altered or expired read challenge')
            who = payload['account']
            verify(self.accounts[who]['public_key'], payload, signature)
            del self.challenges[payload['nonce']]
            return {'account': who, **copy.deepcopy(self.accounts[who]), 'ledger_id': self.ledger.ledger_id}

    def audit(self):
        with self.lock:
            self.db.execute('BEGIN')
            try:
                events = [json.loads(body) for (body,) in self.db.execute('SELECT body FROM events ORDER BY idx')]
                accounts = {who: json.loads(body) for who, body in self.db.execute('SELECT id, body FROM accounts')}
                head = self._meta('head')
                ledger = Ledger({'header': self.header, 'accounts': accounts, 'events': events, 'head': head})
                report = ledger.audit()
                self._check_allocation_rows(events)
                count, total = self.db.execute('SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM allocations').fetchone()
            finally:
                self.db.commit()
            q, n = self.plan['allocation_quanta'], len(self.eligible)
            report.update({'allocation_count': count, 'allocation_quanta': q, 'allocated_total_quanta': total,
                           'wallet_target': n, 'distribution_complete': count == n,
                           'all_primary_grants_equal': total == count*q,
                           'reserve_balance': accounts.get(self.plan['reserve_account'], {}).get('balance', 0)})
            return report

    def close(self):
        with self.lock:
            self.writable = False
            if self.db is not None:
                self.db.close()
                self.db = None
            if self.lease is not None and self.lease.exists():
                self.lease.rmdir()
                self.lease = None
