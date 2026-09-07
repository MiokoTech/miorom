"""
miorom.text.relative_search
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Relative text search engine for discovering unknown character tables (.tbl / CharMap).
Finds text in binary ROM dumps where characters have custom byte mappings with fixed intervals.
Supports 1-byte and 2-byte (endian-aware) relative searching and automated .tbl generation.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union
import struct

from miorom.text.charmap import CharMap


@dataclass
class RelativeMatch:
    """Represents a discovered text occurrence via relative search."""
    offset: int
    length: int
    matched_bytes: bytes
    base_delta: int
    mode: str = "1byte"  # "1byte", "2byte_be", "2byte_le"

    @property
    def offset_hex(self) -> str:
        return f"0x{self.offset:08X}"

    def build_charmap(
        self,
        include_uppercase: bool = True,
        include_lowercase: bool = True,
        include_digits: bool = True,
    ) -> CharMap:
        """
        Extrapolates a full CharMap (.tbl) from this match's base delta.
        """
        mapping: Dict[bytes, str] = {}

        def add_char(char: str):
            code = ord(char)
            if self.mode == "1byte":
                val = (code + self.base_delta) & 0xFF
                b = bytes([val])
            elif self.mode == "2byte_be":
                val = (code + self.base_delta) & 0xFFFF
                b = struct.pack(">H", val)
            else:  # 2byte_le
                val = (code + self.base_delta) & 0xFFFF
                b = struct.pack("<H", val)
            mapping[b] = char

        if include_uppercase:
            for c in range(ord("A"), ord("Z") + 1):
                add_char(chr(c))
        if include_lowercase:
            for c in range(ord("a"), ord("z") + 1):
                add_char(chr(c))
        if include_digits:
            for c in range(ord("0"), ord("9") + 1):
                add_char(chr(c))

        return CharMap(mapping)

    def to_tbl(self) -> str:
        """Exports the extrapolated table in standard Thingy .tbl format (HEX=CHAR)."""
        cm = self.build_charmap()
        lines = []
        for b, char in sorted(cm.byte_to_char.items(), key=lambda item: item[0]):
            hex_str = b.hex().upper()
            lines.append(f"{hex_str}={char}")
        return "\n".join(lines)


class RelativeSearcher:
    """
    Classic ROM hacking Relative Search Engine.
    Discovers text with unknown character encodings by matching letter-distance intervals.
    """

    @classmethod
    def search_1byte(
        cls,
        data: bytes,
        query: str,
        case_sensitive: bool = True,
        max_matches: Optional[int] = None,
    ) -> List[RelativeMatch]:
        """
        Performs 1-byte relative search on data.
        """
        if len(query) < 2:
            raise ValueError("Relative search query must have at least 2 characters.")

        matches: List[RelativeMatch] = []
        q_len = len(query)
        data_len = len(data)

        if not case_sensitive:
            # Search both original and uppercase if case insensitive
            queries = [query.upper(), query.lower()] if query.upper() != query.lower() else [query]
        else:
            queries = [query]

        for q in queries:
            ord_list = [ord(c) for c in q]
            # Deltas between consecutive characters
            deltas = [ord_list[i + 1] - ord_list[i] for i in range(q_len - 1)]

            for i in range(0, data_len - q_len + 1):
                # Check consecutive differences
                match = True
                for idx in range(q_len - 1):
                    # Check modulo 256 difference
                    diff = (data[i + idx + 1] - data[i + idx]) & 0xFF
                    expected_diff = deltas[idx] & 0xFF
                    if diff != expected_diff:
                        match = False
                        break

                if match:
                    base_delta = (data[i] - ord_list[0]) & 0xFF
                    matched_bytes = bytes(data[i : i + q_len])
                    matches.append(RelativeMatch(
                        offset=i,
                        length=q_len,
                        matched_bytes=matched_bytes,
                        base_delta=base_delta,
                        mode="1byte",
                    ))
                    if max_matches is not None and len(matches) >= max_matches:
                        return matches

        return matches

    @classmethod
    def search_2byte(
        cls,
        data: bytes,
        query: str,
        endian: str = ">",
        max_matches: Optional[int] = None,
    ) -> List[RelativeMatch]:
        """
        Performs 2-byte relative search on data (common in Japanese 16-bit text).
        """
        if len(query) < 2:
            raise ValueError("Relative search query must have at least 2 characters.")

        matches: List[RelativeMatch] = []
        q_len = len(query)
        data_len = len(data)
        mode = "2byte_be" if endian == ">" else "2byte_le"
        fmt = f"{endian}H"

        ord_list = [ord(c) for c in query]
        deltas = [ord_list[i + 1] - ord_list[i] for i in range(q_len - 1)]

        step = 2  # Aligned to 16-bit words
        for i in range(0, data_len - (q_len * 2) + 1, step):
            match = True
            first_val = struct.unpack_from(fmt, data, i)[0]
            cur_val = first_val

            for idx in range(q_len - 1):
                next_val = struct.unpack_from(fmt, data, i + (idx + 1) * 2)[0]
                diff = (next_val - cur_val) & 0xFFFF
                expected_diff = deltas[idx] & 0xFFFF
                if diff != expected_diff:
                    match = False
                    break
                cur_val = next_val

            if match:
                base_delta = (first_val - ord_list[0]) & 0xFFFF
                matched_bytes = bytes(data[i : i + q_len * 2])
                matches.append(RelativeMatch(
                    offset=i,
                    length=q_len * 2,
                    matched_bytes=matched_bytes,
                    base_delta=base_delta,
                    mode=mode,
                ))
                if max_matches is not None and len(matches) >= max_matches:
                    return matches

        return matches

    @classmethod
    def search(
        cls,
        data: bytes,
        query: str,
        mode: str = "1byte",
        endian: str = ">",
        max_matches: Optional[int] = None,
    ) -> List[RelativeMatch]:
        """
        Unified relative search interface.
        mode can be '1byte', '2byte' (or '2byte_be', '2byte_le').
        """
        if mode == "1byte":
            return cls.search_1byte(data, query, max_matches=max_matches)
        elif mode in ("2byte", "2byte_be"):
            return cls.search_2byte(data, query, endian=">", max_matches=max_matches)
        elif mode == "2byte_le":
            return cls.search_2byte(data, query, endian="<", max_matches=max_matches)
        else:
            raise ValueError(f"Unknown relative search mode: '{mode}'")
