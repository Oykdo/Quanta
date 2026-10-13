"""Create a small venv sharing existing dependencies, without pip or downloads."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
MAX_ENV_BYTES = 64*1024*1024


def bytes_used(folder):
    return sum(p.stat().st_size for p in Path(folder).rglob('*') if p.is_file())


def setup(folder):
    if sys.version_info[:2] != (3, 12):
        raise ValueError('Use the existing Python 3.12 interpreter as BasePython')
    import cryptography
    if cryptography.__version__ != '49.0.0':
        raise ValueError('BasePython must already provide cryptography 49.0.0; this script downloads nothing')
    folder = Path(folder).resolve()
    folder.relative_to(ROOT)
    if not folder.parent.is_dir():
        raise ValueError('The environment parent directory must already exist')
    marker = folder/'quanta-lite.json'
    if folder.exists():
        if not marker.is_file() or json.loads(marker.read_text(encoding='utf-8')).get('kind') != 'quanta-lite-venv-v1':
            raise ValueError('Existing environment is not a Quanta lite environment; nothing was overwritten')
    else:
        if shutil.disk_usage(folder.parent).free < 10*1024*1024:
            raise ValueError('At least 10 MiB free space is needed for the small environment')
        venv.EnvBuilder(with_pip=False, system_site_packages=True).create(folder)
    executable = folder/('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    probe = subprocess.run([str(executable), '-B', '-c',
        "import sys,cryptography; assert sys.version_info[:2]==(3,12); assert cryptography.__version__=='49.0.0'; print(sys.executable)"],
        capture_output=True, text=True, check=True)
    used = bytes_used(folder)
    if used > MAX_ENV_BYTES:
        raise ValueError('Environment exceeds 64 MiB; no packages will be installed automatically')
    result = {'kind': 'quanta-lite-venv-v1', 'python': str(executable), 'base_python': sys.executable,
              'environment_bytes_before_marker': used, 'max_environment_bytes': MAX_ENV_BYTES,
              'system_site_packages': True, 'pip_bootstrapped': False, 'dependency_downloads': 0}
    if not marker.exists():
        marker.write_text(json.dumps(result, indent=2), encoding='utf-8')
    result['environment_bytes'] = bytes_used(folder)
    print(json.dumps(result, indent=2))
    print('Validated interpreter:', probe.stdout.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'.venv-lite')
    args = parser.parse_args()
    try:
        setup(args.out)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
