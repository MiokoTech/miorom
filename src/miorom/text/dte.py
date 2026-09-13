"""
miorom.text.dte
~~~~~~~~~~~~~~~
Dual-Tile Encoding (DTE) and Multi-Tile Encoding (MTE) Dictionary Optimizer and Transcoder.
Provides n-gram frequency analysis, net byte savings dictionary construction,
longest-match text compression/decompression, and .tbl character table export.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from miorom.result import MioRomResult
from miorom.text.charmap import CharMap


@dataclass
class DteEntry(MioRomResult):
    """Represents a single DTE/MTE token mapping with compression metrics."""
    code: int
    text: str
    occurrences: int = 0
    bytes_saved: int = 0

    @property
    def hex_code(self) -> str:
        return f"{self.code:02X}"


@dataclass
class DteStats(MioRomResult):
    """Summary metrics of a constructed DTE/MTE dictionary and corpus compression."""
    uncompressed_bytes: int
    compressed_bytes: int
    bytes_saved: int
    compression_ratio: float
    dictionary: Dict[int, str] = field(default_factory=dict)
    entries: List[DteEntry] = field(default_factory=list)


class DteOptimizer:
    """
    Analyzes text corpora to synthesize optimal DTE/MTE substitution dictionaries
    maximizing net byte reduction under hardware ROM constraints.
    """

    @classmethod
    def analyze_ngrams(
        cls,
        corpus: Union[str, Sequence[str]],
        min_len: int = 2,
        max_len: int = 4,
        exclude_bracketed_tags: bool = True,
    ) -> Dict[str, int]:
        """
        Count occurrences of all n-grams within [min_len, max_len] range across text corpus.
        Optionally ignores bracketed formatting tags (e.g. [wait], [0x12]).
        """
        if isinstance(corpus, str):
            texts = [corpus]
        else:
            texts = list(corpus)

        counts: Counter[str] = Counter()

        for text in texts:
            clean_text = text
            if exclude_bracketed_tags:
                parts = []
                in_bracket = False
                for ch in text:
                    if ch == "[":
                        in_bracket = True
                    elif ch == "]":
                        in_bracket = False
                    elif not in_bracket:
                        parts.append(ch)
                clean_text = "".join(parts)

            text_len = len(clean_text)
            for n in range(min_len, max_len + 1):
                for i in range(text_len - n + 1):
                    ngram = clean_text[i : i + n]
                    if "\n" not in ngram and "\r" not in ngram:
                        counts[ngram] += 1

        return dict(counts)

    @classmethod
    def build_dictionary(
        cls,
        corpus: Union[str, Sequence[str]],
        num_slots: int = 64,
        min_len: int = 2,
        max_len: int = 4,
        start_code: int = 0x80,
        reserved_codes: Optional[Set[int]] = None,
        exclude_bracketed_tags: bool = True,
    ) -> DteStats:
        """
        Synthesize an optimal DTE/MTE dictionary using net byte savings ranking:
        savings = (len(ngram) - 1) * frequency.
        """
        reserved = reserved_codes or set()
        available_codes: List[int] = []
        code = start_code
        while len(available_codes) < num_slots and code <= 0xFF:
            if code not in reserved:
                available_codes.append(code)
            code += 1

        if isinstance(corpus, str):
            full_text = corpus
        else:
            full_text = "\n".join(corpus)

        raw_counts = cls.analyze_ngrams(
            full_text,
            min_len=min_len,
            max_len=max_len,
            exclude_bracketed_tags=exclude_bracketed_tags,
        )

        candidates = []
        for ngram, count in raw_counts.items():
            savings = (len(ngram) - 1) * count
            if savings > 0:
                candidates.append((savings, count, ngram))

        candidates.sort(key=lambda item: (item[0], item[1], len(item[2])), reverse=True)

        selected_dict: Dict[int, str] = {}
        entries: List[DteEntry] = []
        chosen_ngrams: Set[str] = set()

        for savings, count, ngram in candidates:
            if len(selected_dict) >= len(available_codes):
                break
            if ngram in chosen_ngrams:
                continue

            assigned_code = available_codes[len(selected_dict)]
            selected_dict[assigned_code] = ngram
            chosen_ngrams.add(ngram)
            entries.append(
                DteEntry(
                    code=assigned_code,
                    text=ngram,
                    occurrences=count,
                    bytes_saved=savings,
                )
            )

        encoded_sample = DteCodec.encode(full_text, selected_dict)
        uncompressed_size = len(full_text.encode("utf-8"))
        compressed_size = len(encoded_sample)
        net_saved = max(0, uncompressed_size - compressed_size)
        ratio = (compressed_size / uncompressed_size * 100.0) if uncompressed_size > 0 else 100.0

        return DteStats(
            uncompressed_bytes=uncompressed_size,
            compressed_bytes=compressed_size,
            bytes_saved=net_saved,
            compression_ratio=ratio,
            dictionary=selected_dict,
            entries=entries,
        )

    @staticmethod
    def to_tbl(dictionary: Dict[int, str], uppercase_hex: bool = True) -> str:
        """
        Export dictionary to standard romhacking .tbl character table format lines.
        Example output: 80=th
        """
        lines = []
        for code, text in sorted(dictionary.items(), key=lambda item: item[0]):
            hex_str = f"{code:02X}" if uppercase_hex else f"{code:02x}"
            lines.append(f"{hex_str}={text}")
        return "\n".join(lines)

    @staticmethod
    def from_tbl(tbl_content: str) -> Dict[int, str]:
        """Parse DTE/MTE token definitions from a .tbl text mapping."""
        dictionary: Dict[int, str] = {}
        for raw_line in tbl_content.splitlines():
            line = raw_line.rstrip("\r\n")
            if not line or line.lstrip().startswith(("#", ";", "//")):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                try:
                    code = int(key.strip(), 16)
                    dictionary[code] = val
                except ValueError:
                    continue
        return dictionary


class DteCodec:
    """
    Two-way encoder and decoder for DTE/MTE dictionary text streams.
    """

    @classmethod
    def encode(
        cls,
        text: str,
        dictionary: Dict[int, str],
        charmap: Optional[CharMap] = None,
    ) -> bytes:
        """
        Compress text by greedily replacing matching substrings with single-byte DTE tokens.
        Characters without DTE mappings are encoded via charmap or standard ASCII.
        """
        # Invert dictionary: text -> byte code
        sorted_pairs = sorted(dictionary.items(), key=lambda item: len(item[1]), reverse=True)

        out = bytearray()
        i = 0
        text_len = len(text)

        while i < text_len:
            matched = False
            for code, target_str in sorted_pairs:
                if text.startswith(target_str, i):
                    out.append(code)
                    i += len(target_str)
                    matched = True
                    break

            if not matched:
                ch = text[i]
                if charmap and ch in charmap.char_to_byte:
                    out.extend(charmap.char_to_byte[ch])
                else:
                    out.append(ord(ch) & 0xFF)
                i += 1

        return bytes(out)

    @classmethod
    def decode(
        cls,
        data: Union[bytes, bytearray],
        dictionary: Dict[int, str],
        charmap: Optional[CharMap] = None,
    ) -> str:
        """
        Decompress a byte sequence into text using the DTE dictionary and optional charmap.
        """
        chars: List[str] = []
        i = 0
        data_len = len(data)

        # Build byte-to-char lookup from CharMap
        byte_map = charmap.byte_to_char if charmap else {}

        while i < data_len:
            byte_val = data[i]

            if byte_val in dictionary:
                chars.append(dictionary[byte_val])
                i += 1
                continue

            single_byte = bytes([byte_val])
            if single_byte in byte_map:
                chars.append(byte_map[single_byte])
                i += 1
                continue

            if 32 <= byte_val <= 126:
                chars.append(chr(byte_val))
            else:
                chars.append(f"[{byte_val:02X}]")
            i += 1

        return "".join(chars)


@dataclass
class DTEToken(MioRomResult):
    """Represents a Dual-Tile Encoding token mapping."""
    token_byte: bytes
    expansion: str
    frequency: int = 0

    @property
    def hex_str(self) -> str:
        return self.token_byte.hex().upper()


class DTEMiner:
    """
    Dual-Tile and Multi-Tile Encoding (DTE/MTE) Miner.
    Discovers dictionary tokens and compresses/decompresses text streams.
    """

    @classmethod
    def mine_character_pairs(
        cls,
        text_corpus: Union[str, List[str]],
        max_tokens: int = 128,
        min_occurrences: int = 3,
        token_start: int = 0x80,
    ) -> Dict[bytes, str]:
        """
        Analyzes a corpus of plaintext strings and selects the optimal 2-character
        pairs for DTE compression, mapping them to token bytes starting at token_start.
        """
        if isinstance(text_corpus, list):
            full_text = " ".join(text_corpus)
        else:
            full_text = text_corpus

        pair_counts: Counter[str] = Counter()
        i = 0
        while i < len(full_text) - 1:
            pair = full_text[i : i + 2]
            if "[" not in pair and "]" not in pair and "\n" not in pair:
                pair_counts[pair] += 1
            i += 1

        dte_dict: Dict[bytes, str] = {}
        cur_token = token_start

        for pair, count in pair_counts.most_common():
            if count < min_occurrences:
                break
            if cur_token > 0xFF or len(dte_dict) >= max_tokens:
                break
            dte_dict[bytes([cur_token])] = pair
            cur_token += 1

        return dte_dict

    @classmethod
    def compress_text(cls, text: str, dte_dict: Dict[bytes, str], base_charmap: Optional[CharMap] = None) -> bytes:
        """
        Compresses plaintext by greedily substituting substrings with DTE tokens.
        """
        str_to_token = {v: k for k, v in dte_dict.items()}
        sorted_pairs = sorted(str_to_token.keys(), key=len, reverse=True)

        out = bytearray()
        i = 0
        text_len = len(text)

        while i < text_len:
            matched = False
            for target_str in sorted_pairs:
                if text.startswith(target_str, i):
                    out.extend(str_to_token[target_str])
                    i += len(target_str)
                    matched = True
                    break

            if not matched:
                char = text[i]
                if base_charmap:
                    out.extend(base_charmap.encode(char))
                else:
                    out.append(ord(char) & 0xFF)
                i += 1

        return bytes(out)

    @classmethod
    def decompress_bytes(cls, data: bytes, dte_dict: Dict[bytes, str], base_charmap: Optional[CharMap] = None) -> str:
        """
        Decompresses a DTE byte buffer back to a decoded string.
        """
        chars: List[str] = []
        i = 0
        data_len = len(data)

        while i < data_len:
            b = bytes([data[i]])
            if b in dte_dict:
                chars.append(dte_dict[b])
                i += 1
            else:
                if base_charmap and b in base_charmap.byte_to_char:
                    chars.append(base_charmap.byte_to_char[b])
                else:
                    val = data[i]
                    if 32 <= val <= 126:
                        chars.append(chr(val))
                    else:
                        chars.append(f"[{val:02X}]")
                i += 1

        return "".join(chars)

    @classmethod
    def create_dte_charmap(cls, base_charmap: CharMap, dte_dict: Dict[bytes, str]) -> CharMap:
        """
        Constructs an integrated CharMap containing both base characters and multi-character DTE tokens.
        """
        merged_mappings: Dict[bytes, str] = dict(base_charmap.byte_to_char)
        merged_mappings.update(dte_dict)
        return CharMap(merged_mappings)

