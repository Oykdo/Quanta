"""Reproducible network checks without local ledgers, neural assets or PyTorch."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    suite = unittest.TestSuite()
    for package in ('exchange', 'testnet', 'provenance', 'economy'):
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/package/'tests'),
                                                         top_level_dir=str(ROOT)))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
