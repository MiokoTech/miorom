"""
miorom.audio.vag
~~~~~~~~~~~~~~~~
Sony PlayStation (PS1, PS2) VAG audio format parser, SPU-ADPCM decoder and encoder.
Standard format used for sound effects, character voices, and music samples.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from miorom.audio.adpcm import ADPCMCodec
from miorom.errors import ParseError


# Standard Sony SPU-ADPCM Filter coefficients
SPU_FILTERS: List[Tuple[float, float]] = [
    (0.0, 0.0),
    (60.0 / 64.0, 0.0),
    (115.0 / 64.0, -52.0 / 64.0),
    (98.0 / 64.0, -55.0 / 64.0),
    (122.0 / 64.0, -60.0 / 64.0),
]


@dataclass
class VAGHeader:
    """48-byte VAG file header."""
    magic: bytes           # b"VAGp" (mono/stream) or b"VAGi" (interleaved)
    version: int           # Usually 2 or 3
    interleave: int        # Interleave block size (0 for mono)
    data_size: int         # Size of ADPCM audio data in bytes
    sample_rate: int       # e.g. 44100, 22050, 32000
    name: str              # 16-character ASCII name

    @classmethod
    def from_bytes(cls, data: bytes) -> VAGHeader:
        if len(data) < 48:
            raise ParseError(f"Data too short for VAG header: {len(data)} < 48 bytes")
        magic = data[:4]
        if magic not in (b"VAGp", b"VAGi", b"VAG1", b"VAG2"):
            raise ParseError(f"Invalid VAG magic: {magic!r}")

        version, interleave, data_size, sample_rate = struct.unpack(">IIII", data[4:20])
        # Skip 12 reserved bytes (20:32)
        raw_name = data[32:48].split(b"\x00")[0]
        try:
            name = raw_name.decode("ascii", errors="replace")
        except Exception:
            name = ""

        return cls(
            magic=magic,
            version=version,
            interleave=interleave,
            data_size=data_size,
            sample_rate=sample_rate,
            name=name,
        )

    def to_bytes(self) -> bytes:
        buf = bytearray()
        buf.extend(self.magic[:4].ljust(4, b"\x00"))
        buf.extend(struct.pack(">IIII", self.version, self.interleave, self.data_size, self.sample_rate))
        buf.extend(b"\x00" * 12)  # reserved
        name_bytes = self.name.encode("ascii", errors="replace")[:16].ljust(16, b"\x00")
        buf.extend(name_bytes)
        return bytes(buf)


class VAGCodec:
    """
    Pure-Python Sony SPU-ADPCM decoder and encoder for PS1 and PS2 VAG files.
    """

    BLOCK_SIZE = 16
    SAMPLES_PER_BLOCK = 28

    @classmethod
    def decode_block(
        cls,
        block: bytes,
        s1: float = 0.0,
        s2: float = 0.0,
    ) -> Tuple[List[int], float, float, int]:
        """
        Decodes a single 16-byte SPU-ADPCM block into 28 signed 16-bit PCM samples.
        Returns (samples, next_s1, next_s2, flags).
        """
        if len(block) < cls.BLOCK_SIZE:
            raise ParseError(f"SPU-ADPCM block too short ({len(block)} < 16 bytes)")

        shift = block[0] & 0x0F
        filter_idx = (block[0] >> 4) & 0x0F
        flags = block[1]

        if filter_idx >= len(SPU_FILTERS):
            filter_idx = 0
        c1, c2 = SPU_FILTERS[filter_idx]

        samples: List[int] = []
        for b in block[2:16]:
            # Low nibble first, then high nibble
            for nibble in (b & 0x0F, (b >> 4) & 0x0F):
                val = nibble if nibble < 8 else nibble - 16
                if shift <= 12:
                    raw = val << (12 - shift)
                else:
                    raw = val >> (shift - 12)
                sample = raw + s1 * c1 + s2 * c2
                clamped = max(-32768, min(32767, int(round(sample))))
                samples.append(clamped)
                s2 = s1
                s1 = float(clamped)

        return samples, s1, s2, flags

    @classmethod
    def decode(cls, data: bytes) -> List[int]:
        """
        Decodes raw SPU-ADPCM bytes into a list of 16-bit PCM audio samples.
        Stops if an end-of-stream flag (0x04 or 0x07) is encountered.
        """
        samples: List[int] = []
        s1 = 0.0
        s2 = 0.0
        pos = 0

        while pos + cls.BLOCK_SIZE <= len(data):
            block = data[pos : pos + cls.BLOCK_SIZE]
            pos += cls.BLOCK_SIZE
            block_samples, s1, s2, flags = cls.decode_block(block, s1, s2)
            samples.extend(block_samples)
            if flags & 0x04:  # End of sample flag
                break

        return samples

    @classmethod
    def encode_block(
        cls,
        samples: Sequence[int],
        s1: float = 0.0,
        s2: float = 0.0,
        flags: int = 0x00,
    ) -> Tuple[bytes, float, float]:
        """
        Encodes up to 28 signed 16-bit PCM samples into a 16-byte SPU-ADPCM block.
        Tests available filters to minimize quantization error.
        """
        frame = list(samples)
        if len(frame) < cls.SAMPLES_PER_BLOCK:
            frame.extend([0] * (cls.SAMPLES_PER_BLOCK - len(frame)))
        frame = frame[:cls.SAMPLES_PER_BLOCK]

        best_err = float("inf")
        best_block = b"\x00" * 16
        best_s1 = s1
        best_s2 = s2

        # Search optimal filter (0..4) and shift (0..12)
        for f_idx, (c1, c2) in enumerate(SPU_FILTERS):
            # Determine maximum predicted residual to set shift
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

            # Find minimum shift (0..12) that accommodates max_res
            shift = 0
            while shift < 12 and (max_res > (7 << (12 - shift))):
                shift += 1

            # Quantize
            enc_nibbles: List[int] = []
            cur_s1, cur_s2 = s1, s2
            total_err = 0.0
            scale = 1.0 / (1 << (12 - shift))

            for s in frame:
                pred = cur_s1 * c1 + cur_s2 * c2
                target = (s - pred) * scale
                nibble = max(-8, min(7, int(round(target))))
                enc_nibbles.append(nibble & 0x0F)
                recon = (nibble << (12 - shift)) + pred
                recon_clamped = max(-32768, min(32767, int(round(recon))))
                err = (s - recon_clamped) ** 2
                total_err += err
                cur_s2 = cur_s1
                cur_s1 = float(recon_clamped)

            if total_err < best_err:
                best_err = total_err
                header_byte = (f_idx << 4) | (shift & 0x0F)
                block_buf = bytearray([header_byte, flags])
                for i in range(0, 28, 2):
                    lo = enc_nibbles[i]
                    hi = enc_nibbles[i + 1]
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
        Encodes a list of 16-bit PCM audio samples into raw SPU-ADPCM byte blocks.
        Appends an empty terminating block with the EOS flag (0x07) per Sony spec.
        """
        buf = bytearray()
        s1 = 0.0
        s2 = 0.0
        n_samples = len(samples)
        pos = 0

        while pos < n_samples:
            chunk = samples[pos : pos + cls.SAMPLES_PER_BLOCK]
            pos += cls.SAMPLES_PER_BLOCK
            flags = 0x00
            if loop_point is not None and pos >= loop_point and (pos - cls.SAMPLES_PER_BLOCK) < loop_point:
                flags = 0x06  # Loop start
            elif loop_point is not None and pos >= loop_point:
                flags = 0x02  # Loop repeat
            if pos >= n_samples and loop_point is None:
                flags |= 0x01  # 1-shot sound

            block_bytes, s1, s2 = cls.encode_block(chunk, s1, s2, flags=flags)
            buf.extend(block_bytes)

        # Sony EOS termination block
        end_flags = 0x03 if loop_point is not None else 0x07
        buf.extend(bytes([0x00, end_flags]) + b"\x00" * 14)
        return bytes(buf)


