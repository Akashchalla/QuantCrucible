"""Local configuration and atomic, private research artifacts."""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'private_data'


def now():
    return datetime.now(timezone.utc).isoformat()


def settings():
    values = {}
    file = ROOT / '.env'
    if file.exists():
        for line in file.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            name, sep, val = line.partition('=')
            if sep:
                values[name.strip()] = val.strip().strip('\"\'')
    values.update(os.environ)
    return values


def config():
    return json.loads((ROOT / 'config.json').read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def save(name, data):
    PRIVATE.mkdir(exist_ok=True, mode=0o700)
    destination = PRIVATE / name
    fd, temp = tempfile.mkstemp(dir=PRIVATE)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2, allow_nan=False)
        os.replace(temp, destination)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return destination


def read(name, default=None):
    file = PRIVATE / name
    return json.loads(file.read_text()) if file.exists() else default


def require_freeze(cfg):
    frozen = read('freeze.json')
    if not frozen or frozen['config_hash'] != digest(cfg):
        raise ValueError('Freeze the current research specification before evaluating market returns.')
    return frozen
