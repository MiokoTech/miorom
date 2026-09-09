import difflib
import struct
from typing import List, Tuple, Dict, Callable, Optional, Sequence


from miorom.errors import RelocationError
class ByteOffsetMapper:
    """
    Computes exact byte-level offset relocation between original and modified data
    using Longest Common Subsequence (LCS) alignment via difflib.SequenceMatcher.

    Guarantees 1:1 precision when recalculating internal pointers, jump targets,
    and sub-entry boundaries after text expansions or byte insertions.
    """

    def __init__(self, old_bytes: bytes, new_bytes: bytes):
        self.old_len = len(old_bytes)
        self.new_len = len(new_bytes)
        self.delta = self.new_len - self.old_len

        # Compute sequence alignment once and cache opcodes
        sm = difflib.SequenceMatcher(a=old_bytes, b=new_bytes, autojunk=False)
        self.opcodes = sm.get_opcodes()

    def map_offset(self, old_offset: int) -> int:
        """
        Maps a byte offset from old_bytes to its exact corresponding offset in new_bytes.
        """
        if old_offset < 0:
            raise RelocationError(f"Offset cannot be negative: {old_offset}")

        for tag, i1, i2, j1, j2 in self.opcodes:
            if i1 <= old_offset < i2 or (i1 == i2 == old_offset):
                if tag == "equal":
                    return j1 + (old_offset - i1)
                else:
                    return j1

        # Offset past the end of tracked opcodes
        if self.opcodes:
            last_tag, i1, i2, j1, j2 = self.opcodes[-1]
            if old_offset >= i2:
                return j2 + (old_offset - i2)

        return old_offset + self.delta

    def map_range(self, old_start: int, old_end: int) -> Tuple[int, int]:
        """
        Maps an (old_start, old_end) slice range to (new_start, new_end).
        """
        return self.map_offset(old_start), self.map_offset(old_end)

    def remap_pointers(
        self,
        old_pointers: List[int],
        base_offset: int = 0
    ) -> List[int]:
        """
        Batch-remaps a list of pointer values.
        If base_offset is given, resolves pointers relative to base.
        """
        new_pointers = []
        for ptr in old_pointers:
            rel = ptr - base_offset
            new_rel = self.map_offset(rel)
            new_pointers.append(new_rel + base_offset)
        return new_pointers

    @classmethod
    def remap_u16_in_place(
        cls,
        new_data: bytearray,
        old_data: bytes,
        pointer_positions: List[int],
        endian: str = "<",
        base: int = 0
    ) -> Dict[int, Tuple[int, int]]:
        """
        Automatically updates 16-bit pointers in new_data at given positions.
        Returns a dict mapping old_pos -> (new_pos, new_target).
        """
        mapper = cls(old_data, bytes(new_data))
        fmt = f"{endian}H"
        results = {}

        for old_pos in pointer_positions:
            if old_pos + 2 > len(old_data):
                continue
            old_target = struct.unpack_from(fmt, old_data, old_pos)[0]
            new_target = mapper.map_offset(old_target - base) + base
            new_pos = mapper.map_offset(old_pos)

            if new_pos + 2 <= len(new_data) and 0 <= new_target <= 0xFFFF:
                struct.pack_into(fmt, new_data, new_pos, new_target)
                results[old_pos] = (new_pos, new_target)

        return results

    @classmethod
    def remap_u32_in_place(
        cls,
        new_data: bytearray,
        old_data: bytes,
        pointer_positions: List[int],
        endian: str = "<",
        base: int = 0
    ) -> Dict[int, Tuple[int, int]]:
        """
        Automatically updates 32-bit pointers in new_data at given positions.
        Returns a dict mapping old_pos -> (new_pos, new_target).
        """
        mapper = cls(old_data, bytes(new_data))
        fmt = f"{endian}I"
        results = {}

        for old_pos in pointer_positions:
            if old_pos + 4 > len(old_data):
                continue
            old_target = struct.unpack_from(fmt, old_data, old_pos)[0]
            new_target = mapper.map_offset(old_target - base) + base
            new_pos = mapper.map_offset(old_pos)

            if new_pos + 4 <= len(new_data) and 0 <= new_target <= 0xFFFFFFFF:
                struct.pack_into(fmt, new_data, new_pos, new_target)
                results[old_pos] = (new_pos, new_target)

        return results

    @classmethod
    def update_footer_anchored_fields(
        cls,
        new_data: bytearray,
        old_data: bytes,
        offsets: Sequence[int],
        endian: str = "<",
        field_size: int = 2,
        unused_sentinel: Optional[int] = 0xFFFF,
    ) -> Dict[int, int]:
        """
        Updates fields anchored to the end of a variable-length data record.
        When payload size shifts by delta = len(new_data) - len(old_data), each
        active field is incremented by delta to maintain its relative distance to footer.
        """
        delta = len(new_data) - len(old_data)
        fmt = f"{endian}{'H' if field_size == 2 else 'I'}"
        max_val = 0xFFFF if field_size == 2 else 0xFFFFFFFF
        results = {}

        for off in offsets:
            if off + field_size > len(old_data):
                continue
            val = struct.unpack_from(fmt, old_data, off)[0]
            if unused_sentinel is not None and val == unused_sentinel:
                continue
            new_val = val + delta
            if not (0 <= new_val <= max_val):
                raise RelocationError(f"Value {new_val} overflows field size {field_size} at offset 0x{off:X}")
            struct.pack_into(fmt, new_data, off, new_val)
            results[off] = new_val

        return results
