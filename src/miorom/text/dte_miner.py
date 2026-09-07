"""
miorom.text.dte_miner
~~~~~~~~~~~~~~~~~~~~~
Dual-Tile Encoding (DTE) and Multi-Tile Encoding (MTE) Dictionary Miner and Transcoder.
Identifies high-frequency character pairs and dictionary tokens in retro game ROMs,
enables dictionary compression to fit expanded text into constrained memory, and
expands DTE tables into standard CharMap encodings.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

from miorom.text.charmap import CharMap


@dataclass
class DTEToken:
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
            # Exclude control formatting tags like [XX]
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
        # Invert dte_dict: string -> token_byte
        str_to_token = {v: k for k, v in dte_dict.items()}
        # Sort by length descending for greedy matching
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