class VAGFile:
    """
    PlayStation VAG Audio File container, parser, and exporter.
    """

    def __init__(self, header: VAGHeader, audio_data: bytes):
        self.header = header
        self.audio_data = audio_data

    @classmethod
    def from_bytes(cls, data: bytes) -> VAGFile:
        header = VAGHeader.from_bytes(data)
        audio_offset = 48
        # Check 64-byte padded header
        if len(data) >= 64 and data[48:64] == b"\x00" * 16:
            audio_offset = 64
        audio_data = data[audio_offset : audio_offset + header.data_size]
        if not audio_data:
            audio_data = data[audio_offset:]
        return cls(header=header, audio_data=audio_data)

    def to_bytes(self) -> bytes:
        hdr = self.header
        hdr.data_size = len(self.audio_data)
        return hdr.to_bytes() + self.audio_data

    def decode(self) -> List[int]:
        """Decodes VAG audio into signed 16-bit PCM samples."""
        return VAGCodec.decode(self.audio_data)

    def to_wav(self) -> bytes:
        """Converts VAG audio into standard 16-bit mono RIFF/WAVE bytes."""
        samples = self.decode()
        return ADPCMCodec.build_wav(
            samples=samples,
            sample_rate=self.header.sample_rate or 44100,
            channels=1,
        )

    @classmethod
    def from_pcm(
        cls,
        samples: Sequence[int],
        sample_rate: int = 44100,
        name: str = "",
        loop_point: Optional[int] = None,
    ) -> VAGFile:
        """Creates a VAGFile instance from raw PCM 16-bit samples."""
        encoded = VAGCodec.encode(samples, loop_point=loop_point)
        header = VAGHeader(
            magic=b"VAGp",
            version=3,
            interleave=0,
            data_size=len(encoded),
            sample_rate=sample_rate,
            name=name,
        )
        return cls(header=header, audio_data=encoded)
