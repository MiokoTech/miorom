"""
miorom.platforms.psp.at3
~~~~~~~~~~~~~~~~~~~~~~~~
Sony PlayStation Portable (PSP) ATRAC3 and ATRAC3plus audio stream container parser,
metadata inspector, loop point editor, and synthesizer.

PSP audio files (.at3 and SND0.AT3) are RIFF WAVE containers encapsulating
Sony ATRAC3 (tag 0x0270) or ATRAC3plus (tag 0xFFFE extensible GUID) compressed audio.
Seamless background music (BGM) looping in PSP games is controlled by the RIFF 'smpl' chunk.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Union

from miorom.core.schema import (
    U16,
    U32,
    BinaryStruct,
    RawBytes,
    unpack_from,
)
from miorom.errors import ParseError
from miorom.result import MioRomResult

# RIFF Magic Signatures
RIFF_MAGIC = b"RIFF"
WAVE_MAGIC = b"WAVE"

FMT_CHUNK_ID = b"fmt "
FACT_CHUNK_ID = b"fact"
SMPL_CHUNK_ID = b"smpl"
DATA_CHUNK_ID = b"data"

# Format Tags
ATRAC3_FORMAT_TAG = 0x0270
WAVE_FORMAT_EXTENSIBLE = 0xFFFE

# Sony ATRAC3plus SubFormat GUID: {BFB03CD0-2581-4484-9B7E-FA21693E32D4}
ATRAC3PLUS_GUID = (
    b"\xbf\xb0\x3c\xd0\x25\x81\x44\x84\x9b\x7e\xfa\x21\x69\x3e\x32\xd4"
)
# Sony ATRAC3 SubFormat GUID: {E923AAB4-BB58-4477-AA77-03374014CD26}
ATRAC3_GUID = (
    b"\xb4\xaa\x23\xe9\x58\xbb\x77\x44\xaa\x77\x03\x37\x40\x14\xcd\x26"
)


class AT3Codec(str, Enum):
    """Sony ATRAC audio codec identifiers."""

    ATRAC3 = "atrac3"
    ATRAC3PLUS = "atrac3plus"
    UNKNOWN = "unknown"


class RiffHeaderStruct(BinaryStruct):
    """RIFF container 12-byte header."""

    magic = RawBytes(4)  # b"RIFF"
    file_size = U32()  # Total file size - 8
    form_type = RawBytes(4)  # b"WAVE"


class ChunkHeaderStruct(BinaryStruct):
    """RIFF 8-byte sub-chunk header."""

    chunk_id = RawBytes(4)  # 4-character chunk ID
    chunk_size = U32()  # Chunk data length


class WaveFormatExStruct(BinaryStruct):
    """WAVEFORMATEX 16-byte base header."""

    wFormatTag = U16()  # 0x0270 (ATRAC3) or 0xFFFE (Extensible)
    nChannels = U16()  # 1 = Mono, 2 = Stereo
    nSamplesPerSec = U32()  # Sample rate (Hz)
    nAvgBytesPerSec = U32()  # Average byte rate
    nBlockAlign = U16()  # Compressed frame size in bytes
    wBitsPerSample = U16()  # 0 for compressed stream


class Atrac3FormatExtraStruct(BinaryStruct):
    """ATRAC3 extra format parameters (14 bytes)."""

    cbSize = U16()  # 14 (0x000E)
    wSubFormat = U16()  # 1
    nSamplesPerBlock = U32()  # 1024 samples per frame
    wChannelMask = U16()  # Channel mask
    wCodingMode = U16()  # Joint stereo mode
    wReserved = U32()  # 0


class FactChunkStruct(BinaryStruct):
    """RIFF 'fact' 8-byte chunk descriptor."""

    total_samples = U32()  # Total audio samples (per channel)
    delay_samples = U32()  # Encoder priming delay samples


class SmplChunkHeaderStruct(BinaryStruct):
    """RIFF 'smpl' 36-byte sampler chunk header."""

    dwManufacturer = U32()  # 0
    dwProduct = U32()  # 0
    dwSamplePeriod = U32()  # Nanoseconds per sample (10^9 / sample_rate)
    dwMIDIUnityNote = U32()  # 60 (Middle C)
    dwMIDIPitchFraction = U32()  # 0
    dwSMPTEFormat = U32()  # 0
    dwSMPTEOffset = U32()  # 0
    cSampleLoops = U32()  # Number of loop point entries (typically 1)
    cbSamplerData = U32()  # Extra sampler data length (0)


class SmplLoopEntryStruct(BinaryStruct):
    """RIFF 'smpl' 24-byte sampler loop entry."""

    dwIdentifier = U32()  # Loop point identifier (0)
    dwType = U32()  # 0 = Forward loop
    dwStart = U32()  # Loop start sample index
    dwEnd = U32()  # Loop end sample index
    dwFraction = U32()  # Fractional sample (0)
    dwPlayCount = U32()  # 0 = Infinite loop


@dataclass
class AT3LoopPoint(MioRomResult):
    """Loop point timing and sample metrics for seamless BGM playback."""

    start_sample: int
    end_sample: int
    start_seconds: float
    end_seconds: float


@dataclass
class _ChunkInfo:
    chunk_id: bytes
    header_offset: int
    data_offset: int
    data_size: int


class AT3Audio:
    """
    Sony PlayStation Portable (PSP) ATRAC3 / ATRAC3plus audio stream container.
    Provides metadata inspection, loop point reading/editing, payload replacement,
    and RIFF WAVE serialization.
    """

    def __init__(self, raw_data: bytes):
        if len(raw_data) < 12:
            raise ParseError(
                f"Data too short for RIFF header: {len(raw_data)} < 12 bytes"
            )

        self.raw_data = bytearray(raw_data)
        self.riff_header = RiffHeaderStruct.from_bytes(
            self.raw_data, offset=0, endian="<"
        )

        if self.riff_header.magic != RIFF_MAGIC:
            raise ParseError(
                f"Invalid RIFF header magic: expected b'RIFF', got {self.riff_header.magic!r}"
            )
        if self.riff_header.form_type != WAVE_MAGIC:
            raise ParseError(
                f"Invalid RIFF form type: expected b'WAVE', got {self.riff_header.form_type!r}"
            )

        total_riff_len = self.riff_header.file_size + 8
        if len(self.raw_data) > total_riff_len:
            self.raw_data = self.raw_data[:total_riff_len]

        self._chunks: List[_ChunkInfo] = []
        self._chunk_map: Dict[bytes, _ChunkInfo] = {}

        self.codec: AT3Codec = AT3Codec.UNKNOWN
        self.channels: int = 2
        self.sample_rate: int = 44100
        self.bitrate_kbps: int = 132
        self.frame_size: int = 384
        self.samples_per_frame: int = 1024
        self.total_samples: int = 0
        self.delay_samples: int = 0
        self.loop_point: Optional[AT3LoopPoint] = None

        self._parse_chunks()
        self._parse_format()
        self._parse_fact()
        self._parse_loop()

    @classmethod
    def from_bytes(cls, data: bytes) -> "AT3Audio":
        """Parse an AT3 audio stream from raw bytes."""
        return cls(data)

    @classmethod
    def from_file(cls, path: Union[str, os.PathLike]) -> "AT3Audio":
        """Read and parse an AT3 audio file from disk."""
        with open(path, "rb") as f:
            return cls(f.read())

    def _sync_riff_size(self):
        """Recalculate and synchronize the RIFF file size header and struct field."""
        new_file_size = len(self.raw_data) - 8
        self.raw_data[4:8] = new_file_size.to_bytes(4, "little")
        self.riff_header.file_size = new_file_size

    def to_bytes(self) -> bytes:
        """Serialize the AT3 audio stream to bytes with recalculated RIFF size."""
        self._sync_riff_size()
        return bytes(self.raw_data)

    def save(self, path: Union[str, os.PathLike]):
        """Save the AT3 audio stream to a file."""
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    def _parse_chunks(self):
        """Index all sub-chunks in the RIFF container."""
        self._chunks.clear()
        self._chunk_map.clear()

        offset = 12
        limit = len(self.raw_data)

        while offset + 8 <= limit:
            cid = bytes(self.raw_data[offset : offset + 4])
            csize = unpack_from("<I", self.raw_data, offset + 4)[0]

            if offset + 8 + csize > limit:
                raise ParseError(
                    f"Chunk {cid!r} claims size {csize} which exceeds container boundary (limit={limit})"
                )

            info = _ChunkInfo(
                chunk_id=cid,
                header_offset=offset,
                data_offset=offset + 8,
                data_size=csize,
            )
            self._chunks.append(info)
            self._chunk_map[cid] = info

            # Move to next chunk (padded to 2-byte boundary)
            offset += 8 + csize + (csize % 2)

    def _parse_format(self):
        """Parse 'fmt ' chunk and determine codec, channels, sample rate, bitrate."""
        fmt_info = self._chunk_map.get(FMT_CHUNK_ID)
        if not fmt_info or fmt_info.data_size < 16:
            raise ParseError("Missing or truncated 'fmt ' chunk in AT3 file")

        wfmt = WaveFormatExStruct.from_bytes(
            self.raw_data, offset=fmt_info.data_offset, endian="<"
        )
        self.channels = wfmt.nChannels
        self.sample_rate = wfmt.nSamplesPerSec
        self.frame_size = wfmt.nBlockAlign
        self.bitrate_kbps = (wfmt.nAvgBytesPerSec * 8) // 1000

        extra_data = self.raw_data[
            fmt_info.data_offset + 16 : fmt_info.data_offset + fmt_info.data_size
        ]

        if wfmt.wFormatTag == ATRAC3_FORMAT_TAG:
            self.codec = AT3Codec.ATRAC3
            self.samples_per_frame = 1024
        elif wfmt.wFormatTag == WAVE_FORMAT_EXTENSIBLE:
            if ATRAC3PLUS_GUID in extra_data:
                self.codec = AT3Codec.ATRAC3PLUS
                self.samples_per_frame = 2048
            elif ATRAC3_GUID in extra_data:
                self.codec = AT3Codec.ATRAC3
                self.samples_per_frame = 1024
            else:
                self.codec = AT3Codec.UNKNOWN
                self.samples_per_frame = 1024
        else:
            self.codec = AT3Codec.UNKNOWN
            self.samples_per_frame = 1024

    def _parse_fact(self):
        """Parse 'fact' chunk for total samples and encoder priming delay."""
        fact_info = self._chunk_map.get(FACT_CHUNK_ID)
        if fact_info and fact_info.data_size >= 4:
            self.total_samples = unpack_from(
                "<I", self.raw_data, fact_info.data_offset
            )[0]
            if fact_info.data_size >= 8:
                self.delay_samples = unpack_from(
                    "<I", self.raw_data, fact_info.data_offset + 4
                )[0]
        else:
            # Fallback estimation based on data chunk size
            data_info = self._chunk_map.get(DATA_CHUNK_ID)
            if data_info and self.frame_size > 0:
                num_frames = data_info.data_size // self.frame_size
                self.total_samples = num_frames * self.samples_per_frame

    def _parse_loop(self):
        """Parse 'smpl' chunk for loop point start and end samples."""
        smpl_info = self._chunk_map.get(SMPL_CHUNK_ID)
        if not smpl_info or smpl_info.data_size < 36:
            self.loop_point = None
            return

        header = SmplChunkHeaderStruct.from_bytes(
            self.raw_data, offset=smpl_info.data_offset, endian="<"
        )
        if header.cSampleLoops < 1 or smpl_info.data_size < 36 + 24:
            self.loop_point = None
            return

        loop_entry = SmplLoopEntryStruct.from_bytes(
            self.raw_data, offset=smpl_info.data_offset + 36, endian="<"
        )
        sr = self.sample_rate if self.sample_rate > 0 else 44100
        self.loop_point = AT3LoopPoint(
            start_sample=loop_entry.dwStart,
            end_sample=loop_entry.dwEnd,
            start_seconds=round(loop_entry.dwStart / sr, 4),
            end_seconds=round(loop_entry.dwEnd / sr, 4),
        )

    @property
    def is_looped(self) -> bool:
        """Returns True if the audio file contains a valid seamless loop point."""
        return self.loop_point is not None

    @property
    def duration_seconds(self) -> float:
        """Total duration of the audio in seconds."""
        if self.sample_rate <= 0:
            return 0.0
        return round(self.total_samples / self.sample_rate, 4)

    @property
    def audio_data(self) -> bytes:
        """Raw compressed audio frame payload contained in the 'data' chunk."""
        data_info = self._chunk_map.get(DATA_CHUNK_ID)
        if not data_info:
            return b""
        return bytes(
            self.raw_data[
                data_info.data_offset : data_info.data_offset + data_info.data_size
            ]
        )

    def set_loop(self, start_sample: int, end_sample: int):
        """
        Configure or update the seamless BGM loop points.
        If a 'smpl' chunk already exists, updates dwStart and dwEnd.
        If absent, synthesizes and injects a 68-byte 'smpl' chunk before 'data'.
        """
        if start_sample < 0:
            raise ValueError(
                f"start_sample ({start_sample}) must be non-negative"
            )
        if end_sample <= start_sample:
            raise ValueError(
                f"end_sample ({end_sample}) must be greater than start_sample ({start_sample})"
            )
        if self.total_samples > 0 and end_sample > self.total_samples:
            raise ValueError(
                f"end_sample ({end_sample}) cannot exceed total_samples ({self.total_samples})"
            )

        smpl_info = self._chunk_map.get(SMPL_CHUNK_ID)
        sr = self.sample_rate if self.sample_rate > 0 else 44100

        if smpl_info and smpl_info.data_size >= 60:
            # Ensure cSampleLoops >= 1 so decoders and _parse_loop recognize the loop
            current_loops = unpack_from(
                "<I", self.raw_data, smpl_info.data_offset + 28
            )[0]
            if current_loops < 1:
                self.raw_data[
                    smpl_info.data_offset + 28 : smpl_info.data_offset + 32
                ] = (1).to_bytes(4, "little")

            # Update existing smpl chunk in place
            entry_offset = smpl_info.data_offset + 36
            # dwStart is at offset 8 within SmplLoopEntryStruct, dwEnd at offset 12
            self.raw_data[entry_offset + 8 : entry_offset + 12] = (
                start_sample.to_bytes(4, "little")
            )
            self.raw_data[entry_offset + 12 : entry_offset + 16] = (
                end_sample.to_bytes(4, "little")
            )
            self._sync_riff_size()
        else:
            # Construct a brand new smpl chunk (36 header + 24 loop entry = 60 bytes data)
            hdr = SmplChunkHeaderStruct()
            hdr.dwManufacturer = 0
            hdr.dwProduct = 0
            hdr.dwSamplePeriod = int(1_000_000_000 / sr) if sr > 0 else 22675
            hdr.dwMIDIUnityNote = 60
            hdr.dwMIDIPitchFraction = 0
            hdr.dwSMPTEFormat = 0
            hdr.dwSMPTEOffset = 0
            hdr.cSampleLoops = 1
            hdr.cbSamplerData = 0

            entry = SmplLoopEntryStruct()
            entry.dwIdentifier = 0
            entry.dwType = 0  # Forward loop
            entry.dwStart = start_sample
            entry.dwEnd = end_sample
            entry.dwFraction = 0
            entry.dwPlayCount = 0

            smpl_payload = hdr.to_bytes(endian="<") + entry.to_bytes(endian="<")
            smpl_chunk_bytes = (
                SMPL_CHUNK_ID + len(smpl_payload).to_bytes(4, "little") + smpl_payload
            )

            # Insert before 'data' chunk if present, else append
            data_info = self._chunk_map.get(DATA_CHUNK_ID)
            insert_pos = (
                data_info.header_offset if data_info else len(self.raw_data)
            )

            self.raw_data[insert_pos:insert_pos] = smpl_chunk_bytes
            self._sync_riff_size()
            self._parse_chunks()

        self.loop_point = AT3LoopPoint(
            start_sample=start_sample,
            end_sample=end_sample,
            start_seconds=round(start_sample / sr, 4),
            end_seconds=round(end_sample / sr, 4),
        )

    def remove_loop(self):
        """Remove the 'smpl' chunk from the audio container, converting to one-shot."""
        smpl_info = self._chunk_map.get(SMPL_CHUNK_ID)
        if not smpl_info:
            self.loop_point = None
            return

        chunk_full_len = (
            8 + smpl_info.data_size + (smpl_info.data_size % 2)
        )
        start = smpl_info.header_offset
        end = start + chunk_full_len

        del self.raw_data[start:end]
        self.loop_point = None
        self._sync_riff_size()
        self._parse_chunks()

    def replace_data(
        self, new_frames: bytes, total_samples: Optional[int] = None
    ):
        """
        Replace the compressed audio frame data in the 'data' chunk and update 'fact' samples.
        """
        data_info = self._chunk_map.get(DATA_CHUNK_ID)
        if not data_info:
            raise ParseError("Cannot replace audio data: missing 'data' chunk")

        # Determine new sample count
        if total_samples is None:
            if self.frame_size > 0:
                num_frames = len(new_frames) // self.frame_size
                total_samples = num_frames * self.samples_per_frame
            else:
                total_samples = self.total_samples

        self.total_samples = total_samples

        # Update fact chunk sample count if present
        fact_info = self._chunk_map.get(FACT_CHUNK_ID)
        if fact_info and fact_info.data_size >= 4:
            self.raw_data[
                fact_info.data_offset : fact_info.data_offset + 4
            ] = total_samples.to_bytes(4, "little")

        # Replace data chunk content
        old_data_len = data_info.data_size + (data_info.data_size % 2)
        new_csize = len(new_frames)
        new_chunk_header = (
            DATA_CHUNK_ID
            + new_csize.to_bytes(4, "little")
            + new_frames
            + (b"\x00" if new_csize % 2 != 0 else b"")
        )

        old_start = data_info.header_offset
        old_end = data_info.data_offset + old_data_len

        self.raw_data[old_start:old_end] = new_chunk_header
        self._sync_riff_size()
        self._parse_chunks()


def create_synthetic_at3(
    codec: Union[str, AT3Codec] = AT3Codec.ATRAC3,
    sample_rate: int = 44100,
    channels: int = 2,
    bitrate_kbps: int = 132,
    num_frames: int = 8,
    loop_start_sample: Optional[int] = None,
    loop_end_sample: Optional[int] = None,
) -> bytes:
    """
    Construct a valid synthetic Sony ATRAC3 or ATRAC3plus RIFF WAVE audio stream for testing.
    Includes RIFF header, fmt, fact, optional smpl loop points, and dummy frame data.
    """
    codec_enum = (
        AT3Codec(codec) if isinstance(codec, str) else codec
    )
    is_atrac3plus = codec_enum == AT3Codec.ATRAC3PLUS

    # Frame size calculations
    if is_atrac3plus:
        frame_size = 512
        samples_per_frame = 2048
        wformat_tag = WAVE_FORMAT_EXTENSIBLE
    else:
        frame_size = 384
        samples_per_frame = 1024
        wformat_tag = ATRAC3_FORMAT_TAG

    avg_bytes_per_sec = (bitrate_kbps * 1000) // 8

    # 1. 'fmt ' chunk payload
    wfmt = WaveFormatExStruct()
    wfmt.wFormatTag = wformat_tag
    wfmt.nChannels = channels
    wfmt.nSamplesPerSec = sample_rate
    wfmt.nAvgBytesPerSec = avg_bytes_per_sec
    wfmt.nBlockAlign = frame_size
    wfmt.wBitsPerSample = 0

    fmt_builder = io.BytesIO()
    fmt_builder.write(wfmt.to_bytes(endian="<"))

    if is_atrac3plus:
        # cbSize = 34 bytes (wValidBitsPerSample=0, dwChannelMask=3, SubFormat GUID, etc.)
        fmt_builder.write((34).to_bytes(2, "little"))  # cbSize
        fmt_builder.write((0).to_bytes(2, "little"))  # wValidBitsPerSample
        fmt_builder.write((3 if channels == 2 else 1).to_bytes(4, "little"))  # dwChannelMask
        fmt_builder.write(ATRAC3PLUS_GUID)  # 16 bytes SubFormat GUID
        fmt_builder.write(b"\x00" * 12)  # Extra Sony config
    else:
        # Atrac3FormatExtraStruct (14 bytes)
        extra = Atrac3FormatExtraStruct()
        extra.cbSize = 14
        extra.wSubFormat = 1
        extra.nSamplesPerBlock = samples_per_frame
        extra.wChannelMask = 3 if channels == 2 else 1
        extra.wCodingMode = 0
        extra.wReserved = 0
        fmt_builder.write(extra.to_bytes(endian="<"))

    fmt_payload = fmt_builder.getvalue()

    # 2. 'fact' chunk payload (8 bytes)
    total_samples = num_frames * samples_per_frame
    delay_samples = 2048 if is_atrac3plus else 1024
    fact_struct = FactChunkStruct()
    fact_struct.total_samples = total_samples
    fact_struct.delay_samples = delay_samples
    fact_payload = fact_struct.to_bytes(endian="<")

    # 3. 'smpl' chunk payload (optional)
    smpl_payload = b""
    if loop_start_sample is not None and loop_end_sample is not None:
        hdr = SmplChunkHeaderStruct()
        hdr.dwManufacturer = 0
        hdr.dwProduct = 0
        hdr.dwSamplePeriod = int(1_000_000_000 / sample_rate)
        hdr.dwMIDIUnityNote = 60
        hdr.dwMIDIPitchFraction = 0
        hdr.dwSMPTEFormat = 0
        hdr.dwSMPTEOffset = 0
        hdr.cSampleLoops = 1
        hdr.cbSamplerData = 0

        entry = SmplLoopEntryStruct()
        entry.dwIdentifier = 0
        entry.dwType = 0
        entry.dwStart = loop_start_sample
        entry.dwEnd = loop_end_sample
        entry.dwFraction = 0
        entry.dwPlayCount = 0
        smpl_payload = hdr.to_bytes(endian="<") + entry.to_bytes(endian="<")

    # 4. 'data' chunk payload
    data_payload = b"\xAA\x55" * (num_frames * frame_size // 2)

    # Build entire RIFF container
    out = io.BytesIO()
    # Placeholder for RIFF header (12 bytes)
    out.write(b"\x00" * 12)

    def write_chunk(cid: bytes, payload: bytes):
        out.write(cid)
        out.write(len(payload).to_bytes(4, "little"))
        out.write(payload)
        if len(payload) % 2 != 0:
            out.write(b"\x00")

    write_chunk(FMT_CHUNK_ID, fmt_payload)
    write_chunk(FACT_CHUNK_ID, fact_payload)
    if smpl_payload:
        write_chunk(SMPL_CHUNK_ID, smpl_payload)
    write_chunk(DATA_CHUNK_ID, data_payload)

    result = bytearray(out.getvalue())

    # Write final RIFF header
    file_size = len(result) - 8
    hdr = RiffHeaderStruct()
    hdr.magic = RIFF_MAGIC
    hdr.file_size = file_size
    hdr.form_type = WAVE_MAGIC
    result[:12] = hdr.to_bytes(endian="<")

    return bytes(result)
