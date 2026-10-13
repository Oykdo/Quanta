"""Run network checks in a disposable copy of ONLY public repository sources."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from testnet.source import public_files


def main():
    top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout.strip()
    if Path(top).resolve() != ROOT.resolve():
        raise ValueError('Git must be rooted in the project, not the user directory')
    candidates = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                                cwd=ROOT, check=True, capture_output=True).stdout.decode('utf-8').split('\0')
    allowed = {p.relative_to(ROOT).as_posix(): p for p in public_files()}
    names = [name for name in candidates if name]
    if len(names) != len(set(names)) or set(names) != set(allowed):
        raise ValueError('Git selection differs from the explicit public source list: '+
                         ', '.join(sorted(set(names)^set(allowed))))
    temporary_parent = os.environ.get('QUANTA_CHECK_TEMP')
    with tempfile.TemporaryDirectory(prefix='quanta_public_', dir=temporary_parent) as tmp:
        out = Path(tmp)
        for name in names:
            target = out/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(allowed[name], target)
        env = os.environ.copy()
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        result = subprocess.run([sys.executable, '-B', 'scripts/check.py'], cwd=out, env=env)
        print(f'Public source-only copy: {len(names)} files; tests exit={result.returncode}')
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
