"""
miorom.core.bitfield
~~~~~~~~~~~~~~~~~~~~
Sub-byte bitfield and packed record codec for retro console ROM hacking.
Enables precise packing and unpacking of arbitrary-width integer and boolean fields
across byte boundaries for save files, RPG stats, event flags, and hardware bitmasks.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from miorom.core.bits import sign_extend
from miorom.core.bitstream import BitReader, BitWriter
from miorom.result import MioRomResult


@dataclass
class BitField:
    """Specification for a single sub-byte field within a packed record."""
    name: str
    bits: int
    signed: bool = False
    default: int = 0
    description: str = ""

    def __post_init__(self):
        if self.bits <= 0:
            raise ValueError(f"BitField '{self.name}' must have positive bit length, got {self.bits}")
        if self.bits > 64:
            raise ValueError(f"BitField '{self.name}' exceeds maximum 64-bit length: {self.bits}")


class BitFieldSchema:
    """
    Schema defining the structure and bit alignment of a packed record.
    Supports MSB-first and LSB-first bit ordering.
    """

    def __init__(
        self,
        fields: Iterable[Union[BitField, Tuple[str, int], Tuple[str, int, bool]]],
        bit_order: str = "msb",
        name: str = "PackedRecord",
    ):
        self.name = name
        self.bit_order = bit_order.lower()
        if self.bit_order not in ("msb", "lsb"):
            raise ValueError(f"Unsupported bit order '{bit_order}'. Expected 'msb' or 'lsb'.")

        self.fields: List[BitField] = []
        for item in fields:
            if isinstance(item, BitField):
                self.fields.append(item)
            elif isinstance(item, tuple):
                if len(item) == 2:
                    self.fields.append(BitField(name=item[0], bits=item[1]))
                elif len(item) >= 3:
                    self.fields.append(BitField(name=item[0], bits=item[1], signed=bool(item[2])))
            else:
                raise TypeError(f"Invalid field definition: {item}")

        self._validate()

    def _validate(self) -> None:
        seen = set()
        for f in self.fields:
            if f.name in seen:
                raise ValueError(f"Duplicate field name in schema: '{f.name}'")
            seen.add(f.name)

    @property
    def total_bits(self) -> int:
        """Total bit width across all fields in the schema."""
        return sum(f.bits for f in self.fields)

    @property
    def byte_size(self) -> int:
        """Number of full bytes required to store this packed record."""
        return math.ceil(self.total_bits / 8)

    @property
    def field_names(self) -> List[str]:
        return [f.name for f in self.fields]


class BitFieldCodec:
    """
    Encoder and decoder for sub-byte packed records and bitfield tables.
    """

    def __init__(
        self,
        schema: Union[BitFieldSchema, Iterable[Union[BitField, Tuple[str, int], Tuple[str, int, bool]]]],
        bit_order: str = "msb",
    ):
        if isinstance(schema, BitFieldSchema):
            self.schema = schema
        else:
            self.schema = BitFieldSchema(schema, bit_order=bit_order)

    @property
    def byte_size(self) -> int:
        return self.schema.byte_size

    @property
    def total_bits(self) -> int:
        return self.schema.total_bits

    def unpack(
        self,
        data: Union[bytes, bytearray, memoryview],
        offset: int = 0,
        bool_flags: bool = False,
    ) -> Dict[str, Any]:
        """
        Unpacks a single packed record from data starting at byte offset.
        If bool_flags is True, 1-bit unsigned fields are converted to booleans.
        """
        record, _ = self.unpack_from(data, offset=offset, bool_flags=bool_flags)
        return record

    def unpack_from(
        self,
        data: Union[bytes, bytearray, memoryview],
        offset: int = 0,
        bool_flags: bool = False,
    ) -> Tuple[Dict[str, Any], int]:
        """
        Unpacks a single packed record and returns (record_dict, bytes_consumed).
        """
        chunk = bytes(data[offset : offset + self.schema.byte_size])
        if len(chunk) < self.schema.byte_size:
            raise ValueError(
                f"Buffer too short: need {self.schema.byte_size} bytes, got {len(chunk)} bytes at offset {offset}"
            )

        reader = BitReader(chunk, bit_order=self.schema.bit_order)
        result: Dict[str, Any] = {}

        for f in self.schema.fields:
            if f.signed:
                val = reader.read_signed_bits(f.bits)
            else:
                val = reader.read_bits(f.bits)
                if bool_flags and f.bits == 1:
                    val = bool(val)

            result[f.name] = val

        return result, self.schema.byte_size

    def unpack_all(
        self,
        data: Union[bytes, bytearray, memoryview],
        offset: int = 0,
        count: Optional[int] = None,
        bool_flags: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Unpacks a sequential table of packed records.
        """
        record_bytes = self.schema.byte_size
        if record_bytes == 0:
            return []

        available = len(data) - offset
        max_possible = available // record_bytes
        num_records = min(count, max_possible) if count is not None else max_possible

        records: List[Dict[str, Any]] = []
        cur = offset
        for _ in range(num_records):
            rec, consumed = self.unpack_from(data, offset=cur, bool_flags=bool_flags)
            records.append(rec)
            cur += consumed

        return records

    def pack(self, values: Dict[str, Any]) -> bytes:
        """
        Packs a dictionary of values into bytes according to schema.
        """
        writer = BitWriter(bit_order=self.schema.bit_order)

        for f in self.schema.fields:
            val = values.get(f.name, f.default)

            if isinstance(val, bool):
                val = 1 if val else 0

            if f.signed:
                min_val = -(1 << (f.bits - 1))
                max_val = (1 << (f.bits - 1)) - 1
                if not (min_val <= val <= max_val):
                    raise ValueError(f"Value {val} out of range for signed {f.bits}-bit field '{f.name}'")
                writer.write_signed_bits(val, f.bits)
            else:
                max_val = (1 << f.bits) - 1
                if not (0 <= val <= max_val):
                    raise ValueError(f"Value {val} out of range for unsigned {f.bits}-bit field '{f.name}'")
                writer.write_bits(val, f.bits)

        return writer.to_bytes()

    def pack_into(
        self,
        buffer: bytearray,
        offset: int,
        values: Dict[str, Any],
    ) -> None:
        """
        Packs a dictionary of values directly into a mutable bytearray buffer at offset.
        """
        packed_bytes = self.pack(values)
        if offset + len(packed_bytes) > len(buffer):
            raise ValueError(
                f"Destination buffer too small: required {offset + len(packed_bytes)}, buffer size {len(buffer)}"
            )
        buffer[offset : offset + len(packed_bytes)] = packed_bytes

    def pack_all(self, records: List[Dict[str, Any]]) -> bytes:
        """
        Packs an array of dictionaries into contiguous binary bytes.
        """
        out = bytearray()
        for rec in records:
            out.extend(self.pack(rec))
        return bytes(out)
