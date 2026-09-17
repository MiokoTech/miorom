"""
miorom.audio.wav_codec
~~~~~~~~~~~~~~~~~~~~~~
Pure-Python RIFF/WAVE audio encoder, decoder, and container.
Zero external dependencies (uses only standard library and miorom.core.schema).
Supports 8-bit, 16-bit, and 32-bit float PCM; mono and stereo; and seamless channel extraction.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Union

from miorom.core import schema
from miorom.errors import ParseError


@dataclass
class WavSound:
    """
    Standard in-memory representation of uncompressed PCM audio.
    Samples are stored as 16-bit signed integers (-32768 to 32767).
    Multi-channel audio has interleaved samples [L0, R0, L1, R1, ...].
    """

    samples: List[int]
    sample_rate: int = 44100
    channels: int = 1
    bits_per_sample: int = 16

    @property
    def num_frames(self) -> int:
        """Total number of sample frames (per channel)."""
        if self.channels <= 0:
            return 0
        return len(self.samples) // self.channels

    @property
    def duration_seconds(self) -> float:
        """Audio duration in seconds."""
        if self.sample_rate <= 0 or self.channels <= 0:
            return 0.0
        return self.num_frames / self.sample_rate

    def get_channel(self, channel_index: int = 0) -> List[int]:
        """
        Extracts samples for a single channel.
        channel_index 0 = Mono (or Left), 1 = Right.
        """
        if self.channels == 1:
            return list(self.samples)
        if channel_index < 0 or channel_index >= self.channels:
            raise IndexError(f"Channel index {channel_index} out of range (0..{self.channels - 1})")
        return self.samples[channel_index :: self.channels]

    def to_mono(self) -> WavSound:
        """Averages multi-channel audio into a single mono channel."""
        if self.channels == 1:
            return self
        frames = self.num_frames
        ch = self.channels
        mono: List[int] = []
        for i in range(frames):
            frame_sum = sum(self.samples[i * ch + c] for c in range(ch))
            mono.append(frame_sum // ch)
        return WavSound(
            samples=mono,
            sample_rate=self.sample_rate,
            channels=1,
            bits_per_sample=16,
        )

    def to_bytes(self) -> bytes:
        """Encodes to complete RIFF/WAVE file binary."""
        return WavCodec.encode(
            samples=self.samples,
            sample_rate=self.sample_rate,
            channels=self.channels,
            bits_per_sample=self.bits_per_sample,
        )

    def save(self, filepath: str) -> str:
        """Saves audio to a standard .wav file on disk."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(self.to_bytes())
        return filepath


