"""Artifact storage backends — local filesystem now, S3-compatible later.

Objects are private by default; delivery happens through an authorized API
route, never a public bucket path (architecture: Artifact Storage).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from xp_core.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class StoredObject:
    key: str
    size_bytes: int
    sha256: str


class StorageBackend(Protocol):
    def save_bytes(self, key: str, data: bytes) -> StoredObject: ...
    def open_path(self, key: str) -> Path: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    """Development/local-storage backend rooted at a configurable directory."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = key.lstrip("/").replace("..", "_")
        target = (self.root / safe).resolve()
        if not str(target).startswith(str(self.root)):
            raise ValueError(f"invalid object key: {key!r}")
        return target

    def save_bytes(self, key: str, data: bytes) -> StoredObject:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write so delivery never sees a partial object.
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, target)
        digest = hashlib.sha256(data).hexdigest()
        log.info("artifact_stored", key=key, size=len(data), sha256=digest)
        return StoredObject(key=key, size_bytes=len(data), sha256=digest)

    def open_path(self, key: str) -> Path:
        return self._path(key)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        target = self._path(key)
        if target.is_file():
            target.unlink()
