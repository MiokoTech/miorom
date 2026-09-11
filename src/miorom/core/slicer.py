from typing import Generator, List, Optional, Tuple, Union


def align_up(val: int, alignment: int) -> int:
    """Returns the smallest multiple of alignment greater than or equal to val."""
    if alignment <= 0:
        raise ValueError(f"Alignment must be positive, got {alignment}")
    return ((val + alignment - 1) // alignment) * alignment


def align_down(val: int, alignment: int) -> int:
    """Returns the largest multiple of alignment less than or equal to val."""
    if alignment <= 0:
        raise ValueError(f"Alignment must be positive, got {alignment}")
    return (val // alignment) * alignment


def pad_bytes(data: bytes, alignment: int, pad_byte: int = 0x00) -> bytes:
    """Pads a byte sequence to a multiple of alignment with the specified pad byte."""
    target_len = align_up(len(data), alignment)
    padding_needed = target_len - len(data)
    if padding_needed == 0:
        return data
    return data + bytes([pad_byte & 0xFF]) * padding_needed


def chunk_bytes(
    data: Union[bytes, bytearray, memoryview], chunk_size: int
) -> Generator[Union[bytes, bytearray, memoryview], None, None]:
    """Yields consecutive slices of chunk_size from data."""
    if chunk_size <= 0:
        raise ValueError(f"Chunk size must be positive, got {chunk_size}")
    total = len(data)
    for i in range(0, total, chunk_size):
        yield data[i : min(i + chunk_size, total)]


def find_free_blocks(
    data: Union[bytes, bytearray, memoryview],
    fill_byte: int = 0x00,
    min_size: int = 16,
    alignment: int = 1,
) -> List[Tuple[int, int]]:
    """
    Scans a binary buffer for contiguous sequences of fill_byte of at least min_size.
    Returns a list of (offset, length) tuples, optionally adjusted to alignment boundaries.
    """
    if min_size <= 0:
        raise ValueError("min_size must be positive")
    if alignment <= 0:
        raise ValueError("alignment must be positive")

    target_byte = fill_byte & 0xFF
    blocks: List[Tuple[int, int]] = []
    total_len = len(data)
    idx = 0

    while idx < total_len:
        if data[idx] == target_byte:
            start = idx
            while idx < total_len and data[idx] == target_byte:
                idx += 1
            length = idx - start

            if alignment > 1:
                aligned_start = align_up(start, alignment)
                shift = aligned_start - start
                aligned_length = length - shift
                if aligned_length >= min_size:
                    blocks.append((aligned_start, aligned_length))
            elif length >= min_size:
                blocks.append((start, length))
        else:
            idx += 1

    return blocks


class BinarySlicer:
    """
    Zero-copy binary buffer navigator and pattern finder over byte collections.
    """

    def __init__(self, data: Union[bytes, bytearray, memoryview]):
        self._view = memoryview(data)

    def __len__(self) -> int:
        return len(self._view)

    def slice(self, start: int, length: int) -> memoryview:
        """Returns a zero-copy memoryview slice."""
        if start < 0 or start + length > len(self._view):
            raise IndexError(f"Slice range [{start}:{start + length}] out of bounds (len {len(self._view)})")
        return self._view[start : start + length]

    def chunks(self, chunk_size: int) -> Generator[memoryview, None, None]:
        """Yields zero-copy chunks of specified size."""
        for chunk in chunk_bytes(self._view, chunk_size):
            yield chunk

    def find(self, pattern: bytes, start: int = 0, end: Optional[int] = None) -> int:
        """Locates the first occurrence of pattern within the buffer."""
        raw = bytes(self._view[start:end]) if end is not None else bytes(self._view[start:])
        idx = raw.find(pattern)
        if idx == -1:
            return -1
        return start + idx

    def find_all(self, pattern: bytes, start: int = 0, end: Optional[int] = None) -> List[int]:
        """Locates all occurrences of pattern within the buffer."""
        matches = []
        cur = start
        limit = len(self._view) if end is None else min(end, len(self._view))
        pat_len = len(pattern)

        if pat_len == 0:
            return matches

        while cur <= limit - pat_len:
            pos = self.find(pattern, cur, limit)
            if pos == -1:
                break
            matches.append(pos)
            cur = pos + 1

        return matches

    def replace_slice(self, offset: int, replacement: bytes) -> bytes:
        """Returns a new bytes buffer with the slice at offset replaced."""
        if offset < 0 or offset + len(replacement) > len(self._view):
            raise IndexError(f"Replacement at offset {offset} (len {len(replacement)}) exceeds buffer size {len(self._view)}")
        ba = bytearray(self._view)
        ba[offset : offset + len(replacement)] = replacement
        return bytes(ba)
