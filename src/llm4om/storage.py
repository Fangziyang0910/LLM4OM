"""Persist immutable public references and atomic, validated run checkpoints."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterator
from contextlib import contextmanager
from uuid import uuid4

from llm4om.contracts import RunError, parse_json, public_path, read_public_bytes
from llm4om.control import CancellationToken


def _atomic(path: Path, content: bytes) -> None:
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _control_lock(path: Path) -> Iterator[None]:
    descriptor = os.open(path / 'control.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def _bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


class RunStore:
    def __init__(self, root: Path, *, resume: Path | None = None,
                 cancellation: CancellationToken | None = None, versioned: bool = True) -> None:
        if resume is not None and resume.is_symlink():
            raise RunError('control_incompatible', 'storage', 'Run directory must not be a symlink.')
        self.run_id = resume.name if resume else uuid4().hex
        self.path = resume.resolve() if resume else root.resolve() / self.run_id
        if resume is None:
            self.path.mkdir(parents=True, exist_ok=False)
        if self.path.is_symlink() or not self.path.is_dir() or self.path.stat().st_uid != os.getuid():
            raise RunError('control_incompatible', 'storage', 'Run directory has a different owner.')
        self.versioned = versioned
        self._lock = os.open(self.path / 'owner.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self._lock)
            raise RunError('run_busy', 'storage', 'This run already has an active writer.') from None
        self.refs: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.projections: dict[str, dict[str, Any]] = {}
        self.state: dict[str, Any] = {}
        self.cancellation = cancellation or CancellationToken()
        self.identity = {'schema_version': '0.1.0', 'run_id': self.run_id,
                         'owner_uid': os.getuid(), 'owner_id': uuid4().hex}
        try:
            if resume:
                envelope = parse_json(read_public_bytes(self.path / 'checkpoint.json'))
                payload = envelope['payload']
                if (envelope['schema_version'] != '0.1.0' or envelope['sha256'] != hashlib.sha256(_bytes(payload)).hexdigest()
                        or payload['run_id'] != self.run_id):
                    raise ValueError('Checkpoint identity/hash mismatch.')
                for ref in payload['refs']:
                    raw = read_public_bytes(public_path(self.path, ref['relative_path']))
                    if len(raw) != ref['size_bytes'] or hashlib.sha256(raw).hexdigest() != ref['sha256']:
                        raise ValueError('Public bytes changed.')
                self.refs, self.events, self.state = payload['refs'], payload['events'], payload['state']
                self.projections = payload['projections']
                for name, ref in self.projections.items():
                    raw = read_public_bytes(public_path(self.path, name))
                    if hashlib.sha256(raw).hexdigest() != ref['sha256']:
                        raise ValueError('Public projection changed.')
                if [event['sequence_no'] for event in self.events] != list(range(1, len(self.events) + 1)):
                    raise ValueError('Event sequence mismatch.')
            if not versioned:
                return
            with _control_lock(self.path):
                self.cancellation.bind(self.path / 'cancel-request.json', self.identity)
                (self.path / 'cancel-request.json').unlink(missing_ok=True)
                _atomic(self.path / 'control.json', _bytes({**self.identity, 'active': True}))
        except (OSError, RunError, ValueError, KeyError, TypeError) as error:
            os.close(self._lock)
            raise RunError('checkpoint_incompatible', 'storage', 'Cannot verify the persisted checkpoint and public bytes.') from error

    def close(self) -> None:
        try:
            if self.versioned:
                with _control_lock(self.path):
                    _atomic(self.path / 'control.json', _bytes({**self.identity, 'active': False}))
        finally:
            os.close(self._lock)

    def checkpoint(self) -> None:
        payload = {'run_id': self.run_id, 'refs': self.refs, 'events': self.events, 'state': self.state, 'projections': self.projections}
        _atomic(self.path / 'checkpoint.json', _bytes({'schema_version': '0.1.0',
                'sha256': hashlib.sha256(_bytes(payload)).hexdigest(), 'payload': payload}))

    def write(self, name: str, content: bytes, artifact_id: str,
              schema_version: str | None = None) -> dict[str, Any]:
        projection = self.path / name
        projection_name = name
        if self.versioned:
            name = 'history/' + hashlib.sha256(content).hexdigest() + '/' + name
        destination = self.path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            _atomic(destination, content)
        projection.parent.mkdir(parents=True, exist_ok=True)
        _atomic(projection, content)
        ref = {'artifact_id': artifact_id,
            'media_type': {'.json': 'application/json', '.csv': 'text/csv', '.md': 'text/markdown',
                           '.jsonl': 'application/x-ndjson'}.get(destination.suffix, 'application/octet-stream'),
            'sha256': hashlib.sha256(content).hexdigest(), 'size_bytes': len(content),
            'namespace': 'run_public', 'relative_path': name, 'schema_version': schema_version}
        self.refs = [item for item in self.refs if item['relative_path'] != name] + [ref]
        self.projections[projection_name] = ref
        return ref

    def json(self, name: str, value: dict[str, Any], artifact_id: str) -> dict[str, Any]:
        return self.write(name, _bytes(value), artifact_id, value.get('schema_version'))

    def emit(self, kind: str, **fields: Any) -> None:
        self.events.append({'sequence_no': len(self.events) + 1, 'kind': kind, **fields})
        raw = ''.join(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n' for event in self.events).encode()
        self.write('events.jsonl', raw, 'events')
        if self.state:
            self.checkpoint()


def cancel_run(run: Path) -> str:
    """Request cooperative cancellation of a verified run owner, never signal a PID."""
    path = run.resolve()
    if path.stat().st_uid != os.getuid():
        raise RunError('control_incompatible', 'control', 'Run directory belongs to a different owner.')
    with _control_lock(path):
        control = parse_json(read_public_bytes(path / 'control.json'))
        if (control.get('schema_version') != '0.1.0' or control.get('run_id') != path.name
                or control.get('owner_uid') != os.getuid() or not isinstance(control.get('owner_id'), str)):
            raise RunError('control_incompatible', 'control', 'Run control identity is invalid.')
        if not control.get('active'):
            return 'inactive'
        descriptor = os.open(path / 'owner.lock', os.O_RDWR | os.O_NOFOLLOW)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                control.pop('active')
                _atomic(path / 'cancel-request.json', _bytes(control))
                return 'cancellation_requested'
            return 'inactive'
        finally:
            os.close(descriptor)
