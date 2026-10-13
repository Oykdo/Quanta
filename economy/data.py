"""Bounded, explicit CSV inputs for synthetic or pseudonymous field observations."""
import csv
import hashlib
import io
import json
from pathlib import Path
import re

from exchange.ledger import integer
from v2.storage import OutputBudget

IDENTIFIER = re.compile(r'[A-Za-z0-9_.:-]{1,64}\Z')
TABLES = {
    'participants': ('participant_id', 'debt_limit_quanta', 'credit_limit_quanta'),
    'offers': ('offer_id', 'seller_id', 'resource_id', 'unit', 'quantity_total', 'quantity_per_day',
               'price_quanta', 'available_day', 'expires_day', 'delivery_delay_days', 'payment_delay_days',
               'delivery_success_bps', 'settlement_success_bps'),
    'needs': ('need_id', 'buyer_id', 'resource_id', 'unit', 'quantity', 'max_unit_price_quanta',
              'earliest_day', 'deadline_day', 'priority'),
    'resource_limits': ('resource_id', 'unit', 'quantity_cap')
}
TEXT = {'participant_id', 'offer_id', 'seller_id', 'resource_id', 'unit', 'need_id', 'buyer_id'}
SETTINGS = {'version', 'data_origin', 'days', 'initial_allocation_quanta', 'total_debt_limit_quanta',
            'max_orders', 'max_match_checks', 'notes'}


def validate(data):
    if not isinstance(data, dict) or set(data) != {'settings', *TABLES}:
        raise ValueError('Expected settings and the four documented economic tables')
    settings = data['settings']
    if not isinstance(settings, dict) or set(settings) != SETTINGS or type(settings['version']) is not int or settings['version'] != 1:
        raise ValueError('Unsupported economic input format')
    if settings['data_origin'] not in ('synthetic_example', 'field_observations', 'hypothetical'):
        raise ValueError('Declare whether data are synthetic, hypothetical or field observations')
    integer(settings['days'], 1, 180)
    integer(settings['initial_allocation_quanta'], 0, 10**9)
    integer(settings['total_debt_limit_quanta'], 1, 10**12)
    integer(settings['max_orders'], 1, 10000)
    integer(settings['max_match_checks'], 1, 1_000_000)
    if not isinstance(settings['notes'], str) or len(settings['notes']) > 2000:
        raise ValueError('Input notes must be short text, without personal information')
    for table, columns in TABLES.items():
        rows = data[table]
        maximum = 1000 if table == 'participants' else 5000
        if not isinstance(rows, list) or len(rows) > maximum:
            raise ValueError(f'{table} exceeds its bounded row count')
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(columns):
                raise ValueError(f'{table} columns differ from the documented schema')
            for name, value in row.items():
                if name in TEXT:
                    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                        raise ValueError(f'Use a short opaque identifier for {name}')
                else:
                    integer(value)
    participants = {r['participant_id']: r for r in data['participants']}
    if not 2 <= len(participants) == len(data['participants']):
        raise ValueError('At least two different participants are required')
    if 'reserve' in participants:
        raise ValueError('The reserve identifier is reserved for the simulation')
    allocation = settings['initial_allocation_quanta']
    if settings['total_debt_limit_quanta'] < len(participants)*allocation:
        raise ValueError('Collective debt limit cannot be below the initial reserve debit')
    if any(r['credit_limit_quanta'] < allocation for r in participants.values()):
        raise ValueError('Initial allocation exceeds a participant credit limit')
    for table, id_name in (('offers', 'offer_id'), ('needs', 'need_id')):
        if len({r[id_name] for r in data[table]}) != len(data[table]):
            raise ValueError(f'Duplicate {id_name}')
    days = settings['days']
    units = {}
    for row in [*data['offers'], *data['needs'], *data['resource_limits']]:
        previous = units.setdefault(row['resource_id'], row['unit'])
        if previous != row['unit']:
            raise ValueError('One resource ID must have one explicitly defined unit')
    for offer in data['offers']:
        if offer['seller_id'] not in participants or not 0 <= offer['available_day'] <= offer['expires_day'] < days:
            raise ValueError('Offer seller or availability window is invalid')
        for field in ('quantity_total', 'quantity_per_day', 'price_quanta'):
            integer(offer[field], 1, 10**9)
        for field in ('delivery_delay_days', 'payment_delay_days'):
            integer(offer[field], 0, 365)
        for field in ('delivery_success_bps', 'settlement_success_bps'):
            integer(offer[field], 0, 10000)
    for need in data['needs']:
        if need['buyer_id'] not in participants or not 0 <= need['earliest_day'] <= need['deadline_day'] < days:
            raise ValueError('Need buyer or deadline is invalid')
        integer(need['quantity'], 1, 10**9)
        integer(need['max_unit_price_quanta'], 1, 10**9)
        integer(need['priority'], 1, 5)
    limits = [(r['resource_id'], r['unit']) for r in data['resource_limits']]
    if len(limits) != len(set(limits)):
        raise ValueError('Duplicate resource budget')
    return data