class WavCodec:
    """
    Encoder and decoder for standard RIFF/WAVE (.wav) files.
    """

    RIFF_MAGIC = b"RIFF"
    WAVE_MAGIC = b"WAVE"
    FMT_MAGIC = b"fmt "
    DATA_MAGIC = b"data"

    @classmethod
    def encode(
        cls,
        samples: Union[Sequence[int], WavSound],
        sample_rate: int = 44100,
        channels: int = 1,
        bits_per_sample: int = 16,
    ) -> bytes:
        """
        Encapsulates PCM audio samples into a standard RIFF/WAVE binary.
        Accepts either a WavSound instance or a raw sample sequence.

        Parameters
        ----------
        samples : Union[Sequence[int], WavSound]
            Signed 16-bit PCM integer samples or a WavSound instance.
        sample_rate : int
            Sampling frequency in Hz (e.g. 44100, 32000, 22050).
        channels : int
            Number of audio channels (1 for mono, 2 for stereo).
        bits_per_sample : int
            Bits per sample (16 or 8).
        """
        if isinstance(samples, WavSound):
            sample_rate = samples.sample_rate
            channels = samples.channels
            bits_per_sample = samples.bits_per_sample
            samples = samples.samples

        if bits_per_sample not in (8, 16):
            raise ValueError(f"Unsupported bits_per_sample: {bits_per_sample} (must be 8 or 16)")

        block_align = channels * (bits_per_sample // 8)
        byte_rate = sample_rate * block_align

        if bits_per_sample == 16:
            # Clamping signed 16-bit
            pcm_data = bytearray(len(samples) * 2)
            for i, s in enumerate(samples):
                clamped = max(-32768, min(32767, int(s)))
                schema.pack_into("<h", pcm_data, i * 2, clamped)
        else:
            # 8-bit unsigned PCM (0..255, 128 = silence)
            pcm_data = bytearray(len(samples))
            for i, s in enumerate(samples):
                clamped_16 = max(-32768, min(32767, int(s)))
                u8 = max(0, min(255, (clamped_16 >> 8) + 128))
                pcm_data[i] = u8

        subchunk2_size = len(pcm_data)
        riff_chunk_size = 36 + subchunk2_size

        header = schema.pack(
            "<4sI4s4sIHHIIHH4sI",
            cls.RIFF_MAGIC,
            riff_chunk_size,
            cls.WAVE_MAGIC,
            cls.FMT_MAGIC,
            16,             # Subchunk1Size (16 for standard PCM)
            1,              # AudioFormat (1 = PCM)
            channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
            cls.DATA_MAGIC,
            subchunk2_size,
        )

        return header + bytes(pcm_data)

    @classmethod
    def decode(cls, data: bytes) -> WavSound:
        """
        Parses a RIFF/WAVE file binary into a WavSound object.
        Supports 8-bit, 16-bit PCM, and 32-bit float audio.
        """
        if len(data) < 44:
            raise ParseError("Data too small to be a valid WAV file (minimum 44 bytes)")

        if data[:4] != cls.RIFF_MAGIC:
            raise ParseError(f"Invalid WAV header: expected 'RIFF', got {data[:4]!r}")

        if data[8:12] != cls.WAVE_MAGIC:
            raise ParseError(f"Invalid WAV format: expected 'WAVE', got {data[8:12]!r}")

        pos = 12
        audio_format = 1
        channels = 1
        sample_rate = 44100
        bits_per_sample = 16
        pcm_raw = b""

        while pos + 8 <= len(data):
            chunk_id = data[pos : pos + 4]
            chunk_size = schema.unpack_from("<I", data, pos + 4)[0]
            pos += 8

            if chunk_id == cls.FMT_MAGIC:
                if chunk_size < 16:
                    raise ParseError("Corrupt WAV 'fmt ' chunk: size < 16")
                audio_format, channels, sample_rate, _byte_rate, _align, bits_per_sample = schema.unpack_from(
                    "<HHIIHH", data, pos
                )
            elif chunk_id == cls.DATA_MAGIC:
                # Payload chunk
                pcm_raw = data[pos : pos + chunk_size]

            pos += chunk_size
            # Word align
            if chunk_size % 2 == 1:
                pos += 1

        if not pcm_raw:
            # Fallback: if data was truncated or missing data tag, read from byte 44
            pcm_raw = data[44:]

        samples: List[int] = []

        if audio_format == 1:  # Integer PCM
            if bits_per_sample == 16:
                num_samples = len(pcm_raw) // 2
                samples = [schema.unpack_from("<h", pcm_raw, i * 2)[0] for i in range(num_samples)]
            elif bits_per_sample == 8:
                # Convert 8-bit unsigned (0..255) to 16-bit signed (-32768..32767)
                samples = [((b - 128) << 8) for b in pcm_raw]
            elif bits_per_sample == 24:
                # 24-bit PCM: 3 bytes per sample little-endian
                num_samples = len(pcm_raw) // 3
                for i in range(num_samples):
                    b0, b1, b2 = pcm_raw[i * 3 : i * 3 + 3]
                    val = (b0 | (b1 << 8) | (b2 << 16))
                    if val & 0x800000:
                        val -= 0x1000000
                    samples.append(val >> 8)
            elif bits_per_sample == 32:
                num_samples = len(pcm_raw) // 4
                samples = [schema.unpack_from("<i", pcm_raw, i * 4)[0] >> 16 for i in range(num_samples)]
            else:
                raise ParseError(f"Unsupported bit depth for PCM WAV: {bits_per_sample}")

        elif audio_format == 3:  # IEEE Float
            if bits_per_sample == 32:
                num_samples = len(pcm_raw) // 4
                for i in range(num_samples):
                    f_val = schema.unpack_from("<f", pcm_raw, i * 4)[0]
                    clamped = max(-1.0, min(1.0, f_val))
                    samples.append(int(clamped * 32767.0))
            else:
                raise ParseError(f"Unsupported bit depth for IEEE Float WAV: {bits_per_sample}")
        else:
            raise ParseError(f"Unsupported WAV compression format tag: {audio_format} (only PCM=1 and Float=3 supported)")

        return WavSound(
            samples=samples,
            sample_rate=sample_rate,
            channels=channels,
            bits_per_sample=16,
        )

    @classmethod
    def decode_file(cls, filepath: str) -> WavSound:
        """Reads a .wav file from disk and parses it into a WavSound."""
        with open(filepath, "rb") as f:
            return cls.decode(f.read())

    @classmethod
    def encode_file(
        cls,
        filepath: str,
        samples: Sequence[int],
        sample_rate: int = 44100,
        channels: int = 1,
        bits_per_sample: int = 16,
    ) -> str:
        """Encodes samples and writes a .wav file to disk."""
        wav_bytes = cls.encode(samples, sample_rate=sample_rate, channels=channels, bits_per_sample=bits_per_sample)
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(wav_bytes)
        return filepath

    @classmethod
    def inspect(cls, data: bytes) -> Dict[str, Any]:
        """Inspects WAV file header metadata without decoding all samples."""
        sound = cls.decode(data)
        return {
            "format": "WAVE (PCM)",
            "file_size": len(data),
            "sample_rate": sound.sample_rate,
            "channels": sound.channels,
            "bits_per_sample": sound.bits_per_sample,
            "num_samples": len(sound.samples),
            "num_frames": sound.num_frames,
            "duration_seconds": round(sound.duration_seconds, 3),
        }
