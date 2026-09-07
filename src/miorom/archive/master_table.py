"""
miorom.archive.master_table
~~~~~~~~~~~~~~~~~~~~~~~~~~~
General-purpose container handler for binary archives indexed by a master table.
Tracks record entry counts, preserves pristine snapshots, provides entry bounds slicing,
and performs cascading downstream offset updates upon record resizing.
"""

import struct
from typing import List, Tuple, Optional, Union, Dict, Any


class MasterTableArchive:
    """
    Generic binary container indexed by a master record/pointer table.
    Automatically manages cascading offset shifts when internal entries expand or shrink.
    """

    def __init__(
        self,
        data: Union[bytes, bytearray],
        table_entries: int,
        record_format: str = "<II",
        table_offset: int = 0,
        stride: Optional[int] = None,
    ):
        self.data = bytearray(data)
        self.table_entries = table_entries
        self.record_format = record_format
        self.table_offset = table_offset
        self.record_size = struct.calcsize(record_format) if stride is None else stride
        self.total_table_size = self.table_entries * self.record_size

        if len(self.data) < self.table_offset + self.total_table_size:
            raise ValueError(
                f"Data size {len(self.data)} too small for table size {self.total_table_size} "
                f"at offset {self.table_offset}"
            )

        self.table: List[List[Any]] = self._parse_table(self.data)
        self._pristine_data = bytes(data)
        self._pristine_table = self._parse_table(self._pristine_data)

    def _parse_table(self, buf: Union[bytes, bytearray]) -> List[List[Any]]:
        table = []
        for i in range(self.table_entries):
            off = self.table_offset + (i * self.record_size)
            fields = list(struct.unpack_from(self.record_format, buf, off))
            table.append(fields)
        return table

    def serialize_table(self) -> bytes:
        out = bytearray()
        for fields in self.table:
            out += struct.pack(self.record_format, *fields)
        return bytes(out)

    @classmethod
    def from_file(cls, path: str, **kwargs) -> "MasterTableArchive":
        with open(path, "rb") as f:
            return cls(f.read(), **kwargs)

    def save(self, path: str) -> None:
        self.commit_table()
        with open(path, "wb") as f:
            f.write(self.data)

    def to_bytes(self) -> bytes:
        self.commit_table()
        return bytes(self.data)

    def commit_table(self) -> None:
        table_bytes = self.serialize_table()
        start = self.table_offset
        self.data[start : start + len(table_bytes)] = table_bytes

    def get_slice(self, start: int, end: int) -> bytes:
        return bytes(self.data[start:end])

    def get_pristine_slice(self, start: int, end: int) -> bytes:
        return self._pristine_data[start:end]

    def replace_slice(self, start: int, end: int, new_data: bytes) -> int:
        old_size = end - start
        new_size = len(new_data)
        delta = new_size - old_size
        self.data[start:end] = new_data
        return delta

    def cascade_offset(
        self,
        from_index: int,
        delta: int,
        offset_field_idx: int = 1,
        until_index: Optional[int] = None,
    ) -> None:
        """
        Cascades an offset shift across subsequent table entries.
        """
        if delta == 0:
            return
        end_idx = until_index if until_index is not None else len(self.table)
        for i in range(from_index, end_idx):
            self.table[i][offset_field_idx] += delta

    def get_record(self, index: int) -> List[Any]:
        return self.table[index]

    def set_record(self, index: int, *fields) -> None:
        self.table[index] = list(fields)

    def get_pristine_record(self, index: int) -> List[Any]:
        return self._pristine_table[index]

    def __len__(self) -> int:
        return len(self.data)
