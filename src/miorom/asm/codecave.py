from miorom.result import MioRomResult
from dataclasses import dataclass
from typing import List, Optional


from miorom.errors import RelocationError
@dataclass
class CodeCave(MioRomResult):
    offset: int
    size: int
    filler_byte: int


class CodeCaveFinder:
    """
    Scans binary ROMs and executables for unused space / padding (code caves)
    suitable for injecting custom assembly patches and trampolines.
    """

    @classmethod
    def find_caves(
        cls,
        data: bytes,
        min_size: int = 16,
        filler_byte: int = 0x00,
        alignment: int = 4,
        start_offset: int = 0,
        end_offset: Optional[int] = None,
    ) -> List[CodeCave]:
        if end_offset is None:
            end_offset = len(data)

        caves: List[CodeCave] = []
        pos = start_offset

        while pos < end_offset:
            # Align pos
            aligned_pos = (pos + alignment - 1) & ~(alignment - 1)
            if aligned_pos >= end_offset:
                break
            pos = aligned_pos

            if data[pos] == filler_byte:
                run_start = pos
                while pos < end_offset and data[pos] == filler_byte:
                    pos += 1
                run_len = pos - run_start
                if run_len >= min_size:
                    caves.append(CodeCave(offset=run_start, size=run_len, filler_byte=filler_byte))
            else:
                pos += 1

        return caves

    @classmethod
    def allocate(
        cls,
        data: bytearray,
        payload: bytes,
        filler_byte: int = 0x00,
        alignment: int = 4,
        start_offset: int = 0,
    ) -> int:
        """
        Finds the first suitable code cave and writes payload into it.
        Returns the offset where the payload was written.
        """
        caves = cls.find_caves(
            bytes(data),
            min_size=len(payload),
            filler_byte=filler_byte,
            alignment=alignment,
            start_offset=start_offset,
        )
        if not caves:
            raise RelocationError(f"No code cave of size {len(payload)} bytes found.")

        target_cave = caves[0]
        offset = target_cave.offset
        data[offset : offset + len(payload)] = payload
        return offset
