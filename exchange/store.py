"""Atomic single-writer local clearing, with the existing output-budget guard."""
import json
from pathlib import Path

from exchange.ledger import Ledger
from v2.storage import OutputBudget


def read_json(path, maximum=10_000_000):
    path = Path(path)
    if path.stat().st_size > maximum:
        raise ValueError('Input file exceeds the size limit')
    return json.loads(path.read_text(encoding='utf-8'))


def write_request(path, value):
    path = Path(path)
    if not path.parent.is_dir():
        raise ValueError('Output parent directory must already exist')
    if path.exists():
        raise FileExistsError('An authorization file must not be overwritten')
    # All proposal/consent files share their parent folder's small budget.
    payload = json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False).encode('utf-8')
    if len(payload) > 8192:
        raise ValueError('Authorization file is unexpectedly large')
    storage = OutputBudget(path.parent, 10_000_000)
    storage._check(len(payload))
    with path.open('xb') as file:
        file.write(payload)


class LedgerStore:
    def __init__(self, path):
        self.path = Path(path).resolve()

    @classmethod
    def create(cls, folder, **settings):
        ledger = Ledger.create(**settings)
        folder = Path(folder).resolve()
        folder.mkdir(parents=True, exist_ok=False)
        OutputBudget(folder, ledger.state['header']['policy']['max_output_bytes']).write_json('ledger.json', ledger.state)
        return cls(folder/'ledger.json')

    def load(self, required_head=None):
        ledger = Ledger(read_json(self.path, maximum=50_000_000))
        ledger.audit(required_head)
        return ledger

    def commit(self, payload, signatures, now=None, required_head=None):
        lock = self.path.with_name(self.path.name+'.lock')
        try:
            lock.mkdir()  # Exclusive directory creation serializes all local writers.
        except FileExistsError as error:
            raise ValueError('Ledger is busy or has a stale lock; no transaction was applied') from error
        try:
            ledger = self.load(required_head)
            receipt = ledger.commit(payload, signatures, now)
            budget = ledger.state['header']['policy']['max_output_bytes']
            OutputBudget(self.path.parent, budget).write_json(self.path.name, ledger.state)
            return receipt
        finally:
            lock.rmdir()
