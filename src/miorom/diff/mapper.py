"""
miorom.diff.mapper
~~~~~~~~~~~~~~~~~~
Cross-Region Binary Diffing & Offset Correlator.
Matches functions, text tables, and binary blocks between different regional versions
(e.g. Japanese vs. USA releases) to automate localization mapping.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class MatchedBlock:
    offset_a: int
    offset_b: int
    length: int
    delta: int  # offset_b - offset_a

    @property
    def is_shifted(self) -> bool:
        return self.delta != 0


class BinaryDiffMapper:
    """
    Correlates addresses and structures between two binaries (e.g. Japanese vs USA).

    Example:
        mapper = BinaryDiffMapper(bin_jap, bin_usa)
        matches = mapper.find_matching_blocks(chunk_size=64)
        usa_offset = mapper.correlate_offset(0x80041000)
    """

    def __init__(self, data_a: bytes, data_b: bytes):
        self.data_a = data_a
        self.data_b = data_b
        self.matches: List[MatchedBlock] = []

    def find_matching_blocks(self, chunk_size: int = 32, stride: int = 16) -> List[MatchedBlock]:
        """Find matching contiguous chunks between data_a and data_b."""
        matches: List[MatchedBlock] = []
        lut_b: Dict[bytes, List[int]] = {}

        # Index data_b
        for j in range(0, len(self.data_b) - chunk_size, stride):
            chunk = self.data_b[j:j + chunk_size]
            if chunk == b"\x00" * chunk_size:
                continue  # Ignore pure null padding
            lut_b.setdefault(chunk, []).append(j)

        # Scan data_a
        for i in range(0, len(self.data_a) - chunk_size, stride):
            chunk = self.data_a[i:i + chunk_size]
            if chunk in lut_b:
                for j in lut_b[chunk]:
                    delta = j - i
                    matches.append(MatchedBlock(offset_a=i, offset_b=j, length=chunk_size, delta=delta))

        self.matches = matches
        return matches

    def correlate_offset(self, offset_a: int) -> Optional[int]:
        """
        Estimate the corresponding offset in data_b for an offset in data_a
        based on the closest matched block.
        """
        if not self.matches:
            self.find_matching_blocks()

        if not self.matches:
            return None

        # Find closest match before or at offset_a
        closest = min(self.matches, key=lambda m: abs(m.offset_a - offset_a))
        return offset_a + closest.delta
