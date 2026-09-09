from miorom.result import MioRomResult
import struct
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Union, Any

from miorom.core.mapper import ByteOffsetMapper


from miorom.errors import RelocationError

@dataclass
class RegisteredPointer(MioRomResult):
    pristine_pos: int
    size: int = 4  # 2 or 4 bytes
    endian: str = "<"
    base_offset: int = 0


@dataclass
class AnchoredField(MioRomResult):
    pristine_pos: int
    size: int = 2  # 2 or 4 bytes
    endian: str = "<"
    anchor_type: str = "size_delta"  # "size_delta" or "footer"
    k_constant: int = 0  # for footer-anchored: field = entry_size - K
    sentinel: Optional[int] = 0xFFFF


class RelocatableBuffer:
    """
    A mutable binary buffer that maintains an immutable pristine snapshot
    of original ROM/entry data. Automatically recalculates all internal pointers
    and dynamic size fields across multiple edits without accumulation errors.
    """

    def __init__(self, data: Union[bytes, bytearray]):
        self._pristine_data = bytes(data)
        self._data = bytearray(data)
        self.registered_pointers: List[RegisteredPointer] = []
        self.anchored_fields: List[AnchoredField] = []

    @classmethod
    def load(cls, filepath: str) -> "RelocatableBuffer":
        with open(filepath, "rb") as f:
            return cls(f.read())

    def save(self, filepath: str) -> None:
        with open(filepath, "wb") as f:
            f.write(self.to_bytes())

    def to_bytes(self) -> bytes:
        return bytes(self._data)

    @property
    def pristine_data(self) -> bytes:
        return self._pristine_data

    @property
    def current_data(self) -> bytearray:
        return self._data

    @property
    def current_size(self) -> int:
        return len(self._data)

    @property
    def pristine_size(self) -> int:
        return len(self._pristine_data)

    @property
    def delta(self) -> int:
        return len(self._data) - len(self._pristine_data)

    def get_mapper(self) -> ByteOffsetMapper:
        """Computes current LCS alignment from pristine to current data."""
        return ByteOffsetMapper(self._pristine_data, bytes(self._data))

    def register_pointer(
        self,
        pos: int,
        size: int = 4,
        endian: str = "<",
        base_offset: int = 0
    ) -> None:
        """Registers a pointer field at pristine offset pos."""
        self.registered_pointers.append(
            RegisteredPointer(pos, size=size, endian=endian, base_offset=base_offset)
        )

    def register_anchored_field(
        self,
        pos: int,
        size: int = 2,
        endian: str = "<",
        anchor_type: str = "size_delta",
        k_constant: int = 0,
        sentinel: Optional[int] = 0xFFFF
    ) -> None:
        """Registers a header field that tracks file size changes."""
        self.anchored_fields.append(
            AnchoredField(
                pristine_pos=pos,
                size=size,
                endian=endian,
                anchor_type=anchor_type,
                k_constant=k_constant,
                sentinel=sentinel
            )
        )

    def replace_bytes(self, start: int, end: int, new_bytes: bytes) -> int:
        """
        Replaces slice [start:end] in current data with new_bytes.
        Returns the size delta (new_len - old_len).
        """
        old_len = end - start
        new_len = len(new_bytes)
        self._data[start:end] = new_bytes
        return new_len - old_len

    def replace_text(
        self,
        old_text: Union[str, bytes],
        new_text: Union[str, bytes],
        encoding: str = "utf-8",
        occurrence: int = 0
    ) -> Tuple[int, int]:
        """
        Safely replaces text in the buffer with ambiguity detection.
        Returns (replaced_offset, delta).
        """
        old_b = old_text.encode(encoding) if isinstance(old_text, str) else old_text
        new_b = new_text.encode(encoding) if isinstance(new_text, str) else new_text

        # Find all occurrences
        matches = []
        pos = 0
        while True:
            idx = self._data.find(old_b, pos)
            if idx == -1:
                break
            matches.append(idx)
            pos = idx + len(old_b)

        if not matches:
            raise RelocationError(f"Target text {old_text!r} not found in buffer.")

        if occurrence >= len(matches):
            raise IndexError(
                f"Occurrence index {occurrence} out of range (found {len(matches)} match(es))."
            )

        target_pos = matches[occurrence]
        delta = self.replace_bytes(target_pos, target_pos + len(old_b), new_b)
        return target_pos, delta

    def relocate_all(self) -> Dict[str, Any]:
        """
        Relocates all registered pointers and anchored fields in one diff pass.
        Returns a dictionary summary of updated fields.
        """
        mapper = self.get_mapper()
        report = {
            "delta": self.delta,
            "pointers_updated": 0,
            "fields_updated": 0,
            "details": []
        }

        # 1. Relocate registered pointers
        for ptr in self.registered_pointers:
            fmt = f"{ptr.endian}{'H' if ptr.size == 2 else 'I'}"
            old_pos = ptr.pristine_pos

            if old_pos + ptr.size > len(self._pristine_data):
                continue

            old_target = struct.unpack_from(fmt, self._pristine_data, old_pos)[0]
            new_target = mapper.map_offset(old_target - ptr.base_offset) + ptr.base_offset
            new_pos = mapper.map_offset(old_pos)

            max_val = 0xFFFF if ptr.size == 2 else 0xFFFFFFFF
            if new_pos + ptr.size <= len(self._data) and 0 <= new_target <= max_val:
                struct.pack_into(fmt, self._data, new_pos, new_target)
                report["pointers_updated"] += 1
                report["details"].append(
                    f"Pointer at 0x{old_pos:X}->0x{new_pos:X}: 0x{old_target:X}->0x{new_target:X}"
                )

        # 2. Update anchored fields
        for field in self.anchored_fields:
            fmt = f"{field.endian}{'H' if field.size == 2 else 'I'}"
            old_pos = field.pristine_pos

            if old_pos + field.size > len(self._pristine_data):
                continue

            old_val = struct.unpack_from(fmt, self._pristine_data, old_pos)[0]
            if field.sentinel is not None and old_val == field.sentinel:
                continue

            new_pos = mapper.map_offset(old_pos)
            if field.anchor_type == "size_delta":
                new_val = old_val + self.delta
            elif field.anchor_type == "footer":
                new_val = len(self._data) - field.k_constant
            else:
                new_val = old_val + self.delta

            max_val = 0xFFFF if field.size == 2 else 0xFFFFFFFF
            if new_pos + field.size <= len(self._data) and 0 <= new_val <= max_val:
                struct.pack_into(fmt, self._data, new_pos, new_val)
                report["fields_updated"] += 1
                report["details"].append(
                    f"Anchored field at 0x{old_pos:X}->0x{new_pos:X}: 0x{old_val:X}->0x{new_val:X}"
                )

        return report
