"""
miorom.patch.slack
~~~~~~~~~~~~~~~~~~
Slack space manager and non-destructive binary allocator.
Locates unused padding blocks (0x00, 0xFF, or custom fill) within binary files
and provides safe alignment-aware allocation and end-of-file growth.
Prevents DMA corruption and downstream shifting when injecting expanded assets.
"""

from miorom.result import MioRomResult
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union


@dataclass
class SlackBlock(MioRomResult):
    """Represents an unallocated contiguous region of padding bytes."""
    offset: int
    size: int
    filler_byte: int

    @property
    def end(self) -> int:
        return self.offset + self.size

    @property
    def offset_hex(self) -> str:
        return f"0x{self.offset:08X}"

    def __repr__(self) -> str:
        return f"<SlackBlock offset=0x{self.offset:06X} size={self.size} filler=0x{self.filler_byte:02X}>"


class SlackSpaceManager:
    """
    Scans and manages slack space (padding/caves) in binary ROMs and containers.
    Allocates blocks without shifting downstream assets.
    """

    def __init__(
        self,
        buffer: bytearray,
        filler_bytes: Tuple[int, ...] = (0x00, 0xFF),
        min_slack_size: int = 16,
    ):
        self.buffer = buffer
        self.filler_bytes = filler_bytes
        self.min_slack_size = min_slack_size
        self.slack_blocks = self.scan_slack()

    def scan_slack(self) -> List[SlackBlock]:
        """Scans the buffer for all contiguous runs of filler bytes >= min_slack_size."""
        blocks: List[SlackBlock] = []
        buf = self.buffer
        length = len(buf)
        i = 0

        while i < length:
            b = buf[i]
            if b in self.filler_bytes:
                start = i
                while i < length and buf[i] == b:
                    i += 1
                run_len = i - start
                if run_len >= self.min_slack_size:
                    blocks.append(SlackBlock(offset=start, size=run_len, filler_byte=b))
            else:
                i += 1

        return blocks

    def allocate(
        self,
        size: int,
        alignment: int = 4,
        allow_eof_growth: bool = True,
        preferred_filler: Optional[int] = None,
    ) -> int:
        """
        Allocates a block of `size` bytes with the specified alignment.
        Searches internal slack blocks first. If none fits, appends to EOF if allow_eof_growth is True.
        Returns the allocated offset.
        """
        # Try finding fitting internal slack block
        for idx, block in enumerate(self.slack_blocks):
            if preferred_filler is not None and block.filler_byte != preferred_filler:
                continue

            # Calculate aligned start within block
            rem = block.offset % alignment
            aligned_start = block.offset if rem == 0 else block.offset + (alignment - rem)
            usable_size = block.end - aligned_start

            if usable_size >= size:
                # Carve allocation from block
                alloc_offset = aligned_start
                # Update or split block
                before_len = aligned_start - block.offset
                after_len = usable_size - size
                after_start = alloc_offset + size

                new_blocks = []
                if before_len >= self.min_slack_size:
                    new_blocks.append(SlackBlock(block.offset, before_len, block.filler_byte))
                if after_len >= self.min_slack_size:
                    new_blocks.append(SlackBlock(after_start, after_len, block.filler_byte))

                # Replace current block in list
                self.slack_blocks.pop(idx)
                for nb in reversed(new_blocks):
                    self.slack_blocks.insert(idx, nb)

                return alloc_offset

        if not allow_eof_growth:
            raise MemoryError(f"No internal slack space of size {size} (alignment={alignment}) found.")

        # Allocate at EOF
        cur_len = len(self.buffer)
        rem = cur_len % alignment
        pad = (alignment - rem) % alignment if alignment > 1 else 0
        if pad > 0:
            self.buffer.extend(b"\x00" * pad)

        alloc_offset = len(self.buffer)
        self.buffer.extend(b"\x00" * size)

        # Pad after allocation to preserve alignment for future appends
        rem_after = len(self.buffer) % alignment
        pad_after = (alignment - rem_after) % alignment if alignment > 1 else 0
        if pad_after > 0:
            self.buffer.extend(b"\x00" * pad_after)

        return alloc_offset

    def inject_payload(
        self,
        payload: bytes,
        alignment: int = 4,
        allow_eof_growth: bool = True,
    ) -> int:
        """
        Allocates space and writes payload bytes into the buffer.
        Returns the offset where the payload was written.
        """
        offset = self.allocate(len(payload), alignment=alignment, allow_eof_growth=allow_eof_growth)
        self.buffer[offset : offset + len(payload)] = payload
        return offset


class FarMemoryHeap:
    """
    Dedicated memory allocator for expanded ROM regions (e.g. 32MB -> 64MB far memory).
    Allocates sequential chunks above a base offset with strict boundary and alignment tracking.
    """

    def __init__(
        self,
        buffer: bytearray,
        base_offset: int,
        max_size: Optional[int] = None,
        alignment: int = 16,
    ):
        self.buffer = buffer
        self.base_offset = base_offset
        self.current_offset = base_offset
        self.max_size = max_size or len(buffer)
        self.alignment = alignment
        self.allocated_blocks: List[Tuple[int, int]] = []

    def allocate(self, size: int, alignment: Optional[int] = None) -> int:
        align = alignment or self.alignment
        rem = self.current_offset % align
        if rem != 0:
            self.current_offset += (align - rem)

        alloc_offset = self.current_offset
        end_offset = alloc_offset + size

        if end_offset > self.max_size:
            raise MemoryError(
                f"FarMemoryHeap exhausted: cannot allocate {size} bytes at 0x{alloc_offset:08X} "
                f"(limit: 0x{self.max_size:08X})"
            )

        # Grow buffer if needed
        if end_offset > len(self.buffer):
            self.buffer.extend(b"\x00" * (end_offset - len(self.buffer)))

        self.current_offset = end_offset
        self.allocated_blocks.append((alloc_offset, size))
        return alloc_offset

    def write(self, payload: bytes, alignment: Optional[int] = None) -> int:
        """Allocate and write payload directly into far memory."""
        offset = self.allocate(len(payload), alignment=alignment)
        self.buffer[offset : offset + len(payload)] = payload
        return offset

    @property
    def total_allocated_bytes(self) -> int:
        return sum(sz for _, sz in self.allocated_blocks)
