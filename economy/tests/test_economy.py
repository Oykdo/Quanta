import copy
import json
from pathlib import Path
import tempfile
import unittest

from economy.data import validate, write, load, example, field_template
from economy.engine import simulate
from economy.__main__ import run
from provenance.record import ROOT


def pilot():
    return {'settings': {'version': 1, 'data_origin': 'hypothetical', 'days': 7,
                        'initial_allocation_quanta': 0, 'total_debt_limit_quanta': 1000,
                        'max_orders': 100, 'max_match_checks': 1000, 'notes': 'Test-only observations'},
            'participants': [{'participant_id': p, 'debt_limit_quanta': 1000, 'credit_limit_quanta': 3000} for p in ('buyer', 'seller')],
            'offers': [{'offer_id': 'offer', 'seller_id': 'seller', 'resource_id': 'repair', 'unit': 'job',
                        'quantity_total': 1, 'quantity_per_day': 1, 'price_quanta': 40,
                        'available_day': 0, 'expires_day': 6, 'delivery_delay_days': 2,
                        'payment_delay_days': 2, 'delivery_success_bps': 10000, 'settlement_success_bps': 10000}],
            'needs': [{'need_id': 'need', 'buyer_id': 'buyer', 'resource_id': 'repair', 'unit': 'job',
                       'quantity': 1, 'max_unit_price_quanta': 50, 'earliest_day': 0, 'deadline_day': 5, 'priority': 3}],
            'resource_limits': [{'resource_id': 'repair', 'unit': 'job', 'quantity_cap': 1}]}


class EconomicTests(unittest.TestCase):
    def test_delivery_and_settlement_are_distinct_and_balanced(self):
        result = simulate(pilot())
        self.assertEqual(result['daily'][0]['gross_credit_quanta'], 0)
        self.assertEqual(result['daily'][0]['outstanding_obligations_quanta'], 40)
        self.assertEqual(result['daily'][2]['gross_credit_quanta'], 0)
        self.assertEqual(result['daily'][4]['gross_credit_quanta'], 40)
        self.assertEqual(result['final_balances_quanta']['buyer'], -40)
        self.assertEqual(result['final_balances_quanta']['seller'], 40)
        self.assertTrue(all(day['balance_sum'] == 0 for day in result['daily']))
        self.assertEqual(result['orders'][0]['status'], 'settled')

    def test_unpaid_income_cannot_be_spent_and_pending_debits_cannot_be_reused(self):
        data = pilot()
        data['participants'][0]['debt_limit_quanta'] = 50
        data['offers'][0].update(quantity_total=2, quantity_per_day=2)
        data['needs'][0]['quantity'] = 2
        data['resource_limits'][0]['quantity_cap'] = 2
        result = simulate(data)
        self.assertEqual(result['metrics']['orders_accepted'], 1)
        self.assertEqual(result['final_balances_quanta']['buyer'], -40)
        self.assertGreater(result['blocking_attempts']['buyer_liquidity'], 0)
        self.assertLessEqual(result['metrics']['reserved_debt_exposure_peak_quanta'], 50)

    def test_default_keeps_unpaid_liability_instead_of_creating_fake_settlement(self):
        data = pilot()
        data['offers'][0]['settlement_success_bps'] = 0
        result = simulate(data)
        self.assertEqual(result['metrics']['mean_need_fulfillment_ratio'], 1)
        self.assertEqual(result['metrics']['defaulted_unpaid_value_quanta'], 40)
        self.assertEqual(result['metrics']['settled_value_quanta'], 0)
        self.assertEqual(result['final_balances_quanta']['buyer'], 0)
        self.assertEqual(result['daily'][-1]['outstanding_obligations_quanta'], 40)

    def test_delivery_failure_releases_financial_lock_but_not_committed_capacity(self):
        data = pilot()
        data['offers'][0]['delivery_success_bps'] = 0
        result = simulate(data)
        self.assertEqual(result['metrics']['mean_need_fulfillment_ratio'], 0)
        self.assertEqual(result['daily'][-1]['outstanding_obligations_quanta'], 0)
        self.assertEqual(result['by_resource'][0]['capacity_committed_quantity'], 1)
        self.assertEqual(result['orders'][0]['status'], 'delivery_failed')

    def test_collective_limit_and_physical_budget_independently_block_orders(self):
        data = pilot()
        data['settings']['total_debt_limit_quanta'] = 10
        result = simulate(data)
        self.assertEqual(result['metrics']['orders_accepted'], 0)
        self.assertGreater(result['blocking_attempts']['collective_debt_limit'], 0)
        data = pilot()
        data['resource_limits'][0]['quantity_cap'] = 0
        result = simulate(data)
        self.assertEqual(result['metrics']['orders_accepted'], 0)
        self.assertGreater(result['blocking_attempts']['resource_budget'], 0)

    def test_future_payment_is_pending_not_default(self):
        data = pilot()
        data['offers'][0]['payment_delay_days'] = 20
        result = simulate(data)
        self.assertEqual(result['metrics']['future_settlement_value_quanta'], 40)
        self.assertEqual(result['metrics']['defaulted_unpaid_value_quanta'], 0)

    def test_seed_is_reproducible_and_input_not_modified(self):
        data = example(9, 14)
        original = copy.deepcopy(data)
        first, second = simulate(data, 42), simulate(data, 42)
        self.assertEqual(first, second)
        self.assertEqual(data, original)
        self.assertFalse(first['live_ledger_modified'])
        self.assertFalse(first['real_owner_consent'])

    def test_severe_shortage_cannot_deliver_more_than_available_capacity(self):
        data = example(9, 14)
        result = simulate(data, scenario='severe_shortage')
        self.assertLess(result['metrics']['mean_need_fulfillment_ratio'], 1)
        for resource in result['by_resource']:
            capacity = sum(offer['quantity_total']//10 for offer in data['offers']
                           if offer['resource_id'] == resource['resource_id'])
            self.assertLessEqual(resource['delivered_quantity'], capacity)

    def test_csv_roundtrip_validation_and_bounded_report(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'economy') as tmp:
            source, output = Path(tmp)/'input', Path(tmp)/'report'
            data = pilot()
            write(source, data)
            loaded, hashes = load(source)
            self.assertEqual(loaded, data)
            self.assertEqual(len(hashes), 5)
            result = run(source, output, replications=2)
            self.assertLess(result['output_bytes'], 1000000)
            report = json.loads((output/'report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['data_origin_declared'], 'hypothetical')
            self.assertFalse(report['field_data_verified'])
            self.assertFalse((output/'balances.json').exists())
            with self.assertRaises(FileExistsError):
                run(source, output)
            bad = copy.deepcopy(data)
            bad['offers'][0]['price_quanta'] = True
            with self.assertRaises(ValueError):
                validate(bad)
            bad = copy.deepcopy(data)
            bad['needs'][0]['unit'] = 'another_unit'
            with self.assertRaises(ValueError):
                validate(bad)

    def test_empty_field_template_is_not_mistaken_for_a_completed_pilot(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'economy') as tmp:
            source = Path(tmp)/'observations'
            field_template(source, 30, 50000)
            self.assertEqual(len((source/'offers.csv').read_text(encoding='utf-8').splitlines()), 1)
            with self.assertRaisesRegex(ValueError, 'two different participants'):
                load(source)
