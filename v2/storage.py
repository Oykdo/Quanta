"""Budgeted session outputs, including the temporary copies used for replacement."""
import io
import json
import os
from pathlib import Path
import shutil
import tempfile


class BudgetExceeded(RuntimeError):
    pass


class OutputBudget:
    def __init__(self, root, max_bytes):
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError('A positive output budget in bytes is required')
        self.root = Path(root).resolve()
        self.max_bytes = max_bytes

    def used_bytes(self):
        return sum(path.stat().st_size for path in self.root.rglob('*') if path.is_file())

    def _path(self, relative):
        path = (self.root/relative).resolve()
        path.relative_to(self.root)
        return path

    def _check(self, extra):
        used = self.used_bytes()
        if used + extra > self.max_bytes:
            raise BudgetExceeded(f'Output budget exceeded: {used} + {extra} > {self.max_bytes} bytes')
        if extra > shutil.disk_usage(self.root).free:
            raise BudgetExceeded('Not enough free disk space for the next output')

    def write_bytes(self, relative, payload):
        path = self._path(relative)
        # Count the ENTIRE temporary file, even when replacing an existing file.
        self._check(len(payload))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
                temporary = Path(file.name)
                file.write(payload)
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def write_json(self, relative, value):
        payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        self.write_bytes(relative, payload)

    def write_checkpoint(self, relative, value):
        import torch
        buffer = io.BytesIO()
        torch.save(value, buffer)
        self.write_bytes(relative, buffer.getvalue())

    def append_log(self, message):
        payload = (message + '\n').encode('utf-8')
        self._check(len(payload))
        with self._path('training.log').open('ab') as file:
            file.write(payload)
