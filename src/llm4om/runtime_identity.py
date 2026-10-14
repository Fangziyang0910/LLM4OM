"""Source identity used by run, task and experiment checkpoints."""

import hashlib
from pathlib import Path


def sdk_sha256() -> str:
    digest = hashlib.sha256()
    root = Path(__file__).parent
    for path in sorted(path for path in root.rglob("*") if path.suffix in (".py", ".txt", ".json")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
