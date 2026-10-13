"""Bounded mutual credit with bilateral consent and a replay-verifiable journal."""
import copy
import hashlib
import re
import secrets
import time

from exchange.crypto import account_id, canonical, sign, verify
from exchange.charter import community_charter, charter_hash, validate_charter

HEX64 = re.compile(r'[0-9a-f]{64}\Z')
HEX32 = re.compile(r'[0-9a-f]{32}\Z')
RESOURCE = re.compile(r'[a-zA-Z0-9_.:-]{1,64}\Z')
MAX_QUANTA = 10**12
HEADER_FIELDS = {'version', 'ledger_id', 'created_at', 'unit', 'quanta_per_unit', 'policy'}
POLICY_FIELDS = {'max_debt', 'max_credit', 'max_total_debt', 'max_accounts', 'max_events',
                 'max_ttl_seconds', 'max_output_bytes', 'interest', 'protocol_fee'}
COMMON = {'version', 'kind', 'ledger_id', 'request_id', 'issued_at', 'expires_at'}
JOIN = COMMON | {'public_key', 'account', 'debt_limit', 'credit_limit', 'policy_hash'}
TRANSFER = COMMON | {'payer', 'payee', 'amount', 'resource_id', 'payer_nonce', 'payee_nonce'}
CONTROL = COMMON | {'account', 'nonce', 'enabled'}


def integer(value, minimum=0, maximum=MAX_QUANTA):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('An in-range integer is required; fractional or boolean amounts are not allowed')
    return value


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def clock(now):
    return integer(int(time.time()) if now is None else now, 0, 2**63-1)


def validate_header(header):
    if not isinstance(header, dict):
        raise ValueError('Invalid ledger header')
    version = header.get('version')
    if type(version) is not int or version not in (1, 2):
        raise ValueError('Unsupported ledger version')
    if set(header) != HEADER_FIELDS | ({'charter'} if version == 2 else set()):
        raise ValueError('Invalid ledger header')
    if version == 2:
        validate_charter(header['charter'])
    if not isinstance(header['ledger_id'], str) or not HEX64.fullmatch(header['ledger_id']):
        raise ValueError('Invalid ledger identity')
    integer(header['created_at'], 0, 2**63-1)
    if header['unit'] != 'LOCAL' or type(header['quanta_per_unit']) is not int or header['quanta_per_unit'] != 1000:
        raise ValueError('Unsupported mutual-credit unit')
    policy = header['policy']
    if not isinstance(policy, dict) or set(policy) != POLICY_FIELDS:
        raise ValueError('Invalid cooperative policy')
    for key in ('max_debt', 'max_credit', 'max_total_debt'):
        integer(policy[key], 1)
    integer(policy['max_accounts'], 2, 10000)
    integer(policy['max_events'], 1, 10000)
    integer(policy['max_ttl_seconds'], 1, 3600)
    integer(policy['max_output_bytes'], 1024, 1_000_000_000)
    if type(policy['interest']) is not int or policy['interest'] != 0:
        raise ValueError('This prototype has no interest')
    if type(policy['protocol_fee']) is not int or policy['protocol_fee'] != 0:
        raise ValueError('This prototype has no protocol fee')


