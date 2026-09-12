import io
import json
import os
import struct

from eda_proto.ids import CellId
from eda_proto.invariants import check_invariants
from eda_proto.model import Design
from eda_proto.serialize import CURRENT_VERSION, cell_from_dict, cell_to_dict

# header layout: key(4 bytes) + flag(1 byte) + payload_length(4 bytes)
HEADER = ">IBI"  # struct format: big-endian, uint32, uint8, uint32
HEADER_SIZE = 9  # struct.calcsize(HEADER)
HEADER_KEY = 0  # cell ids start at 1


def _sync(f):
    f.flush()  # userspace buffer->OS
    try:
        fd = f.fileno()
    except (io.UnsupportedOperation, AttributeError):
        return  # in-memory buffer, can only do flush
    os.fsync(fd)  # OS page cache


# ==========================================================================
# Slice 2 + 3: In-memory index + put/get/delete
# ==========================================================================
class LogStore:
    def __init__(self, f):
        self.f = f  # open binary file-like (BytesIO in test)
        self.index = {}
        self._rebuild_index()  # recover on open

    def _rebuild_index(self) -> None:
        self.f.seek(0)  # scan from start
        while True:
            offset = self.f.tell()  # capture b4 read
            try:
                rec = read_record(self.f)
            except ValueError:  # crash interrupted the append
                self.f.seek(0)
                self.f.truncate(offset)
                break
            if rec is None:  # EOF means done
                break
            key, payload, deleted = rec
            if deleted:
                self.index.pop(key, None)  # remove
            else:
                self.index[key] = offset  # exists, so set

    def sync(self):
        _sync(self.f)

    def close(self) -> None:
        self.f.close()

    def keys(self) -> list:
        return list(self.index)

    def put(self, key: int, payload: bytes) -> None:
        self.f.seek(0, 2)  # go to EOF
        offset = self.f.tell()  # capture offset before writing
        self.f.write(frame_record(key, payload))
        self.f.flush()
        self.index[key] = offset  # latest offset

    def get(self, key: int) -> bytes | None:
        offset = self.index.get(key)
        if offset is None:
            return None
        self.f.seek(offset)
        rec = read_record(self.f)
        assert rec is not None
        _, payload, _ = rec
        return payload

    def delete(self, key: int) -> None:
        if key not in self.index:
            return
        self.f.seek(0, 2)
        self.f.write(frame_record(key, b"", deleted=True))
        self.f.flush()
        del self.index[key]


def open_store(path: str) -> LogStore:
    """Opener for real files"""
    if not os.path.exists(path):
        open(path, "wb").close()  # create empty file if missing
    f = open(path, "r+b")  # read + write
    return LogStore(f)


# ==========================================================================
# Slice 1: Record framing-how a record is laid out on a disk
# ==========================================================================
def frame_record(key: int, payload: bytes, deleted: bool = False) -> bytes:
    """Turn one record into its on-dist byte form: header + payload."""
    flag: int = 0
    if deleted:
        flag = 1
    header = struct.pack(HEADER, key, flag, len(payload))
    return header + payload


def read_record(f) -> tuple[int, bytes, bool] | None:
    """Read a framed record from open file f at its current position.
    Returns (key, payload, deleted), or None at clean EOF.
    Leaves f positioned at the start of the next record.
    """
    header_bytes = f.read(HEADER_SIZE)
    if header_bytes == b"":
        return None  # clean EOF, nothing left to read
    if len(header_bytes) < HEADER_SIZE:
        raise ValueError("truncated header")  # partial header, corruption
    key, flag, length = struct.unpack(HEADER, header_bytes)
    payload = f.read(length)
    if len(payload) < length:
        raise ValueError("truncated payload")  # header promised more than existes
    return (key, payload, flag == 1)


# ==========================================================================
# Slice 4: A design recorded and read back
# ==========================================================================
def save_design(design: Design, store: LogStore) -> None:
    header = {"version": CURRENT_VERSION, "top": design.top, "next_id": design._next_id}
    store.put(HEADER_KEY, json.dumps(header, sort_keys=True).encode())
    for cell in design.library.values():
        payload = json.dumps(cell_to_dict(cell), sort_keys=True).encode()
        store.put(cell.id, payload)
    store.sync()


def load_design(store: LogStore) -> Design:
    raw = store.get(HEADER_KEY)
    if raw is None:
        raise ValueError("store has no header record; not a design store")
    header = json.loads(raw)
    if header["version"] != CURRENT_VERSION:
        raise ValueError(f"unknown header version {header['version']}")
    design = Design()
    design._next_id = header["next_id"]
    design.top = CellId(header["top"]) if header["top"] is not None else None
    for key in store.keys():
        if key == HEADER_KEY:
            continue
        raw = store.get(key)
        assert raw is not None
        cell = cell_from_dict(json.loads(raw))
        design.library[cell.id] = cell
    check_invariants(design)
    return design
