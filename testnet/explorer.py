"""Verified local wallet histories and a balanced logical overlay of ONE ledger."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path

from exchange.crypto import account_id
from exchange.ledger import digest, integer
from testnet.node import Node
from v2.storage import OutputBudget


def snapshot(path):
    node = Node(path, writable=False)
    try:
        return {'header': copy.deepcopy(node.header), 'plan': copy.deepcopy(node.plan),
                'accounts': copy.deepcopy(node.accounts), 'events': copy.deepcopy(node.snapshot_events),
                'head': node.head, 'primary_resource': node.primary_resource}
    finally:
        node.close()


def catalogue(state):
    grants = {e['payload']['payee']: e for e in state['events']
              if e['payload']['kind'] == 'transfer' and e['payload']['resource_id'] == state['primary_resource']}
    wallets = []
    for index, who in enumerate(sorted(state['plan']['eligible_accounts']), 1):
        current, grant = state['accounts'].get(who), grants.get(who)
        if current is not None and account_id(current['public_key']) != who:
            raise ValueError('Wallet address does not match its public key')
        wallets.append({'alias': f'wallet-{index:06d}', 'address': who,
                        'registered': current is not None,
                        'public_key_ed25519_hex': current['public_key'] if current else None,
                        'balance_quanta': current['balance'] if current else None,
                        'operation_nonce': current['nonce'] if current else None,
                        'enabled': current['enabled'] if current else None,
                        'primary_allocation_quanta': grant['payload']['amount'] if grant else None,
                        'primary_receipt_index': grant['index'] if grant else None})
    reserve_id = state['plan']['reserve_account']
    reserve = state['accounts'].get(reserve_id)
    return {'mode': 'local_operator_view_of_synthetic_wallets',
            'ledger_id': state['header']['ledger_id'], 'head': state['head'],
            'wallet_count': len(wallets), 'registered_wallets': sum(w['registered'] for w in wallets),
            'address_format': 'SHA-256(raw Ed25519 public key), 64 hexadecimal characters',
            'private_key_exported': False, 'aliases_are_human_identities': False,
            'reserve': {'alias': 'reserve', 'address': reserve_id,
                        'balance_quanta': reserve['balance'] if reserve else None},
            'wallets': wallets}


def resolve(state, reference):
    if reference == 'reserve':
        return state['plan']['reserve_account'], 'reserve'
    for wallet in catalogue(state)['wallets']:
        if reference in (wallet['alias'], wallet['address']):
            return wallet['address'], wallet['alias']
    raise ValueError('Unknown wallet alias or public address')


def wallet_trace(state, reference, offset=0, limit=100):
    integer(offset, 0, 10000)
    integer(limit, 1, 10000)
    who, alias = resolve(state, reference)
    current = state['accounts'].get(who)
    if current is None:
        raise ValueError('This test wallet has not joined the ledger yet')
    history, balance, nonce = [], 0, 0
    for event in state['events']:
        p = event['payload']
        involved = (p.get('account') == who if p['kind'] in ('join', 'control')
                    else who in (p['payer'], p['payee']))
        if not involved:
            continue
        direction, counterparty, amount = p['kind'], None, 0
        if p['kind'] == 'transfer':
            incoming = p['payee'] == who
            direction = 'incoming' if incoming else 'outgoing'
            counterparty = p['payer'] if incoming else p['payee']
            amount = p['amount']
            before = p['payee_nonce'] if incoming else p['payer_nonce']
            if before != nonce:
                raise ValueError('Wallet trace contains a discontinuous nonce')
            balance += amount if incoming else -amount
            nonce += 1
        elif p['kind'] == 'control':
            if p['nonce'] != nonce:
                raise ValueError('Wallet control nonce is discontinuous')
            nonce += 1
        history.append({'index': event['index'], 'event_hash': event['hash'],
                        'previous_hash': event['previous_hash'], 'request_id': p['request_id'],
                        'committed_utc': datetime.fromtimestamp(event['committed_at'], timezone.utc).isoformat().replace('+00:00', 'Z'),
                        'direction': direction, 'counterparty': counterparty, 'amount_quanta': amount,
                        'balance_after_quanta': balance, 'nonce_after': nonce,
                        'resource_id': p.get('resource_id'),
                        'receipt': copy.deepcopy(event)})
    if (balance, nonce) != (current['balance'], current['nonce']):
        raise ValueError('Reconstructed wallet state differs from the ledger')
    return {'ledger_id': state['header']['ledger_id'], 'head': state['head'],
            'alias': alias, 'address': who, 'public_key_ed25519_hex': current['public_key'],
            'balance_quanta': balance, 'operation_nonce': nonce, 'enabled': current['enabled'],
            'signatures_and_chain_verified': True, 'private_key_exported': False,
            'history_total': len(history), 'offset': offset, 'limit': limit,
            'history': history[offset:offset+limit],
            'has_more': offset+limit < len(history)}


def _connected(peers, excluded=None):
    active = set(peers) - (excluded or set())
    if not active:
        return False
    seen, pending = set(), [min(active)]
    while pending:
        who = pending.pop()
        if who not in seen:
            seen.add(who)
            pending.extend((peers[who] & active) - seen)
    return seen == active


def branches(state, count=10):
    ids = sorted(state['plan']['eligible_accounts'])
    integer(count, 2, min(100, len(ids)//2))
    groups = [ids[index::count] for index in range(count)]
    peers = {who: set() for who in ids}

    def link(first, second):
        if first != second:
            peers[first].add(second)
            peers[second].add(first)

    for branch_index, members in enumerate(groups):
        adjacent = {(branch_index-1) % count, (branch_index+1) % count}
        if count >= 4 and count % 2 == 0:
            adjacent.add((branch_index+count//2) % count)
        for position, who in enumerate(members):
            link(who, members[(position-1) % len(members)])
            link(who, members[(position+1) % len(members)])
            for neighbor in adjacent:
                link(who, groups[neighbor][position % len(groups[neighbor])])
    sizes = [len(group) for group in groups]
    if max(sizes)-min(sizes) > 1 or not _connected(peers):
        raise ValueError('Logical branch plan is unbalanced or disconnected')
    survives = {f'branch-{n+1:03d}': _connected(peers, set(group)) for n, group in enumerate(groups)}
    members = catalogue(state)['wallets']
    details = {wallet['address']: wallet for wallet in members}
    result = {'mode': 'logical_overlay_single_ledger', 'ledger_id': state['header']['ledger_id'],
              'head': state['head'], 'branch_count': count, 'wallet_count': len(ids),
              'branch_size_min': min(sizes), 'branch_size_max': max(sizes),
              'peer_degree_min': min(len(p) for p in peers.values()),
              'peer_degree_max': max(len(p) for p in peers.values()),
              'undirected_links': sum(len(p) for p in peers.values())//2,
              'connected': True, 'connected_after_each_single_branch_removal': survives,
              'scope': 'Planned peer graph, not physical connections or distributed consensus; no balance changes',
              'private_key_exported': False,
              'branches': [{'id': f'branch-{index+1:03d}', 'wallet_count': len(group),
                            'current_balance_sum_quanta': sum(state['accounts'].get(who, {}).get('balance', 0) for who in group),
                            'wallets': [{**details[who], 'peers': sorted(peers[who])} for who in group]}
                           for index, group in enumerate(groups)]}
    result['plan_sha256'] = digest(result)
    return result


def write_export(path, value, budget):
    path = Path(path).resolve()
    if path.exists():
        raise FileExistsError('An existing wallet or branch export must not be overwritten')
    if not path.parent.is_dir():
        raise ValueError('Export parent directory must exist')
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
    OutputBudget(path.parent, budget)._check(len(payload))
    # Exclusive creation also prevents a concurrent exporter from replacing it.
    with path.open('xb') as file:
        file.write(payload)