def load(folder):
    folder = Path(folder)
    paths = [folder/'settings.json', *[folder/(name+'.csv') for name in TABLES]]
    if sum(path.stat().st_size for path in paths) > 2_000_000:
        raise ValueError('Economic inputs exceed the 2 MB input limit')
    settings = json.loads(paths[0].read_text(encoding='utf-8-sig'))
    data = {'settings': settings}
    fingerprints = {}
    for path in paths:
        fingerprints[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name, columns in TABLES.items():
        with (folder/(name+'.csv')).open(encoding='utf-8-sig', newline='') as file:
            reader = csv.DictReader(file)
            if reader.fieldnames != list(columns):
                raise ValueError(f'{name}.csv must use exactly these columns: '+','.join(columns))
            rows = []
            for raw in reader:
                if None in raw or any(value is None for value in raw.values()):
                    raise ValueError('CSV row has missing or extra fields')
                row = {key: value.strip() if key in TEXT else int(value) for key, value in raw.items()}
                rows.append(row)
                if len(rows) > 5000:
                    raise ValueError('CSV row limit exceeded')
            data[name] = rows
    return validate(data), fingerprints


def csv_bytes(rows, columns):
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode('utf-8')


def write(folder, data, max_bytes=1_000_000):
    validate(data)
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    storage = OutputBudget(folder, max_bytes)
    storage.write_json('settings.json', data['settings'])
    for table, columns in TABLES.items():
        storage.write_bytes(table+'.csv', csv_bytes(data[table], columns))


def field_template(folder, days, total_debt_limit):
    integer(days, 1, 180)
    integer(total_debt_limit, 1, 10**12)
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    storage = OutputBudget(folder, 1_000_000)
    settings = {'version': 1, 'data_origin': 'field_observations', 'days': days,
                'initial_allocation_quanta': 0, 'total_debt_limit_quanta': total_debt_limit,
                'max_orders': 5000, 'max_match_checks': 200000,
                'notes': 'Blank template. Populate authorized pseudonymous observations and agreed limits before simulation. Data are not verified by this program.'}
    storage.write_json('settings.json', settings)
    for table, columns in TABLES.items():
        storage.write_bytes(table+'.csv', csv_bytes([], columns))


def example(participants=30, days=30):
    integer(participants, 3, 300)
    integer(days, 7, 180)
    resources = [('repair', 'repair_30min', 300), ('produce', 'basket', 100), ('tool_share', 'tool_day', 200)]
    data = {'settings': {'version': 1, 'data_origin': 'synthetic_example', 'days': days,
                        'initial_allocation_quanta': 1000, 'total_debt_limit_quanta': participants*2000,
                        'max_orders': 5000, 'max_match_checks': 200000,
                        'notes': 'Synthetic fixed quotes, capacities and requests. No field measurements or real owner consent.'},
            **{name: [] for name in TABLES}}
    for i in range(participants):
        who = f'p{i:04d}'
        data['participants'].append({'participant_id': who, 'debt_limit_quanta': 1000, 'credit_limit_quanta': 3000})
        resource, unit, price = resources[i % 3]
        data['offers'].append({'offer_id': f'o{i:04d}', 'seller_id': who, 'resource_id': resource, 'unit': unit,
                              'quantity_total': days*2, 'quantity_per_day': 2, 'price_quanta': price,
                              'available_day': 0, 'expires_day': days-1, 'delivery_delay_days': 1,
                              'payment_delay_days': 2, 'delivery_success_bps': 10000, 'settlement_success_bps': 10000})
        for week in range(min(max(1, days//7), 5000//(2*participants))):
            for offset in (1, 2):
                resource, unit, price = resources[(i+offset) % 3]
                data['needs'].append({'need_id': f'n{i:04d}_{week}_{offset}', 'buyer_id': who,
                                     'resource_id': resource, 'unit': unit, 'quantity': 1,
                                     'max_unit_price_quanta': price*2, 'earliest_day': week*7,
                                     'deadline_day': min(days-1, week*7+5), 'priority': 3})
    for resource, unit, _ in resources:
        data['resource_limits'].append({'resource_id': resource, 'unit': unit, 'quantity_cap': participants*days})
    return validate(data)
