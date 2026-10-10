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


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _mkdir(path: Path, *, mode: int = 0o777, exist_ok: bool = True) -> None:
    if not path.parent.exists():
        _mkdir(path.parent)
    path.mkdir(mode=mode, exist_ok=exist_ok)
    # An existing entry may be left by an interrupted creation before its fsync.
    _sync_directory(path.parent)


def _atomic(path: Path, content: bytes) -> None:
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        _sync_directory(path.parent)
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
            _mkdir(self.path, exist_ok=False)
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
        self.interrupted_publications: dict[str, list[dict[str, Any]]] = {}
        self.state: dict[str, Any] = {}
        self.cancellation = cancellation or CancellationToken()
        self._checkpoint_hash: str | None = None
        self._pending: dict[str, list[dict[str, Any]]] = {}
        self.identity = {'schema_version': '0.1.0', 'run_id': self.run_id,
                         'owner_uid': os.getuid(), 'owner_id': uuid4().hex}
        try:
            if resume:
                checkpoint_bytes = read_public_bytes(self.path / 'checkpoint.json')
                self._checkpoint_hash = hashlib.sha256(checkpoint_bytes).hexdigest()
                envelope = parse_json(checkpoint_bytes)
                if read_public_bytes(self.path / 'checkpoints' / (self._checkpoint_hash + '.json')) != checkpoint_bytes:
                    raise ValueError('Immutable checkpoint changed.')
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
                pending_path = self.path / 'publication.json'
                pending = parse_json(read_public_bytes(pending_path)) if pending_path.exists() else {}
                control = parse_json(read_public_bytes(self.path / 'control.json'))
                interrupted = (control.get('active') is True and control.get('run_id') == self.run_id
                               and control.get('owner_uid') == os.getuid()
                               and pending.get('checkpoint_sha256') == self._checkpoint_hash
                               and pending.get('owner_id') == control.get('owner_id'))
                versions = payload.get('interrupted_publications', {})
                if interrupted:
                    for name, records in pending.get('projections', {}).items():
                        versions.setdefault(name, []).extend(ref for ref in records if ref not in versions.get(name, []))
                for name, records in versions.items():
                    public_path(self.path, name, require_file=False)
                    for ref in records:
                        if ref['relative_path'] != 'history/' + ref['sha256'] + '/' + name:
                            raise ValueError('Uncommitted reference identity changed.')
                        raw = read_public_bytes(public_path(self.path, ref['relative_path']))
                        if len(raw) != ref['size_bytes'] or hashlib.sha256(raw).hexdigest() != ref['sha256']:
                            raise ValueError('Uncommitted immutable bytes changed.')
                repairs = []
                for name, ref in self.projections.items():
                    raw = read_public_bytes(public_path(self.path, name))
                    if hashlib.sha256(raw).hexdigest() != ref['sha256']:
                        if not any(hashlib.sha256(raw).hexdigest() == item['sha256'] for item in versions.get(name, [])):
                            raise ValueError('Public projection changed.')
                        repairs.append((name, ref))
                for name, records in versions.items():
                    if name not in self.projections:
                        path = public_path(self.path, name, require_file=False)
                        if path.exists():
                            raw = read_public_bytes(path)
                            if not any(hashlib.sha256(raw).hexdigest() == item['sha256'] for item in records):
                                raise ValueError('Uncommitted public bytes changed.')
                if [event['sequence_no'] for event in self.events] != list(range(1, len(self.events) + 1)):
                    raise ValueError('Event sequence mismatch.')
                self.interrupted_publications = versions
                if interrupted:
                    for records in versions.values():
                        self.refs.extend(ref for ref in records if ref not in self.refs)
                    # Commit the verified receipt before repairing views or changing owner.
                    self.checkpoint()
                for name, ref in repairs:
                    _atomic(public_path(self.path, name), read_public_bytes(public_path(self.path, ref['relative_path'])))
                for name in versions:
                    if name not in self.projections:
                        public_path(self.path, name, require_file=False).unlink(missing_ok=True)
                pending_path.unlink(missing_ok=True)
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
                    _atomic(self.path / 'control.json', _bytes({**self.identity, 'active': bool(self._pending)}))
        finally:
            os.close(self._lock)

    def checkpoint(self) -> None:
        payload = {'run_id': self.run_id, 'refs': self.refs, 'events': self.events, 'state': self.state,
                   'projections': self.projections, 'interrupted_publications': self.interrupted_publications}
        raw = _bytes({'schema_version': '0.1.0',
                      'sha256': hashlib.sha256(_bytes(payload)).hexdigest(), 'payload': payload})
        versions = self.path / 'checkpoints'
        _mkdir(versions)
        immutable = versions / (hashlib.sha256(raw).hexdigest() + '.json')
        if immutable.exists():
            if read_public_bytes(immutable) != raw:
                raise RunError('checkpoint_incompatible', 'storage', 'Immutable checkpoint bytes changed.')
        else:
            _atomic(immutable, raw)
        _atomic(self.path / 'checkpoint.json', raw)
        self._checkpoint_hash = hashlib.sha256(raw).hexdigest()
        self._pending = {}
        (self.path / 'publication.json').unlink(missing_ok=True)

    def accept_publications(self) -> None:
        """Republish verified interrupted records selected by the application."""
        for name, records in self.interrupted_publications.items():
            ref = records[-1]
            self.write(name, read_public_bytes(public_path(self.path, ref['relative_path'])),
                       ref['artifact_id'], ref['schema_version'])
        self.interrupted_publications = {}

    def write(self, name: str, content: bytes, artifact_id: str,
              schema_version: str | None = None) -> dict[str, Any]:
        projection = self.path / name
        projection_name = name
        if self.versioned:
            name = 'history/' + hashlib.sha256(content).hexdigest() + '/' + name
        destination = self.path / name
        _mkdir(destination.parent)
        if not destination.exists():
            _atomic(destination, content)
        elif read_public_bytes(destination) != content:
            raise RunError('checkpoint_incompatible', 'storage', 'Immutable artifact bytes changed.')
        _mkdir(projection.parent)
        ref = {'artifact_id': artifact_id,
            'media_type': {'.json': 'application/json', '.csv': 'text/csv', '.md': 'text/markdown',
                           '.jsonl': 'application/x-ndjson', '.html': 'text/html', '.txt': 'text/plain'}.get(destination.suffix, 'application/octet-stream'),
            'sha256': hashlib.sha256(content).hexdigest(), 'size_bytes': len(content),
            'namespace': 'run_public', 'relative_path': name, 'schema_version': schema_version}
        if self.versioned:
            self._pending.setdefault(projection_name, []).append(ref)
            _atomic(self.path / 'publication.json', _bytes({
                'checkpoint_sha256': self._checkpoint_hash, 'owner_id': self.identity['owner_id'],
                'projections': self._pending}))
        _atomic(projection, content)
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
