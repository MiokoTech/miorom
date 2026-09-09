from miorom.result import MioRomResult
import string
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from miorom.text.charmap import CharMap


@dataclass
class MinedCharMapResult(MioRomResult):
    charmap: CharMap
    confidence: float
    mapped_count: int
    text_preview: str
    sample_matches: Dict[int, str] = field(default_factory=dict)


class CharMapMiner:
    """
    Statistical CharMap & Text Matrix Miner.
    Auto-reconstructs unknown proprietary character encoding tables (.tbl / CharMap)
    using frequency analysis and n-gram natural language distribution matching.
    """

    # English frequency ranking: space, E, T, A, O, I, N, S, H, R, D, L, C, U, M, W, F, G, Y, P, B, V, K, J, X, Q, Z
    ENGLISH_FREQ_ORDER = " etaoihnrsdlcumwfgypbvkjxqz"

    @classmethod
    def mine_1byte_charmap(
        cls,
        data: bytes,
        min_cluster_len: int = 16,
        confidence_threshold: float = 0.6,
        language: str = "english",
    ) -> MinedCharMapResult:
        """
        Analyze a candidate text block and reconstruct a 1-byte character table.
        """
        if not data:
            return MinedCharMapResult(CharMap(), 0.0, 0, "")

        counts = Counter(data)
        # Exclude null and common control delimiters
        filtered_counts = {k: v for k, v in counts.items() if k not in (0x00, 0xFF, 0x0A, 0x0D)}

        if len(filtered_counts) < 5:
            return MinedCharMapResult(CharMap(), 0.0, 0, "")

        sorted_bytes = [b for b, c in sorted(filtered_counts.items(), key=lambda x: x[1], reverse=True)]

        # Score candidate offsets based on English text character distribution
        best_offset = None
        best_score = -float("inf")

        for offset in range(-128, 128):
            score = 0.0
            for b in data:
                val = b - offset
                if val == 0x20:
                    score += 3.0  # space is very common
                elif 0x61 <= val <= 0x7A:  # a-z
                    score += 2.0
                elif 0x41 <= val <= 0x5A:  # A-Z
                    score += 1.5
                elif 0x30 <= val <= 0x39:  # 0-9
                    score += 1.0
                elif val in (ord("."), ord(","), ord("!"), ord("?"), ord("'"), ord('"')):
                    score += 1.0
                elif 0x20 <= val <= 0x7E:
                    score += 0.2
                else:
                    score -= 5.0  # non-printable penalty

            if score > best_score:
                best_score = score
                best_offset = offset

        table_dict: Dict[bytes, str] = {}
        target_alphabet = cls.ENGLISH_FREQ_ORDER

        # If best_score is positive and high confidence
        min_expected_score = len(data) * 1.0
        if best_offset is not None and best_score >= min_expected_score:
            # Shifted ASCII mapping detected!
            confidence = min(0.99, max(0.5, best_score / (len(data) * 2.2)))
            for b in range(256):
                val = b - best_offset
                if 0x20 <= val <= 0x7E:
                    table_dict[bytes([b])] = chr(val)
        else:
            # Frequency rank alignment
            confidence = 0.65
            limit = min(len(sorted_bytes), len(target_alphabet))
            for i in range(limit):
                table_dict[bytes([sorted_bytes[i]])] = target_alphabet[i]

        cm = CharMap(table_dict)

        # Generate preview
        preview_chars = []
        for b in data[:64]:
            byte_key = bytes([b])
            if byte_key in table_dict:
                preview_chars.append(table_dict[byte_key])
            elif b == 0:
                preview_chars.append("\n")
            else:
                preview_chars.append(f"[{b:02X}]")

        sample_matches = {k[0]: v for k, v in list(table_dict.items())[:10]}

        return MinedCharMapResult(
            charmap=cm,
            confidence=confidence,
            mapped_count=len(table_dict),
            text_preview="".join(preview_chars).strip(),
            sample_matches=sample_matches,
        )

    @classmethod
    def solve_ngram_frequencies(
        cls,
        data: bytes,
        min_occurrences: int = 3,
    ) -> Dict[bytes, str]:
        """
        Solves unknown substitution ciphers by calculating bigram frequencies
        and aligning against standard linguistic distributions (TH, HE, IN, ER, AN).
        """
        bigrams: Counter[bytes] = Counter()
        for i in range(len(data) - 1):
            pair = data[i : i + 2]
            if pair[0] != 0 and pair[1] != 0:
                bigrams[pair] += 1

        common_target_bigrams = ["th", "he", "in", "er", "an", "re", "ed", "on", "es", "st"]
        frequent_rom_bigrams = [bg for bg, cnt in bigrams.most_common(len(common_target_bigrams)) if cnt >= min_occurrences]

        table: Dict[bytes, str] = {}
        for rom_bg, tgt_bg in zip(frequent_rom_bigrams, common_target_bigrams):
            if bytes([rom_bg[0]]) not in table:
                table[bytes([rom_bg[0]])] = tgt_bg[0]
            if bytes([rom_bg[1]]) not in table:
                table[bytes([rom_bg[1]])] = tgt_bg[1]

        return table