class Ledger:
    def __init__(self, state):
        self.state = copy.deepcopy(state)
        self.audit()

    @classmethod
    def create(cls, *, max_debt=100_000, max_credit=100_000, max_total_debt=1_000_000,
               max_accounts=100, max_events=1000, max_ttl_seconds=300,
               max_output_bytes=10_000_000, now=None):
        header = {'version': 2, 'ledger_id': secrets.token_hex(32), 'created_at': clock(now),
                  'unit': 'LOCAL', 'quanta_per_unit': 1000, 'charter': community_charter(),
                  'policy': {'max_debt': max_debt, 'max_credit': max_credit,
                             'max_total_debt': max_total_debt, 'max_accounts': max_accounts,
                             'max_events': max_events, 'max_ttl_seconds': max_ttl_seconds,
                             'max_output_bytes': max_output_bytes, 'interest': 0, 'protocol_fee': 0}}
        validate_header(header)
        return cls({'header': header, 'accounts': {}, 'events': [], 'head': digest(header)})

    @property
    def ledger_id(self):
        return self.state['header']['ledger_id']

    @property
    def charter(self):
        return copy.deepcopy(self.state['header'].get('charter'))

    def _base(self, kind, now=None, ttl=None):
        now = clock(now)
        policy = self.state['header']['policy']
        ttl = policy['max_ttl_seconds'] if ttl is None else integer(ttl, 1, policy['max_ttl_seconds'])
        return {'version': self.state['header']['version'], 'kind': kind, 'ledger_id': self.ledger_id,
                'request_id': secrets.token_hex(16), 'issued_at': now, 'expires_at': now+ttl}

    def join_proposal(self, public_key, debt_limit=None, credit_limit=None, now=None):
        policy = self.state['header']['policy']
        proposal = {**self._base('join', now), 'public_key': public_key,
                    'account': account_id(public_key),
                    'debt_limit': policy['max_debt'] if debt_limit is None else debt_limit,
                    'credit_limit': policy['max_credit'] if credit_limit is None else credit_limit,
                    'policy_hash': digest(policy)}
        if self.charter is not None:
            proposal['charter_hash'] = charter_hash(self.charter)
        return proposal

    def transfer_proposal(self, payer, payee, amount, resource_id, now=None, ttl=None):
        accounts = self.state['accounts']
        if payer not in accounts or payee not in accounts:
            raise ValueError('Both participants must have joined this cooperative')
        return self.transfer_authorization(payer, payee, amount, resource_id,
                                           accounts[payer]['nonce'], accounts[payee]['nonce'], now, ttl)

    def transfer_authorization(self, payer, payee, amount, resource_id, payer_nonce, payee_nonce, now=None, ttl=None):
        """Build a wallet-side proposal from nonces; the ledger validates it at commit."""
        return {**self._base('transfer', now, ttl), 'payer': payer, 'payee': payee,
                'amount': amount, 'resource_id': resource_id,
                'payer_nonce': payer_nonce, 'payee_nonce': payee_nonce}

    def control_proposal(self, account, enabled, now=None):
        if account not in self.state['accounts']:
            raise ValueError('Unknown participant')
        return {**self._base('control', now), 'account': account,
                'nonce': self.state['accounts'][account]['nonce'], 'enabled': enabled}

    def _apply(self, accounts, payload, signatures, now, verify_signatures=True):
        if not isinstance(payload, dict) or payload.get('kind') not in ('join', 'transfer', 'control'):
            raise ValueError('Unknown authorization type')
        fields = {'join': JOIN, 'transfer': TRANSFER, 'control': CONTROL}[payload['kind']]
        if payload['kind'] == 'join' and self.state['header']['version'] == 2:
            fields = fields | {'charter_hash'}
        if set(payload) != fields or type(payload['version']) is not int \
                or payload['version'] != self.state['header']['version']:
            raise ValueError('Malformed authorization')
        if payload['ledger_id'] != self.ledger_id:
            raise ValueError('Authorization belongs to another cooperative')
        if not isinstance(payload['request_id'], str) or not HEX32.fullmatch(payload['request_id']):
            raise ValueError('Invalid request identity')
        issued = integer(payload['issued_at'], 0, 2**63-1)
        expires = integer(payload['expires_at'], 0, 2**63-1)
        policy = self.state['header']['policy']
        if not issued <= now < expires or not 1 <= expires-issued <= policy['max_ttl_seconds']:
            raise ValueError('Authorization expired, not yet valid, or exceeds its allowed duration')
        kind = payload['kind']
        if kind == 'join':
            account = payload['account']
            if account != account_id(payload['public_key']) or account in accounts:
                raise ValueError('Account already exists or does not match its owner key')
            if payload['policy_hash'] != digest(policy):
                raise ValueError('The owner did not authorize this cooperative policy')
            if self.charter is not None and payload['charter_hash'] != charter_hash(self.charter):
                raise ValueError('The owner did not authorize this community charter')
            if len(accounts) >= policy['max_accounts']:
                raise ValueError('Participant capacity reached')
            debt = integer(payload['debt_limit'], 0, policy['max_debt'])
            credit = integer(payload['credit_limit'], 0, policy['max_credit'])
            owners = {account: payload['public_key']}
            changes = {account: {'public_key': payload['public_key'], 'debt_limit': debt,
                                 'credit_limit': credit, 'balance': 0, 'nonce': 0, 'enabled': True}}
        elif kind == 'transfer':
            payer, payee = payload['payer'], payload['payee']
            if payer == payee or payer not in accounts or payee not in accounts:
                raise ValueError('Two different enrolled participants are required')
            amount = integer(payload['amount'], 1)
            if not isinstance(payload['resource_id'], str) or not RESOURCE.fullmatch(payload['resource_id']):
                raise ValueError('Use a short opaque resource identifier, without personal text')
            owners = {who: accounts[who]['public_key'] for who in (payer, payee)}
            changes = {who: copy.deepcopy(accounts[who]) for who in owners}
            for who, field in ((payer, 'payer_nonce'), (payee, 'payee_nonce')):
                if not accounts[who]['enabled']:
                    raise ValueError('A participant has paused their account')
                if integer(payload[field]) != accounts[who]['nonce']:
                    raise ValueError('Replayed or stale authorization nonce')
                changes[who]['nonce'] += 1
            changes[payer]['balance'] -= amount
            changes[payee]['balance'] += amount
        else:
            account = payload['account']
            if account not in accounts or type(payload['enabled']) is not bool:
                raise ValueError('Unknown participant or invalid account control')
            if integer(payload['nonce']) != accounts[account]['nonce']:
                raise ValueError('Replayed or stale authorization nonce')
            owners = {account: accounts[account]['public_key']}
            changes = {account: {**accounts[account], 'enabled': payload['enabled'],
                                 'nonce': accounts[account]['nonce']+1}}
        if verify_signatures:
            if not isinstance(signatures, dict) or set(signatures) != set(owners):
                raise ValueError('Every affected owner must sign this exact authorization')
            for owner, public_key in owners.items():
                verify(public_key, payload, signatures[owner])
        candidate = {**accounts, **changes}
        for account in changes.values():
            if not -account['debt_limit'] <= account['balance'] <= account['credit_limit']:
                raise ValueError('A participant balance limit would be exceeded')
        if sum(max(0, -a['balance']) for a in candidate.values()) > policy['max_total_debt']:
            raise ValueError('The cooperative total debt limit would be exceeded')
        if sum(a['balance'] for a in candidate.values()) != 0:
            raise ValueError('Credit and debt must balance exactly')
        accounts.update(changes)

    def validate_proposal(self, payload, now=None):
        self._apply(copy.deepcopy(self.state['accounts']), payload, {}, clock(now), verify_signatures=False)

    def transition_accounts(self, accounts, payload, signatures, now=None):
        """Validated candidate state for a transactional backend; input is unchanged."""
        candidate = accounts.copy()
        self._apply(candidate, payload, signatures, clock(now))
        return candidate

    def commit(self, payload, signatures, now=None):
        now = clock(now)
        if not isinstance(payload, dict):
            raise ValueError('An authorization object is required')
        if len(self.state['events']) >= self.state['header']['policy']['max_events']:
            raise ValueError('Journal event limit reached; nothing was discarded')
        previous_time = (self.state['events'][-1]['committed_at'] if self.state['events']
                         else self.state['header']['created_at'])
        if now < previous_time:
            raise ValueError('Ledger clock moved backwards')
        if any(e['payload']['request_id'] == payload.get('request_id') for e in self.state['events']):
            raise ValueError('Request already committed')
        candidate = copy.deepcopy(self.state)
        self._apply(candidate['accounts'], payload, signatures, now)
        event = {'index': len(candidate['events'])+1, 'previous_hash': candidate['head'],
                 'committed_at': now, 'payload': copy.deepcopy(payload),
                 'signatures': copy.deepcopy(signatures)}
        event['hash'] = digest(event)
        candidate['events'].append(event)
        candidate['head'] = event['hash']
        self.state = candidate
        return copy.deepcopy(event)

    def audit(self, required_head=None):
        state = self.state
        if not isinstance(state, dict) or set(state) != {'header', 'accounts', 'events', 'head'}:
            raise ValueError('Invalid ledger state')
        validate_header(state['header'])
        if not isinstance(state['events'], list) or len(state['events']) > state['header']['policy']['max_events']:
            raise ValueError('Invalid journal size')
        head, rebuilt = digest(state['header']), {}
        previous_time, seen = state['header']['created_at'], set()
        known_heads = {head}
        for index, event in enumerate(state['events'], 1):
            if not isinstance(event, dict) or set(event) != {'index', 'previous_hash', 'committed_at',
                                                          'payload', 'signatures', 'hash'}:
                raise ValueError('Malformed journal event')
            content = {k: v for k, v in event.items() if k != 'hash'}
            if type(event['index']) is not int or event['index'] != index or event['previous_hash'] != head:
                raise ValueError('Broken journal ordering')
            if event['hash'] != digest(content):
                raise ValueError('Journal hash mismatch')
            now = clock(event['committed_at'])
            if now < previous_time:
                raise ValueError('Journal time moved backwards')
            if not isinstance(event['payload'], dict):
                raise ValueError('Malformed journal authorization')
            request = event['payload'].get('request_id')
            if request in seen:
                raise ValueError('Duplicate journal request')
            self._apply(rebuilt, event['payload'], event['signatures'], now)
            seen.add(request)
            previous_time, head = now, event['hash']
            known_heads.add(head)
        if canonical(state['accounts']) != canonical(rebuilt) or state['head'] != head:
            raise ValueError('Cached balances or head do not match the signed journal')
        if required_head is not None and required_head not in known_heads:
            raise ValueError('A previously observed receipt is missing: possible rollback or wrong ledger')
        charter = self.charter
        return {'ledger_id': self.ledger_id, 'head': head, 'events': len(state['events']),
                'protocol_version': state['header']['version'],
                'charter': ({'version': charter['version'], 'hash': charter_hash(charter),
                             'motto': charter['motto'], 'fiat_conversion_allowed': False}
                            if charter is not None else None),
                'accounts': len(rebuilt), 'balance_sum': sum(a['balance'] for a in rebuilt.values()),
                'total_debt': sum(max(0, -a['balance']) for a in rebuilt.values()),
                'balances': {who: a['balance'] for who, a in rebuilt.items()},
                'unit': 'LOCAL', 'quanta_per_unit': 1000}


def owner_signature(key, payload):
    from exchange.crypto import public_hex
    return {account_id(public_hex(key)): sign(key, payload)}
