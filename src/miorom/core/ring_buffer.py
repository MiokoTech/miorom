from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Union


class RingBuffer:
    """
    Circular sliding window byte buffer for LZ compression and streaming decoders.
    Supports wrap-around indexing and overlapping RLE-style match copies.
    """

    def __init__(self, capacity: int = 4096, fill_byte: int = 0x00):
        if capacity <= 0:
            raise ValueError(f"Capacity must be positive, got {capacity}")
        self.capacity = capacity
        self.buffer = bytearray([fill_byte & 0xFF] * capacity)
        self.head = 0
        self.total_written = 0

    def write_byte(self, byte_val: int) -> None:
        """Writes a single byte at the current head position and advances head."""
        self.buffer[self.head] = byte_val & 0xFF
        self.head = (self.head + 1) % self.capacity
        self.total_written += 1

    def write_bytes(self, data: Union[bytes, bytearray, memoryview]) -> None:
        """Writes a sequence of bytes sequentially into the circular buffer."""
        for b in data:
            self.write_byte(b)

    def read_byte_at(self, pos: int) -> int:
        """Reads a byte at an absolute circular buffer index."""
        return self.buffer[pos % self.capacity]

    def read_relative(self, distance_back: int) -> int:
        """Reads a byte distance_back positions behind the current head."""
        if distance_back <= 0 or distance_back > self.capacity:
            raise ValueError(f"distance_back must be in 1..{self.capacity}, got {distance_back}")
        idx = (self.head - distance_back) % self.capacity
        return self.buffer[idx]

    def copy_lz_match(self, distance_back: int, length: int) -> bytes:
        """
        Copies length bytes starting distance_back behind head into current position.
        Advances head and handles overlapping runs where length exceeds distance_back.
        Returns the copied bytes.
        """
        if distance_back <= 0 or distance_back > self.capacity:
            raise ValueError(f"distance_back must be in 1..{self.capacity}, got {distance_back}")
        if length <= 0:
            raise ValueError(f"Match length must be positive, got {length}")

        read_pos = (self.head - distance_back) % self.capacity
        copied = bytearray(length)

        for i in range(length):
            b = self.buffer[read_pos]
            copied[i] = b
            self.write_byte(b)
            read_pos = (read_pos + 1) % self.capacity

        return bytes(copied)

    def to_bytes(self) -> bytes:
        """Returns the full internal circular buffer as bytes."""
        return bytes(self.buffer)

    def get_chronological_window(self) -> bytes:
        """Returns buffer content ordered from oldest written byte to newest."""
        if self.total_written < self.capacity:
            return bytes(self.buffer[: self.head])
        return bytes(self.buffer[self.head :] + self.buffer[: self.head])


class LzssMatchFinder:
    """
    Hash-chained sliding window longest-match finder for LZ77/LZSS compression engines.
    """

    def __init__(
        self,
        window_size: int = 4096,
        min_match: int = 3,
        max_match: int = 18,
    ):
        if window_size <= 0:
            raise ValueError(f"window_size must be positive, got {window_size}")
        if min_match <= 0:
            raise ValueError(f"min_match must be positive, got {min_match}")
        if max_match < min_match:
            raise ValueError(f"max_match ({max_match}) cannot be less than min_match ({min_match})")

        self.window_size = window_size
        self.min_match = min_match
        self.max_match = max_match
        self._hash_table: Dict[int, List[int]] = defaultdict(list)

    def _hash_prefix(self, data: bytes, pos: int) -> Optional[int]:
        if pos + 2 > len(data):
            return None
        return (data[pos] << 8) | data[pos + 1]

    def register_position(self, data: bytes, pos: int) -> None:
        """Registers position into the sliding window prefix hash table."""
        key = self._hash_prefix(data, pos)
        if key is not None:
            self._hash_table[key].append(pos)

    def find_longest_match(
        self,
        data: bytes,
        pos: int,
        max_lookahead: Optional[int] = None,
    ) -> Tuple[int, int]:
        """
        Finds the longest match in the preceding sliding window.
        Returns (distance_back, length). If no match >= min_match, returns (0, 0).
        """
        lookahead = self.max_match if max_lookahead is None else min(self.max_match, max_lookahead)
        available_lookahead = min(lookahead, len(data) - pos)
        if available_lookahead < self.min_match:
            return 0, 0

        key = self._hash_prefix(data, pos)
        if key is None or key not in self._hash_table:
            return 0, 0

        window_start = max(0, pos - self.window_size)
        candidates = self._hash_table[key]

        # Prune old candidates outside sliding window
        valid_idx = 0
        while valid_idx < len(candidates) and candidates[valid_idx] < window_start:
            valid_idx += 1
        if valid_idx > 0:
            self._hash_table[key] = candidates[valid_idx:]
            candidates = self._hash_table[key]

        best_distance = 0
        best_length = 0

        for cand_pos in reversed(candidates):
            if cand_pos >= pos:
                continue

            match_len = 0
            while (
                match_len < available_lookahead
                and data[cand_pos + match_len] == data[pos + match_len]
            ):
                match_len += 1

            if match_len > best_length:
                best_length = match_len
                best_distance = pos - cand_pos
                if best_length == available_lookahead:
                    break

        if best_length >= self.min_match:
            return best_distance, best_length
        return 0, 0
