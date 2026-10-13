"""Discrete-day, fixed-quote economic shadow model with conservative payment locks."""
from collections import Counter, defaultdict
import copy
import hashlib
import random
import statistics

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from economy.data import validate
from exchange.crypto import account_id, canonical, public_hex, sign
from exchange.ledger import Ledger

SCENARIOS = ('baseline', 'tight_credit', 'capacity_shortage', 'severe_shortage',
             'payment_delay', 'price_shock', 'settlement_default')


def simulate(data, seed=42, scenario='baseline'):
    validate(data)
    if scenario not in SCENARIOS or type(seed) is not int:
        raise ValueError('Choose a documented scenario and integer seed')
    data = copy.deepcopy(data)
    settings, offers, needs = data['settings'], data['offers'], data['needs']
    if scenario == 'tight_credit':
        for p in data['participants']:
            p['debt_limit_quanta'] //= 4
        settings['initial_allocation_quanta'] = 0
    if scenario == 'capacity_shortage':
        for offer in offers:
            offer['quantity_total'] = max(1, offer['quantity_total']//4)
            offer['quantity_per_day'] = 1
    if scenario == 'severe_shortage':
        for offer in offers:
            offer['quantity_total'] //= 10
            offer['quantity_per_day'] = 1
    if scenario == 'payment_delay':
        for offer in offers:
            offer['payment_delay_days'] += 14
    if scenario == 'settlement_default':
        for offer in offers:
            offer['settlement_success_bps'] = min(offer['settlement_success_bps'], 8500)
    rng = random.Random(seed)
    allocation = settings['initial_allocation_quanta']
    actors = {p['participant_id']: p for p in data['participants']}
    labels = [*actors, 'reserve']
    keys = {who: Ed25519PrivateKey.from_private_bytes(hashlib.sha256(f'economic-simulation-only:{seed}:{who}'.encode()).digest())
            for who in labels}
    addresses = {who: account_id(public_hex(key)) for who, key in keys.items()}
    template = Ledger.create(now=0, max_debt=max(1, len(actors)*allocation, *[p['debt_limit_quanta'] for p in actors.values()]),
                             max_credit=max(1, *[p['credit_limit_quanta'] for p in actors.values()]),
                             max_total_debt=settings['total_debt_limit_quanta'], max_accounts=len(labels), max_events=10000)
    accounts = {}
    for who in labels:
        debt, credit = ((len(actors)*allocation, 0) if who == 'reserve' else
                        (actors[who]['debt_limit_quanta'], actors[who]['credit_limit_quanta']))
        p = template.join_proposal(public_hex(keys[who]), debt, credit, now=0)
        accounts = template.transition_accounts(accounts, p, {addresses[who]: sign(keys[who], p)}, now=0)

    def transfer(buyer, seller, amount, now, resource):
        nonlocal accounts
        p = template.transfer_authorization(addresses[buyer], addresses[seller], amount, resource,
                accounts[addresses[buyer]]['nonce'], accounts[addresses[seller]]['nonce'], now=now)
        accounts = template.transition_accounts(accounts, p, {addresses[who]: sign(keys[who], p) for who in (buyer, seller)}, now=now)

    if allocation:
        for who in actors:
            transfer('reserve', who, allocation, 0, 'analysis_allocation')
    outgoing, incoming = Counter(), Counter()
    remaining = {o['offer_id']: o['quantity_total'] for o in offers}
    demand = {n['need_id']: {'delivered': 0, 'reserved': 0, 'settled': 0} for n in needs}
    budgets = {(r['resource_id'], r['unit']): r['quantity_cap'] for r in data['resource_limits']}
    used_resources = Counter()
    grouped_offers = defaultdict(list)
    for offer in offers:
        grouped_offers[(offer['resource_id'], offer['unit'])].append(offer)
    orders, daily, blocked = [], [], Counter()
    checks, limited = 0, False

    def balance(who):
        return accounts[addresses[who]]['balance']

    def exposure():
        return sum(max(0, -(balance(who)-outgoing[who])) for who in labels)

    def release(order):
        outgoing[order['buyer_id']] -= order['amount_quanta']
        incoming[order['seller_id']] -= order['amount_quanta']

    def process(day):
        for order in orders:
            state = demand[order['need_id']]
            if order['status'] == 'reserved' and order['delivery_day'] <= day:
                state['reserved'] -= order['quantity']
                if rng.randrange(10000) >= order['delivery_success_bps']:
                    order['status'] = 'delivery_failed'
                    release(order)
                else:
                    state['delivered'] += order['quantity']
                    order['status'] = 'delivered_unpaid'
            if order['status'] == 'delivered_unpaid' and order['payment_day'] <= day:
                if rng.randrange(10000) >= order['settlement_success_bps']:
                    order['status'] = 'defaulted_unpaid'
                    # A supplied but unpaid service remains a receivable/liability.
                    # Its reservation is not silently forgiven or spent again.
                else:
                    transfer(order['buyer_id'], order['seller_id'], order['amount_quanta'], day*86400, order['resource_id'])
                    release(order)
                    state['settled'] += order['quantity']
                    order['status'] = 'settled'

    for day in range(settings['days']):
        process(day)
        capacity_used = Counter()
        eligible = [n for n in needs if n['earliest_day'] <= day <= n['deadline_day'] and
                    demand[n['need_id']]['delivered']+demand[n['need_id']]['reserved'] < n['quantity']]
        rng.shuffle(eligible)
        eligible.sort(key=lambda n: (-n['priority'], n['deadline_day']))
        for need in eligible:
            requested = need['quantity']-demand[need['need_id']]['delivered']-demand[need['need_id']]['reserved']
            candidates = [o for o in grouped_offers[(need['resource_id'], need['unit'])] if o['seller_id'] != need['buyer_id']]
            rng.shuffle(candidates)
            candidates.sort(key=lambda o: (o['price_quanta'], o['delivery_delay_days']))
            if not candidates:
                blocked['no_supplier'] += 1
            for offer in candidates:
                if requested <= 0:
                    break
                if len(orders) >= settings['max_orders'] or checks >= settings['max_match_checks']:
                    limited = True
                    blocked['computation_limit'] += 1
                    break
                checks += 1
                if not offer['available_day'] <= day <= offer['expires_day']:
                    blocked['availability'] += 1
                    continue
                price = offer['price_quanta']
                if scenario == 'price_shock' and day >= settings['days']//2:
                    price = (price*125+99)//100
                if price > need['max_unit_price_quanta']:
                    blocked['price'] += 1
                    continue
                if day+offer['delivery_delay_days'] > need['deadline_day']:
                    blocked['delivery_deadline'] += 1
                    continue
                quantity = min(requested, remaining[offer['offer_id']], offer['quantity_per_day']-capacity_used[offer['offer_id']])
                if quantity <= 0:
                    blocked['supplier_capacity'] += 1
                    continue
                resource = (offer['resource_id'], offer['unit'])
                if resource in budgets:
                    quantity = min(quantity, budgets[resource]-used_resources[resource])
                    if quantity <= 0:
                        blocked['resource_budget'] += 1
                        continue
                buyer, seller = need['buyer_id'], offer['seller_id']
                free = balance(buyer)-outgoing[buyer]
                liquidity = max(0, free+actors[buyer]['debt_limit_quanta'])//price
                seller_room = max(0, actors[seller]['credit_limit_quanta']-balance(seller)-incoming[seller])//price
                debt_room = max(0, settings['total_debt_limit_quanta']-exposure())
                collective_room = (max(0, free)+debt_room)//price
                limits = {'buyer_liquidity': liquidity, 'seller_credit_limit': seller_room, 'collective_debt_limit': collective_room}
                for reason, allowed in limits.items():
                    if allowed <= 0:
                        blocked[reason] += 1
                quantity = min(quantity, *limits.values(), 10**12//price)
                if quantity <= 0:
                    continue
                amount = quantity*price
                order = {'order_id': f'order-{len(orders)+1:06d}', 'need_id': need['need_id'],
                         'offer_id': offer['offer_id'], 'buyer_id': buyer, 'seller_id': seller,
                         'resource_id': resource[0], 'unit': resource[1], 'quantity': quantity,
                         'unit_price_quanta': price, 'amount_quanta': amount, 'accepted_day': day,
                         'delivery_day': day+offer['delivery_delay_days'],
                         'payment_day': day+offer['delivery_delay_days']+offer['payment_delay_days'],
                         'delivery_success_bps': offer['delivery_success_bps'],
                         'settlement_success_bps': offer['settlement_success_bps'], 'status': 'reserved'}
                orders.append(order)
                outgoing[buyer] += amount
                incoming[seller] += amount
                remaining[offer['offer_id']] -= quantity
                capacity_used[offer['offer_id']] += quantity
                used_resources[resource] += quantity
                demand[need['need_id']]['reserved'] += quantity
                requested -= quantity
        process(day)
        balances = {who: balance(who) for who in labels}
        if sum(balances.values()) != 0 or exposure() > settings['total_debt_limit_quanta']:
            raise ValueError('Economic accounting or commitment exposure invariant failed')
        daily.append({'day': day, 'balance_sum': sum(balances.values()),
                      'gross_credit_quanta': sum(max(0, b) for b in balances.values()),
                      'gross_debt_quanta': sum(max(0, -b) for b in balances.values()),
                      'reserved_debt_exposure_quanta': exposure(),
                      'outstanding_obligations_quanta': sum(outgoing.values()),
                      'defaulted_unpaid_quanta': sum(o['amount_quanta'] for o in orders if o['status'] == 'defaulted_unpaid'),
                      'orders_settled': sum(o['status'] == 'settled' for o in orders)})

    fractions = [demand[n['need_id']]['delivered']/n['quantity'] for n in needs]
    buyers = defaultdict(list)
    for need, fraction in zip(needs, fractions):
        buyers[need['buyer_id']].append(fraction)
    buyer_ratios = sorted(statistics.mean(values) for values in buyers.values())
    by_resource = []
    for resource in sorted({(n['resource_id'], n['unit']) for n in needs} | set(used_resources)):
        matching = [n for n in needs if (n['resource_id'], n['unit']) == resource]
        by_resource.append({'resource_id': resource[0], 'unit': resource[1],
                            'requested_quantity': sum(n['quantity'] for n in matching),
                            'delivered_quantity': sum(demand[n['need_id']]['delivered'] for n in matching),
                            'settled_quantity': sum(demand[n['need_id']]['settled'] for n in matching),
                            'capacity_committed_quantity': used_resources[resource],
                            'physical_budget_quantity': budgets.get(resource)})
    statuses = dict(Counter(o['status'] for o in orders))
    metrics = {'need_count': len(needs), 'fully_satisfied_needs': sum(f == 1 for f in fractions),
               'mean_need_fulfillment_ratio': statistics.mean(fractions) if fractions else None,
               'mean_buyer_fulfillment_ratio': statistics.mean(buyer_ratios) if buyer_ratios else None,
               'least_served_buyer_decile_ratio': statistics.mean(buyer_ratios[:max(1, len(buyer_ratios)//10)]) if buyer_ratios else None,
               'buyers_with_zero_fulfillment': sum(f == 0 for f in buyer_ratios),
               'orders_accepted': len(orders), 'order_status_counts': statuses,
               'settled_value_quanta': sum(o['amount_quanta'] for o in orders if o['status'] == 'settled'),
               'delivered_unpaid_value_quanta': sum(o['amount_quanta'] for o in orders if o['status'] in ('delivered_unpaid', 'defaulted_unpaid')),
               'defaulted_unpaid_value_quanta': sum(o['amount_quanta'] for o in orders if o['status'] == 'defaulted_unpaid'),
               'future_settlement_value_quanta': sum(o['amount_quanta'] for o in orders if o['status'] == 'delivered_unpaid' and o['payment_day'] >= settings['days']),
               'gross_credit_peak_quanta': max(d['gross_credit_quanta'] for d in daily),
               'reserved_debt_exposure_peak_quanta': max(d['reserved_debt_exposure_quanta'] for d in daily),
               'final_balance_sum': daily[-1]['balance_sum'],
               'mean_settlement_delay_days': statistics.mean(o['payment_day']-o['accepted_day'] for o in orders if o['status'] == 'settled') if statuses.get('settled') else None}
    return {'mode': 'offline_economic_shadow_simulation', 'data_origin_declared': settings['data_origin'],
            'scenario': scenario, 'seed': seed, 'days': settings['days'], 'complete': not limited,
            'limits': {'orders': settings['max_orders'], 'match_checks': settings['max_match_checks']},
            'match_checks': checks, 'metrics': metrics, 'blocking_attempts': dict(blocked),
            'by_resource': by_resource, 'daily': daily, 'orders': orders,
            'final_balances_quanta': {who: balance(who) for who in labels},
            'interpretation': 'Fixed input quotes, bounded greedy matching and exogenous shocks; not a market-equilibrium forecast',
            'real_owner_consent': False, 'live_ledger_modified': False, 'energy_joules': None}
