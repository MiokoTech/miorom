"""
miorom.audio.dsp_adpcm
~~~~~~~~~~~~~~~~~~~~~~
Nintendo GameCube & Wii DSP-ADPCM audio decoder and WAV converter.
Format used in .dsp, .brstm, and .hps audio streams.
"""

from __future__ import annotations

import struct
from typing import List, Optional, Sequence, Tuple

from miorom.audio.adpcm import ADPCMCodec
from miorom.errors import ParseError


# Standard neutral DSP coefficients (8 pairs)
DEFAULT_DSP_COEFFS: List[int] = [
    2048, 0,
    0, 0,
    0, 0,
    0, 0,
    0, 0,
    0, 0,
    0, 0,
    0, 0,
]


class DSPADPCMCodec:
    """
    Nintendo GameCube & Wii DSP-ADPCM decoder.
    Each 8-byte frame unpacks into 14 16-bit PCM samples using standard DSP coefficient tables.
    """

    FRAME_SIZE = 8
    SAMPLES_PER_FRAME = 14

    @classmethod
    def decode_frame(
        cls,
        frame: bytes,
        coefs: Sequence[int],
        s1: int = 0,
        s2: int = 0,
    ) -> Tuple[List[int], int, int]:
        """
        Decodes a single 8-byte DSP-ADPCM frame into 14 signed 16-bit PCM samples.
        """
        if len(frame) < cls.FRAME_SIZE:
            raise ParseError(f"DSP-ADPCM frame too short ({len(frame)} < 8 bytes)")
        if len(coefs) < 16:
            raise ParseError(f"DSP-ADPCM requires 16 filter coefficients, got {len(coefs)}")

        header = frame[0]
        scale_exp = header & 0x0F
        scale = 1 << scale_exp
        pred_idx = (header >> 4) & 0x07

        c1 = coefs[pred_idx * 2]
        c2 = coefs[pred_idx * 2 + 1]

        samples: List[int] = []

        # 7 bytes = 14 nibbles (high nibble first, then low nibble)
        for b in frame[1:8]:
            for nibble in ((b >> 4) & 0x0F, b & 0x0F):
                val = nibble if nibble < 8 else nibble - 16
                sample = (val * scale * 2048 + s1 * c1 + s2 * c2 + 1024) >> 11
                clamped = max(-32768, min(32767, sample))
                samples.append(clamped)
                s2 = s1
                s1 = clamped

        return samples, s1, s2

    @classmethod
    def decode(
        cls,
        data: bytes,
        coefs: Optional[Sequence[int]] = None,
    ) -> List[int]:
        """
        Decodes raw DSP-ADPCM frames into signed 16-bit PCM audio samples.
        """
        if coefs is None:
            coefs = DEFAULT_DSP_COEFFS
        if len(coefs) < 16:
            raise ParseError(f"DSP-ADPCM requires 16 filter coefficients, got {len(coefs)}")

        samples: List[int] = []
        s1 = 0
        s2 = 0
        pos = 0

        while pos + cls.FRAME_SIZE <= len(data):
            frame = data[pos : pos + cls.FRAME_SIZE]
            pos += cls.FRAME_SIZE
            frame_samples, s1, s2 = cls.decode_frame(frame, coefs, s1, s2)
            samples.extend(frame_samples)

        return samples

    @classmethod
    def to_wav(
        cls,
        data: bytes,
        coefs: Optional[Sequence[int]] = None,
        sample_rate: int = 32000,
    ) -> bytes:
        """Decodes DSP-ADPCM data and wraps into a standard 16-bit PCM RIFF/WAVE file."""
        samples = cls.decode(data, coefs=coefs)
        return ADPCMCodec.build_wav(samples, sample_rate=sample_rate, channels=1)
