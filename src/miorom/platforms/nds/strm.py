"""
strm.py - Nintendo DS Nitro Stream (STRM) audio parser, decoder, and encoder.

Supports:
- Decoding Nitro STRM (PCM8, PCM16, IMA-ADPCM) mono and stereo to standard 16-bit PCM RIFF WAV.
- Encoding standard WAV (PCM8, PCM16) into Nitro STRM containers (IMA-ADPCM, PCM16, PCM8).
"""

from __future__ import annotations

import math
import os
import struct
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from miorom.audio.adpcm import ADPCMCodec
from miorom.errors import ParseError


@dataclass
class STRMHeader:
    """Parsed metadata from STRM header and HEAD block."""

    wave_type: int  # 0: PCM8, 1: PCM16, 2: IMA-ADPCM
    loop_flag: int  # 0: False, 1: True
    channels: int   # 1: Mono, 2: Stereo
    time_format: int
    sample_rate: int
    timer_period: int
    loop_start: int
    num_samples: int
    data_offset: int
    num_blocks: int
    block_size: int
    samples_per_block: int
    last_block_size: int
    last_samples_per_block: int


class STRMFile:
    """
    Nintendo DS Nitro Stream (STRM) audio parser, decoder, and builder.
    Handles multi-channel streaming audio containers commonly used for voice clips,
    cutscene voice acting, sound effects, and jingles in Nintendo DS games.
    """

    MAGIC = b"STRM"

    def __init__(self, data: bytes) -> None:
        if len(data) < 96:
            raise ParseError("Data too small for valid STRM container (minimum 96 bytes).")

        if data[:4] != self.MAGIC:
            raise ParseError(f"Invalid STRM magic: {data[:4]!r}")

        self.data = bytearray(data)
        endian, version, self.file_size, self.header_size, num_blocks = struct.unpack_from("<HHIHH", self.data, 4)

        if endian != 0xFEFF:
            raise ParseError(f"Unsupported STRM endianness: 0x{endian:04X} (expected 0xFEFF).")

        # Parse HEAD block
        head_off = self.header_size
        head_magic, head_size = struct.unpack_from("<4sI", self.data, head_off)
        if head_magic != b"HEAD":
            raise ParseError(f"Invalid HEAD block magic: {head_magic!r}")

        (
            wave_type,
            loop_flag,
            channels,
            time_format,
            sample_rate,
            timer_period,
            loop_start,
            num_samples,
            data_offset,
            num_blocks_val,
            block_size,
            spb,
            last_block_sz,
            last_spb,
        ) = struct.unpack_from("<BBBBHHIIIIIIII", self.data, head_off + 8)

        self.header = STRMHeader(
            wave_type=wave_type,
            loop_flag=loop_flag,
            channels=channels,
            time_format=time_format,
            sample_rate=sample_rate,
            timer_period=timer_period,
            loop_start=loop_start,
            num_samples=num_samples,
            data_offset=data_offset,
            num_blocks=num_blocks_val,
            block_size=block_size,
            samples_per_block=spb,
            last_block_size=last_block_sz,
            last_samples_per_block=last_spb,
        )

        # Locate DATA block
        data_block_off = head_off + head_size
        data_magic, data_size = struct.unpack_from("<4sI", self.data, data_block_off)
        if data_magic != b"DATA":
            raise ParseError(f"Invalid DATA block magic: {data_magic!r}")

        self.data_payload = self.data[self.header.data_offset : head_off + head_size + data_size]

    @classmethod
    def from_file(cls, path: str) -> "STRMFile":
        """Loads and parses an STRM file from disk."""
        with open(path, "rb") as f:
            return cls(f.read())

    def decode_samples(self) -> List[List[int]]:
        """
        Decodes all audio blocks into signed 16-bit PCM samples per channel.
        Returns a list of sample lists: [channel_0_samples, channel_1_samples (if stereo)].
        """
        h = self.header
        channels_data: List[List[int]] = [[] for _ in range(h.channels)]
        pos = 0

        # State tracking for ADPCM continuation
        adpcm_states: List[Tuple[int, int]] = [(0, 0) for _ in range(h.channels)]

        for b in range(h.num_blocks):
            is_last = (b == h.num_blocks - 1)
            cur_block_sz = h.last_block_size if is_last else h.block_size
            cur_spb = h.last_samples_per_block if is_last else h.samples_per_block

            for ch in range(h.channels):
                block_bytes = self.data_payload[pos : pos + cur_block_sz]
                pos += cur_block_sz

                if h.wave_type == 2:
                    # IMA-ADPCM 4-bit
                    if len(block_bytes) >= 4:
                        init_samp, init_idx = struct.unpack_from("<hb", block_bytes, 0)
                        # Clamp initial index to valid table range
                        init_idx = max(0, min(88, init_idx))
                        adpcm_payload = block_bytes[4:]
                        ch_samples = ADPCMCodec.decode_ima(
                            adpcm_payload, initial_predictor=init_samp, initial_index=init_idx
                        )
                        channels_data[ch].extend(ch_samples[:cur_spb])
                elif h.wave_type == 1:
                    # PCM16 signed Little Endian
                    sample_count = cur_spb
                    raw_samps = struct.unpack(f"<{sample_count}h", block_bytes[: sample_count * 2])
                    channels_data[ch].extend(raw_samps)
                elif h.wave_type == 0:
                    # PCM8 signed
                    sample_count = cur_spb
                    raw_samps = struct.unpack(f"<{sample_count}b", block_bytes[:sample_count])
                    # Scale signed 8-bit to 16-bit
                    channels_data[ch].extend([s << 8 for s in raw_samps])
                else:
                    raise ValueError(f"Unsupported wave_type: {h.wave_type}")

        # Truncate each channel strictly to total num_samples
        for ch in range(h.channels):
            channels_data[ch] = channels_data[ch][: h.num_samples]

        return channels_data

    def to_wav(self) -> bytes:
        """
        Decodes the STRM audio stream and encapsulates it into a standard 16-bit RIFF WAV binary.
        """
        channels_samples = self.decode_samples()
        h = self.header

        if h.channels == 1:
            interleaved_samples = channels_samples[0]
        else:
            # Interleave L and R channels
            left = channels_samples[0]
            right = channels_samples[1]
            min_len = min(len(left), len(right))
            interleaved_samples = []
            for i in range(min_len):
                interleaved_samples.append(left[i])
                interleaved_samples.append(right[i])

        return ADPCMCodec.build_wav(
            interleaved_samples,
            sample_rate=h.sample_rate,
            channels=h.channels,
        )

    def save_wav(self, output_path: str) -> None:
        """Decodes the STRM stream and writes it to a .wav file."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(self.to_wav())

    @classmethod
    def from_wav(
        cls,
        wav_bytes: bytes,
        wave_type: int = 2,
        block_size: int = 512,
    ) -> "STRMFile":
        """
        Encodes standard WAV audio into a Nintendo DS Nitro STRM binary.
        Supports IMA-ADPCM (wave_type=2) and PCM16 (wave_type=1).
        """
        wav_info = ADPCMCodec.read_wav(wav_bytes)
        channels = wav_info["channels"]
        sample_rate = wav_info["sample_rate"]
        all_samples = wav_info["samples"]

        if channels not in (1, 2):
            raise ValueError(f"Only Mono (1) and Stereo (2) audio supported (got {channels} channels).")

        # De-interleave channels
        if channels == 1:
            channel_samples = [all_samples]
        else:
            left = [all_samples[i] for i in range(0, len(all_samples), 2)]
            right = [all_samples[i] for i in range(1, len(all_samples), 2)]
            channel_samples = [left, right]

        num_samples = len(channel_samples[0])
        if num_samples == 0:
            raise ValueError("WAV file contains no audio samples.")

        # Calculate block parameters
        if wave_type == 2:
            # IMA-ADPCM block parameters
            spb = (block_size - 4) * 2
        elif wave_type == 1:
            # PCM16: 2 bytes per sample
            spb = block_size // 2
        elif wave_type == 0:
            # PCM8: 1 byte per sample
            spb = block_size
        else:
            raise ValueError(f"Unsupported wave_type: {wave_type}")

        num_blocks = math.ceil(num_samples / spb)
        rem_samples = num_samples % spb
        last_spb = rem_samples if rem_samples != 0 else spb

        if wave_type == 2:
            last_block_size = 4 + math.ceil(last_spb / 2)
        elif wave_type == 1:
            last_block_size = last_spb * 2
        elif wave_type == 0:
            last_block_size = last_spb

        # Encode audio payload blocks
        encoded_data = bytearray()
        adpcm_states: List[Tuple[int, int]] = [(0, 0) for _ in range(channels)]

        for b in range(num_blocks):
            is_last = (b == num_blocks - 1)
            cur_spb = last_spb if is_last else spb
            start_idx = b * spb
            end_idx = start_idx + cur_spb

            for ch in range(channels):
                block_samps = channel_samples[ch][start_idx:end_idx]
                if wave_type == 2:
                    init_samp, init_idx = adpcm_states[ch]
                    if b == 0 and block_samps:
                        init_samp = block_samps[0]
                        # Estimate reasonable initial index based on initial amplitude
                        init_idx = min(88, max(0, int(abs(init_samp) / 500)))

                    comp_bytes, final_samp, final_idx = ADPCMCodec.encode_ima(
                        block_samps, initial_predictor=init_samp, initial_index=init_idx
                    )
                    adpcm_states[ch] = (final_samp, final_idx)

                    # Build block: 4-byte header + compressed nibbles
                    block_header = struct.pack("<hbB", init_samp, init_idx, 0)
                    ch_block = bytearray(block_header)
                    ch_block.extend(comp_bytes)
                    target_sz = last_block_size if is_last else block_size
                    if len(ch_block) < target_sz:
                        ch_block.extend(b"\x00" * (target_sz - len(ch_block)))
                    encoded_data.extend(ch_block[:target_sz])

                elif wave_type == 1:
                    # PCM16
                    raw_b = bytearray()
                    for s in block_samps:
                        raw_b.extend(struct.pack("<h", s))
                    target_sz = last_block_size if is_last else block_size
                    if len(raw_b) < target_sz:
                        raw_b.extend(b"\x00" * (target_sz - len(raw_b)))
                    encoded_data.extend(raw_b[:target_sz])

                elif wave_type == 0:
                    # PCM8
                    raw_b = bytearray()
                    for s in block_samps:
                        raw_b.extend(struct.pack("<b", max(-128, min(127, s >> 8))))
                    target_sz = last_block_size if is_last else block_size
                    if len(raw_b) < target_sz:
                        raw_b.extend(b"\x00" * (target_sz - len(raw_b)))
                    encoded_data.extend(raw_b[:target_sz])

        # Construct DATA block (aligned to 4 bytes)
        data_block = bytearray(b"DATA")
        data_block_size = 8 + len(encoded_data)
        data_block.extend(struct.pack("<I", data_block_size))
        data_block.extend(encoded_data)
        pad = (4 - (len(data_block) % 4)) % 4
        if pad > 0:
            data_block.extend(b"\x00" * pad)

        # Construct HEAD block (80 bytes)
        head_size = 80
        data_offset = 16 + head_size + 8  # 104 (0x68)
        timer_period = 0x0020

        head_block = bytearray(b"HEAD")
        head_block.extend(struct.pack("<I", head_size))
        head_block.extend(
            struct.pack(
                "<BBBBHHIIIIIIII",
                wave_type,
                0,  # loop_flag
                channels,
                0,  # time_format
                sample_rate,
                timer_period,
                0,  # loop_start
                num_samples,
                data_offset,
                num_blocks,
                block_size,
                spb,
                last_block_size,
                last_spb,
            )
        )
        # Pad HEAD block to 80 bytes
        if len(head_block) < head_size:
            head_block.extend(b"\x00" * (head_size - len(head_block)))

        # Construct STRM file header (16 bytes)
        total_file_size = 16 + len(head_block) + len(data_block)
        header = bytearray(cls.MAGIC)
        header.extend(struct.pack("<HHIHH", 0xFEFF, 0x0100, total_file_size, 16, 2))

        full_bytes = bytes(header + head_block + data_block)
        return cls(full_bytes)

    def to_bytes(self) -> bytes:
        """Returns the pristine Nintendo DS STRM binary representation."""
        return bytes(self.data)
