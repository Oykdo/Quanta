"""Import pilot observations or generate examples; run bounded economic scenarios."""
import argparse
import json
from pathlib import Path
import statistics
import time

from economy.data import load, write, example, csv_bytes, field_template
from economy.engine import simulate, SCENARIOS
from v2.storage import OutputBudget, BudgetExceeded


def ensemble(data, seed, replications, scenario):
    if not 1 <= replications <= 50:
        raise ValueError('Choose 1 to 50 reproducible replications')
    representative, rows, complete = None, [], True
    for i in range(replications):
        result = simulate(data, seed+i, scenario)
        if representative is None:
            representative = result
        rows.append(result['metrics'])
        complete = complete and result['complete']
    metrics = {}
    for key in rows[0]:
        values = [r[key] for r in rows if type(r[key]) in (int, float)]
        if values:
            metrics[key] = {'mean': statistics.mean(values), 'min': min(values), 'max': max(values)}
    summary = {'scenario': scenario, 'replications': replications, 'seeds': list(range(seed, seed+replications)),
               'all_runs_complete': complete, 'metrics': metrics,
               'representative_statuses': representative['metrics']['order_status_counts'],
               'representative_blocking_attempts': representative['blocking_attempts']}
    return summary, representative


def run(folder, output, seed=42, replications=5, scenarios=('baseline',), details=False, max_bytes=10_000_000):
    data, fingerprints = load(folder)
    if not 1 <= max_bytes <= 1_000_000_000:
        raise ValueError('Choose an output quota up to 1 GB')
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('Use a new economic report directory')
    started = time.perf_counter()
    summaries, representative = [], None
    for scenario in scenarios:
        summary, result = ensemble(data, seed, replications, scenario)
        summaries.append(summary)
        if representative is None:
            representative = result
    report = {'format': 1, 'mode': 'offline_economic_shadow_simulation',
              'data_origin_declared': data['settings']['data_origin'], 'input_sha256': fingerprints,
              'settings': data['settings'], 'participant_count': len(data['participants']),
              'offer_count': len(data['offers']), 'need_count': len(data['needs']),
              'scenarios': summaries, 'representative_scenario': representative['scenario'],
              'representative_seed': representative['seed'],
              'representative_blocking_attempts': representative['blocking_attempts'],
              'representative_resource_results': representative['by_resource'],
              'wall_seconds': time.perf_counter()-started,
              'interpretation': representative['interpretation'],
              'field_data_verified': False, 'real_owner_consent': False, 'live_ledger_modified': False,
              'energy_joules': None,
              'scope': 'Matching and settlement under declared inputs; no verdict on worldwide viability or endogenous prices'}
    output.mkdir(parents=True, exist_ok=False)
    storage = OutputBudget(output, max_bytes)
    storage.write_json('report.json', report)
    daily = representative['daily']
    storage.write_bytes('daily.csv', csv_bytes(daily, tuple(daily[0])))
    if details:
        storage.write_json('orders.json', representative['orders'])
        storage.write_json('balances.json', representative['final_balances_quanta'])
    return {'report': str(output/'report.json'), 'data_origin_declared': report['data_origin_declared'],
            'output_bytes': storage.used_bytes(), 'max_output_bytes': max_bytes,
            'scenarios': summaries, 'live_ledger_modified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    demo = sub.add_parser('example')
    demo.add_argument('--out', type=Path, required=True)
    demo.add_argument('--participants', type=int, default=30)
    demo.add_argument('--days', type=int, default=30)
    template = sub.add_parser('template', help='Create empty field-observation CSV tables, not synthetic quotes')
    template.add_argument('--out', type=Path, required=True)
    template.add_argument('--days', type=int, default=30)
    template.add_argument('--total-debt-limit', type=int, required=True)
    for name in ('run', 'compare'):
        command = sub.add_parser(name)
        command.add_argument('--input', type=Path, required=True)
        command.add_argument('--out', type=Path, required=True)
        command.add_argument('--seed', type=int, default=42)
        command.add_argument('--replications', type=int, default=5)
        command.add_argument('--details', action='store_true', help='Local pseudonymous order/balance exports for analysis')
        command.add_argument('--max-output-bytes', type=int, default=10_000_000)
        if name == 'run':
            command.add_argument('--scenario', choices=SCENARIOS, default='baseline')
    args = parser.parse_args()
    try:
        if args.command == 'template':
            field_template(args.out, args.days, args.total_debt_limit)
            result = {'input_folder': str(args.out), 'status': 'blank_observation_template',
                      'instructions': 'Populate the tables before running; a label is not evidence of measured data'}
        elif args.command == 'example':
            data = example(args.participants, args.days)
            write(args.out, data)
            result = {'input_folder': str(args.out), 'data_origin_declared': 'synthetic_example',
                      'participants': len(data['participants']), 'needs': len(data['needs'])}
        else:
            scenarios = (args.scenario,) if args.command == 'run' else SCENARIOS
            result = run(args.input, args.out, args.seed, args.replications, scenarios, args.details, args.max_output_bytes)
        print(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False))
    except (ValueError, TypeError, KeyError, OSError, BudgetExceeded) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
