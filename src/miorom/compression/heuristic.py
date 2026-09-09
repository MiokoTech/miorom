from miorom.result import MioRomResult
import math
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class LZSSConfig(MioRomResult):
    """Parameters defining an LZSS / LZ77 compression variant."""
    window_size: int = 4096
    distance_bits: int = 12
    length_bits: int = 4
    length_bias: int = 3
    distance_bias: int = 1
    flag_msb_first: bool = True
    flag_literal_bit: int = 1  # 1 = flag bit 1 means literal; 0 = flag bit 0 means literal
    layout: str = "dist_high"  # "dist_high": token = (dist << len_bits) | len; "dist_low": (len << dist_bits) | dist
    initial_buffer_fill: int = 0x00


def decompress_lzss(
    data: bytes,
    config: LZSSConfig,
    max_output: int = 10 * 1024 * 1024,
) -> bytes:
    """
    Decompress arbitrary LZSS stream according to parameter specifications.
    """
    out = bytearray()
    in_pos = 0
    in_len = len(data)

    flags = 0
    flag_mask = 0

    dist_mask = (1 << config.distance_bits) - 1
    len_mask = (1 << config.length_bits) - 1

    while in_pos < in_len and len(out) < max_output:
        # Read flag byte when bits run out
        if flag_mask == 0:
            if in_pos >= in_len:
                break
            flags = data[in_pos]
            in_pos += 1
            flag_mask = 0x80 if config.flag_msb_first else 0x01

        # Extract current bit
        bit = 1 if (flags & flag_mask) else 0
        if config.flag_msb_first:
            flag_mask >>= 1
        else:
            flag_mask = (flag_mask << 1) & 0xFF

        is_literal = (bit == config.flag_literal_bit)

        if is_literal:
            if in_pos >= in_len:
                break
            out.append(data[in_pos])
            in_pos += 1
        else:
            if in_pos + 1 >= in_len:
                break
            b1 = data[in_pos]
            b2 = data[in_pos + 1]
            in_pos += 2
            token = (b1 << 8) | b2

            if config.layout == "dist_high":
                dist = (token >> config.length_bits) & dist_mask
                length = (token & len_mask) + config.length_bias
            else:
                dist = token & dist_mask
                length = ((token >> config.distance_bits) & len_mask) + config.length_bias

            dist += config.distance_bias

            if dist <= 0 or dist > len(out) + config.window_size:
                # Invalid backreference
                break

            for _ in range(length):
                if dist <= len(out):
                    out.append(out[-dist])
                else:
                    out.append(config.initial_buffer_fill)

    return bytes(out)


def compress_lzss(
    data: bytes,
    config: LZSSConfig,
) -> bytes:
    """
    Compress byte buffer using the specified LZSS parameters.
    """
    out = bytearray()
    pos = 0
    length = len(data)

    max_dist = min(config.window_size, (1 << config.distance_bits) - 1)
    max_len = ((1 << config.length_bits) - 1) + config.length_bias
    min_len = config.length_bias

    while pos < length:
        flag_pos = len(out)
        out.append(0)  # placeholder for flag byte
        flag_byte = 0
        bits_left = 8

        for bit_idx in range(8):
            if pos >= length:
                break

            # Find longest match in sliding window
            best_offset = 0
            best_len = 0

            window_start = max(0, pos - max_dist)
            for search_pos in range(window_start, pos):
                cur_len = 0
                while (
                    pos + cur_len < length
                    and cur_len < max_len
                    and data[search_pos + cur_len] == data[pos + cur_len]
                ):
                    cur_len += 1

                if cur_len > best_len:
                    best_len = cur_len
                    best_offset = pos - search_pos

            if best_len >= min_len:
                # Match found: emit pointer
                bit_val = 0 if config.flag_literal_bit == 1 else 1
                dist_val = best_offset - config.distance_bias
                len_val = best_len - config.length_bias

                if config.layout == "dist_high":
                    token = (dist_val << config.length_bits) | (len_val & ((1 << config.length_bits) - 1))
                else:
                    token = ((len_val & ((1 << config.length_bits) - 1)) << config.distance_bits) | dist_val

                out.append((token >> 8) & 0xFF)
                out.append(token & 0xFF)
                pos += best_len
            else:
                # Literal
                bit_val = 1 if config.flag_literal_bit == 1 else 0
                out.append(data[pos])
                pos += 1

            if config.flag_msb_first:
                flag_byte |= (bit_val << (7 - bit_idx))
            else:
                flag_byte |= (bit_val << bit_idx)

        out[flag_pos] = flag_byte

    return bytes(out)


class HeuristicLZSolver:
    """
    Automated LZSS Parameter Discovery Engine.
    Discovers unknown / proprietary compression formats by systematically testing
    parameter permutations, evaluating Shannon entropy collapse, and measuring pattern quality.
    """

    @classmethod
    def generate_candidate_configs(cls) -> List[LZSSConfig]:
        """Generate a matrix of common LZSS configurations found in 90s/2000s games."""
        configs = []
        for msb in (True, False):
            for lit_bit in (1, 0):
                for layout in ("dist_high", "dist_low"):
                    for bias in (2, 3):
                        configs.append(
                            LZSSConfig(
                                window_size=4096,
                                distance_bits=12,
                                length_bits=4,
                                length_bias=bias,
                                distance_bias=1,
                                flag_msb_first=msb,
                                flag_literal_bit=lit_bit,
                                layout=layout,
                            )
                        )
        return configs

    @classmethod
    def solve(
        cls,
        compressed_data: bytes,
        expected_prefix: Optional[bytes] = None,
        min_expansion_ratio: float = 1.1,
    ) -> Optional[Tuple[LZSSConfig, bytes]]:
        """
        Heuristically determine the LZSS configuration of an unknown compressed blob.
        Returns (best_config, decompressed_data) or None if no valid candidate found.
        """
        if len(compressed_data) < 16:
            return None

        candidates = cls.generate_candidate_configs()
        best_cfg = None
        best_output = None
        best_score = -1e9

        for cfg in candidates:
            decomp = decompress_lzss(compressed_data, cfg, max_output=512 * 1024)
            if len(decomp) <= len(compressed_data) * min_expansion_ratio:
                continue

            score = 0.0

            # 1. Expected prefix match
            if expected_prefix:
                if decomp.startswith(expected_prefix):
                    score += 1000.0
                else:
                    continue

            # 2. Entropy evaluation
            # Natural text/data entropy is typically between 3.0 and 6.0
            counts = Counter(decomp)
            length = len(decomp)
            ent = -sum((c / length) * math.log2(c / length) for c in counts.values())

            if 2.5 <= ent <= 6.5:
                score += 50.0 - abs(ent - 4.5) * 10.0
            else:
                score -= 50.0

            # 3. Printable ASCII check
            printable_count = sum(1 for b in decomp if 32 <= b <= 126 or b in (10, 13, 9))
            ascii_ratio = printable_count / length
            score += ascii_ratio * 100.0

            # 4. Expansion ratio
            expansion = length / len(compressed_data)
            score += min(50.0, expansion * 10.0)

            if score > best_score:
                best_score = score
                best_cfg = cfg
                best_output = decomp

        if best_cfg is not None and best_output is not None:
            return best_cfg, best_output
        return None
