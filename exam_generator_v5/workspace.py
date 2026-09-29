"""SessionWorkspaceManager: heavy artefacts (Word/PDF/ZIP exports, previews) live in a private temporary directory per
session; st.session_state keeps only ids/paths/metadata. Thread-safe, collision-free, cleaned up at session end/exit."""
from __future__ import annotations

import atexit
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

_ROOT = Path(tempfile.gettempdir()) / "exam_generator_ws"
_LOCK = threading.Lock()
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
MAX_AGE_S = 12 * 3600


class SessionWorkspaceManager:
    def __init__(self, session_id: str | None = None, root: Path | None = None) -> None:
        self.session_id = _SAFE.sub("_", session_id or uuid.uuid4().hex)[:64]
        self.root = Path(root or _ROOT) / self.session_id
        with _LOCK:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _ACTIVE[self.session_id] = self

    def _path(self, key: str) -> Path:
        name = _SAFE.sub("_", key)[:120] or "item"          # no path traversal: names are flattened
        p = (self.root / name).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("invalid workspace key")
        return p

    def store(self, key: str, data: bytes) -> str:
        p = self._path(key)
        tmp = p.with_suffix(p.suffix + f".{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)                                    # atomic commit
        return str(p)

    def get(self, key: str) -> bytes | None:
        p = self._path(key)
        return p.read_bytes() if p.exists() else None

    def has(self, key: str) -> bool:
        return self._path(key).exists()

    def invalidate(self, prefix: str = "") -> None:
        pre = _SAFE.sub("_", prefix)
        for p in self.root.glob("*"):
            if p.name.startswith(pre):
                p.unlink(missing_ok=True)

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        _ACTIVE.pop(self.session_id, None)


_ACTIVE: dict[str, SessionWorkspaceManager] = {}


def cleanup_stale(max_age_s: float = MAX_AGE_S, root: Path | None = None) -> int:
    """Remove orphaned session directories older than max_age_s (never the active ones)."""
    base = Path(root or _ROOT)
    removed = 0
    if not base.exists():
        return 0
    for d in base.iterdir():
        if d.is_dir() and d.name not in _ACTIVE and time.time() - d.stat().st_mtime > max_age_s:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    return removed


@atexit.register
def _cleanup_all() -> None:
    for ws in list(_ACTIVE.values()):
        ws.cleanup()
