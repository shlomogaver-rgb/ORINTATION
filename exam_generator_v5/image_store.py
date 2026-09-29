"""Versioned, provenance-tracked image storage (files on disk, ids in session_state).

ORIGINAL_MASTER  = EXIF-corrected, full resolution, never downsampled, stored once.
WORKING          = derived editing/preview/API image (<= MAX_IMAGE_SIDE), what the editor shows.
MASTER_EDITED    = the SAME edit chain (normalized crop, erase masks, rotations) replayed on the master;
                   ROI crops for diagram recognition / OCR / CV are taken from it, never from an upscaled preview.
Undo switches the current version id (no full-image copies kept in RAM)."""
from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

PREPROCESS_VERSION = "preprocess/2.0"
HISTORY_LIMIT = 20
_LOCK = threading.Lock()
_RAM: "OrderedDict[str, bytes]" = OrderedDict()      # tiny read cache (bounded), files are the source of truth
_RAM_MAX = 12


class ImageStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes) -> str:
        h = hashlib.sha256(data).hexdigest()
        p = self.root / h
        if not p.exists():
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(p)
        return h

    def get(self, h: str) -> bytes:
        key = f"{self.root}/{h}"
        with _LOCK:
            if key in _RAM:
                _RAM.move_to_end(key)
                return _RAM[key]
        data = (self.root / h).read_bytes()
        with _LOCK:
            _RAM[key] = data
            while len(_RAM) > _RAM_MAX:
                _RAM.popitem(last=False)
        return data


def _ops_hash(ops: list | None) -> str:
    return hashlib.sha256(json.dumps(ops, sort_keys=True).encode()).hexdigest()[:16] if ops is not None else "unknown"


class _History:
    """Read-only view of previous versions (bytes on demand)."""

    def __init__(self, item: "ImageItem") -> None:
        self._item = item

    def __len__(self) -> int:
        return len(dict.__getitem__(self._item, "hist"))

    def __bool__(self) -> bool:
        return len(self) > 0

    def __getitem__(self, i: int) -> bytes:
        return self._item.store.get(dict.__getitem__(self._item, "hist")[i][0])

    def __iter__(self):
        return (self[i] for i in range(len(self)))


class ImageItem(dict):
    """dict-compatible editor item: item["current"] / item["original"] / item["history"] read from the store."""

    def __init__(self, store_root: str, master: bytes, working: bytes, item_id: str) -> None:
        store = ImageStore(store_root)
        super().__init__(id=item_id, store_root=str(store_root), master_id=store.put(master), orig_id=store.put(working),
                         cur_id="", cur_ops=[], hist=[])
        dict.__setitem__(self, "cur_id", dict.__getitem__(self, "orig_id"))

    @property
    def store(self) -> ImageStore:
        return ImageStore(dict.__getitem__(self, "store_root"))

    def __getitem__(self, k: str) -> Any:
        if k == "current":
            return self.store.get(dict.__getitem__(self, "cur_id"))
        if k == "original":
            return self.store.get(dict.__getitem__(self, "orig_id"))
        if k == "master":
            return self.store.get(dict.__getitem__(self, "master_id"))
        if k == "history":
            return _History(self)
        return dict.__getitem__(self, k)

    def __setitem__(self, k: str, v: Any) -> None:
        if k == "current":                      # a raw replacement without a recorded operation
            self.push(v, None)
            return
        dict.__setitem__(self, k, v)

    # ---- versioning
    def push(self, new_bytes: bytes, op: dict | None) -> None:
        hist = list(dict.__getitem__(self, "hist"))
        hist.append([dict.__getitem__(self, "cur_id"), dict.__getitem__(self, "cur_ops")])
        dict.__setitem__(self, "hist", hist[-HISTORY_LIMIT:])
        ops = dict.__getitem__(self, "cur_ops")
        if op is not None and op.get("type") == "reset":
            new_ops: list | None = []
        elif op is None or ops is None:
            new_ops = None                      # unknown chain -> master replay unavailable (reported, never guessed)
        else:
            new_ops = list(ops) + [op]
        dict.__setitem__(self, "cur_id", self.store.put(new_bytes))
        dict.__setitem__(self, "cur_ops", new_ops)

    def undo(self) -> bool:
        hist = list(dict.__getitem__(self, "hist"))
        if not hist:
            return False
        cur, ops = hist.pop()
        dict.__setitem__(self, "hist", hist)
        dict.__setitem__(self, "cur_id", cur)
        dict.__setitem__(self, "cur_ops", ops)
        return True

    def reset(self) -> None:
        self.push(self["original"], {"type": "reset"})

    def put_blob(self, data: bytes) -> str:
        return self.store.put(data)

    # ---- master replay
    def master_current(self) -> bytes | None:
        """Full-resolution edited asset = the edit chain replayed on ORIGINAL_MASTER (cached by chain hash)."""
        import exam_core as core

        ops = dict.__getitem__(self, "cur_ops")
        if ops is None:
            return None
        if not ops:
            return self["master"]
        key = "master_edit_" + dict.__getitem__(self, "master_id")[:16] + "_" + _ops_hash(ops)
        p = self.store.root / key
        if p.exists():
            return p.read_bytes()
        data = self["master"]
        for op in ops:
            data = core.apply_master_op(data, op, self.store)
        p.write_bytes(data)
        return data

    def provenance(self) -> dict:
        import exam_core as core

        master_edit = self.master_current()
        return {"master_hash": dict.__getitem__(self, "master_id"), "working_hash": core.image_digest(self["current"]),
                "master_edited_hash": core.image_digest(master_edit) if master_edit else "",
                "ops_hash": _ops_hash(dict.__getitem__(self, "cur_ops")), "ops": dict.__getitem__(self, "cur_ops"),
                "preprocessing_version": PREPROCESS_VERSION,
                "master_available": master_edit is not None}
