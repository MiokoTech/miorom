"""
miorom.audio.brr
~~~~~~~~~~~~~~~~
Super Nintendo (SNES) SPC700 / S-DSP Bit Rate Reduction (BRR) audio codec.
Decodes 9-byte BRR audio blocks to signed 16-bit PCM and encodes PCM to BRR.
"""

from __future__ import annotations

import struct
from typing import List, Optional, Sequence, Tuple

from miorom.audio.adpcm import ADPCMCodec
from miorom.errors import ParseError


# Standard SNES S-DSP BRR Filter Coefficients
BRR_FILTERS: List[Tuple[float, float]] = [
    (0.0, 0.0),
    (15.0 / 16.0, 0.0),
    (61.0 / 32.0, -15.0 / 16.0),
    (115.0 / 64.0, -13.0 / 16.0),
]


class BRRCodec:
    """
    Pure-Python SNES SPC700 BRR (Bit Rate Reduction) audio decoder and encoder.
    Each block consists of 1 header byte + 8 sample data bytes = 16 PCM samples.
    """

    BLOCK_SIZE = 9
    SAMPLES_PER_BLOCK = 16

    @classmethod
    def decode_block(
        cls,
        block: bytes,
        s1: float = 0.0,
        s2: float = 0.0,
    ) -> Tuple[List[int], float, float, bool, bool]:
        """
        Decodes a 9-byte BRR block into 16 signed 16-bit PCM samples.
        Returns (samples, next_s1, next_s2, is_loop, is_end).
        """
        if len(block) < cls.BLOCK_SIZE:
            raise ParseError(f"BRR block too short ({len(block)} < 9 bytes)")

        header = block[0]
        shift = (header >> 4) & 0x0F
        filter_idx = (header >> 2) & 0x03
        is_loop = bool(header & 0x02)
        is_end = bool(header & 0x01)

        c1, c2 = BRR_FILTERS[filter_idx]
        samples: List[int] = []

        # 8 bytes = 16 nibbles, high nibble first, then low nibble
        for b in block[1:9]:
            for nibble in ((b >> 4) & 0x0F, b & 0x0F):
                val = nibble if nibble < 8 else nibble - 16
                if shift <= 12:
                    raw = (val << shift) >> 1
                else:
                    raw = (val & ~0x07) << 11  # Clamp behavior for invalid shift

                sample = raw + s1 * c1 + s2 * c2
                clamped = max(-32768, min(32767, int(round(sample))))
                samples.append(clamped)
                s2 = s1
                s1 = float(clamped)

        return samples, s1, s2, is_loop, is_end

    @classmethod
    def decode(cls, data: bytes) -> List[int]:
        """
        Decodes raw BRR data blocks into 16-bit PCM samples.
        Stops when the END bit of a block is set.
        """
        samples: List[int] = []
        s1 = 0.0
        s2 = 0.0
        pos = 0

        while pos + cls.BLOCK_SIZE <= len(data):
            block = data[pos : pos + cls.BLOCK_SIZE]
            pos += cls.BLOCK_SIZE
            block_samples, s1, s2, is_loop, is_end = cls.decode_block(block, s1, s2)
            samples.extend(block_samples)
            if is_end:
                break

        return samples

    @classmethod
    def encode_block(
        cls,
        samples: Sequence[int],
        s1: float = 0.0,
        s2: float = 0.0,
        is_loop: bool = False,
        is_end: bool = False,
    ) -> Tuple[bytes, float, float]:
        """
        Encodes up to 16 signed 16-bit PCM samples into a 9-byte BRR block.
        Searches all 4 filter modes and shifts (0..12) to minimize reconstruction MSE.
        """
        frame = list(samples)
        if len(frame) < cls.SAMPLES_PER_BLOCK:
            frame.extend([0] * (cls.SAMPLES_PER_BLOCK - len(frame)))
        frame = frame[:cls.SAMPLES_PER_BLOCK]

        best_err = float("inf")
        best_block = b"\x00" * cls.BLOCK_SIZE
        best_s1 = s1
        best_s2 = s2

        flags = (0x02 if is_loop else 0x00) | (0x01 if is_end else 0x00)

        for f_idx, (c1, c2) in enumerate(BRR_FILTERS):
            # Calculate residuals
            test_s1, test_s2 = s1, s2
            residuals: List[float] = []
            max_res = 0.0
            for s in frame:
                pred = test_s1 * c1 + test_s2 * c2
                res = s - pred
                residuals.append(res)
                abs_res = abs(res)
                if abs_res > max_res:
                    max_res = abs_res
                test_s2 = test_s1
                test_s1 = float(s)

            # Determine shift
            shift = 0
            while shift < 12 and (max_res > (7 << (shift - 1)) if shift > 0 else max_res > 7):
                shift += 1

            enc_nibbles: List[int] = []
            cur_s1, cur_s2 = s1, s2
            total_err = 0.0

            for s in frame:
                pred = cur_s1 * c1 + cur_s2 * c2
                target = s - pred
                if shift <= 12:
                    val = int(round(target / (1 << max(0, shift - 1))))
                else:
                    val = 0
                nibble = max(-8, min(7, val))
                enc_nibbles.append(nibble & 0x0F)

                raw = (nibble << shift) >> 1
                recon = raw + cur_s1 * c1 + cur_s2 * c2
                recon_clamped = max(-32768, min(32767, int(round(recon))))
                err = (s - recon_clamped) ** 2
                total_err += err
                cur_s2 = cur_s1
                cur_s1 = float(recon_clamped)

            if total_err < best_err:
                best_err = total_err
                header = (shift << 4) | (f_idx << 2) | flags
                block_buf = bytearray([header])
                for i in range(0, 16, 2):
                    hi = enc_nibbles[i]
                    lo = enc_nibbles[i + 1]
                    block_buf.append((hi << 4) | lo)
                best_block = bytes(block_buf)
                best_s1 = cur_s1
                best_s2 = cur_s2

        return best_block, best_s1, best_s2

    @classmethod
    def encode(
        cls,
        samples: Sequence[int],
        loop_point: Optional[int] = None,
    ) -> bytes:
        """
        Encodes a sequence of 16-bit PCM samples into BRR byte blocks.
        """
        buf = bytearray()
        s1 = 0.0
        s2 = 0.0
        n_samples = len(samples)
        pos = 0

        while pos < n_samples:
            chunk = samples[pos : pos + cls.SAMPLES_PER_BLOCK]
            pos += cls.SAMPLES_PER_BLOCK
            is_end = pos >= n_samples
            is_loop = False
            if loop_point is not None:
                # Mark loop start on the block containing the loop point
                if (pos - cls.SAMPLES_PER_BLOCK) <= loop_point < pos:
                    is_loop = True

            block_bytes, s1, s2 = cls.encode_block(
                chunk,
                s1=s1,
                s2=s2,
                is_loop=is_loop,
                is_end=is_end,
            )
            buf.extend(block_bytes)

        return bytes(buf)

    @classmethod
    def to_wav(cls, brr_data: bytes, sample_rate: int = 32000) -> bytes:
        """Decodes BRR data and wraps as a standard 16-bit PCM RIFF/WAVE file."""
        samples = cls.decode(brr_data)
        return ADPCMCodec.build_wav(samples, sample_rate=sample_rate, channels=1)
