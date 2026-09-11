"""
miorom.audio.sappy
~~~~~~~~~~~~~~~~~~
Nintendo Game Boy Advance M4A (Music Player 2000 / Sappy) Sound Engine
Scanner, Voice Table Parser, and DirectSound Sample Ripper.

Parses song tables, voice tables, instrument envelopes, and exports
8-bit signed PCM audio samples to standard RIFF WAVE (.wav) files.
"""

from dataclasses import dataclass, field
import struct
from typing import Dict, List, Optional, Tuple

from miorom.errors import ParseError
from miorom.result import MioRomResult


GBA_ROM_BASE = 0x08000000
GBA_ROM_END = 0x0A000000


def is_gba_rom_ptr(ptr: int, rom_len: int) -> bool:
    """Validates whether a 32-bit integer is a valid pointer into the GBA ROM space."""
    if ptr < GBA_ROM_BASE or ptr >= GBA_ROM_END:
        return False
    off = ptr & 0x01FFFFFF
    return off < rom_len


def gba_ptr_to_offset(ptr: int) -> int:
    """Converts a 32-bit GBA memory pointer (0x08xxxxxx) to a ROM byte offset."""
    return ptr & 0x01FFFFFF


def offset_to_gba_ptr(offset: int) -> int:
    """Converts a ROM byte offset to a 32-bit GBA memory pointer."""
    return GBA_ROM_BASE | (offset & 0x01FFFFFF)


@dataclass
class SappySample(MioRomResult):
    """Represents a GBA DirectSound PCM sample."""
    sample_rate: int
    loop_start: int
    loop_enabled: bool
    data: bytes

    @property
    def length(self) -> int:
        return len(self.data)

    def to_wav(self) -> bytes:
        """Encodes raw signed 8-bit PCM data to a standard RIFF WAVE mono buffer."""
        # Convert signed 8-bit (-128..127) to standard WAV unsigned 8-bit (0..255)
        pcm_u8 = bytearray((b + 128) & 0xFF for b in self.data)

        # Standard RIFF WAVE header (44 bytes)
        file_size_minus_8 = 36 + len(pcm_u8)
        byte_rate = self.sample_rate  # 1 channel * 8 bits / 8
        block_align = 1
        bits_per_sample = 8

        wav = bytearray()
        wav.extend(b"RIFF")
        wav.extend(struct.pack("<I", file_size_minus_8))
        wav.extend(b"WAVE")
        wav.extend(b"fmt ")
        wav.extend(struct.pack("<I", 16))              # Subchunk1 size (16 for PCM)
        wav.extend(struct.pack("<H", 1))               # Audio format (1 = PCM)
        wav.extend(struct.pack("<H", 1))               # Num channels (1 = Mono)
        wav.extend(struct.pack("<I", self.sample_rate))
        wav.extend(struct.pack("<I", byte_rate))
        wav.extend(struct.pack("<H", block_align))
        wav.extend(struct.pack("<H", bits_per_sample))
        wav.extend(b"data")
        wav.extend(struct.pack("<I", len(pcm_u8)))
        wav.extend(pcm_u8)
        return bytes(wav)


@dataclass
class SappyInstrument(MioRomResult):
    """Represents an instrument definition within a Sappy Voice Table."""
    instrument_type: int
    root_key: int
    pan_sweep: int
    sample_ptr: int
    attack: int
    decay: int
    sustain: int
    release: int
    sub_table_ptr: Optional[int] = None
    sample: Optional[SappySample] = None

    @property
    def is_direct_sound(self) -> bool:
        return (self.instrument_type & 0x03) in (0, 1)

    @property
    def is_drum_kit(self) -> bool:
        return (self.instrument_type & 0x40) != 0

    @property
    def is_key_split(self) -> bool:
        return (self.instrument_type & 0x80) != 0


@dataclass
class SappySongEntry(MioRomResult):
    """Represents a song entry in the Sappy Song Table."""
    song_index: int
    header_ptr: int
    header_offset: int
    player_group: int
    track_count: int = 0
    voice_table_ptr: int = 0
    voice_table_offset: int = 0


class SappyCodec:
    """
    Encoder and decoder for GBA DirectSound PCM samples and Sappy structures.
    """

    @classmethod
    def parse_sample(cls, rom: bytes, offset: int) -> SappySample:
        """
        Parses a Sappy SoundSample header and its following signed 8-bit PCM data.
        Header is 16 bytes: flags (4B), pitch (4B), loop_start (4B), length (4B).
        """
        if offset + 16 > len(rom):
            raise ParseError(f"Offset 0x{offset:X} out of range for Sappy sample header.")

        flags, pitch, loop_start, length = struct.unpack_from("<IIII", rom, offset)
        loop_enabled = (flags & 0x4000) != 0

        # Calculate sample rate in Hz
        if pitch > 4000:
            sample_rate = pitch
        elif pitch > 0:
            sample_rate = (pitch * 1024) >> 10
            if sample_rate < 4000:
                sample_rate = 13379  # Standard GBA default
        else:
            sample_rate = 13379

        sample_data_offset = offset + 16
        if sample_data_offset + length > len(rom):
            actual_len = max(0, len(rom) - sample_data_offset)
        else:
            actual_len = length

        # Raw GBA 8-bit signed PCM data (0x00 is center, 0x80 is -128)
        raw_slice = rom[sample_data_offset : sample_data_offset + actual_len]

        return SappySample(
            sample_rate=sample_rate,
            loop_start=loop_start,
            loop_enabled=loop_enabled,
            data=bytes(raw_slice),
        )

    @classmethod
    def encode_sample(
        cls,
        data: bytes,
        sample_rate: int = 13379,
        loop_start: int = 0,
        loop_enabled: bool = False,
    ) -> bytes:
        """
        Encodes signed 8-bit PCM data into a GBA SoundSample 16-byte header and payload.
        """
        flags = 0x4000 if loop_enabled else 0
        pitch = sample_rate
        header = struct.pack("<IIII", flags, pitch, loop_start, len(data))
        raw_bytes = bytes((b & 0xFF) for b in data)
        return header + raw_bytes


class SappyScanner:
    """
    Automated scanner for Nintendo GBA M4A / Sappy sound engine tables and voices.
    """

    @classmethod
    def scan_song_tables(
        cls,
        rom: bytes,
        min_consecutive_songs: int = 8,
    ) -> List[int]:
        """
        Scans a GBA ROM for candidate Sappy Song Tables.
        Each entry is 8 bytes: header_ptr (4B, 0x08xxxxxx), ms (2B, 0..15), me (2B).
        """
        rom_len = len(rom)
        candidates: List[int] = []

        # Scan 4-byte aligned offsets
        for off in range(0, rom_len - (min_consecutive_songs * 8), 4):
            valid_count = 0
            curr_off = off
            while curr_off + 8 <= rom_len:
                hdr_ptr, ms, me = struct.unpack_from("<IHH", rom, curr_off)
                if not is_gba_rom_ptr(hdr_ptr, rom_len):
                    break
                if ms > 15:
                    break
                # Validate song header target
                hdr_off = gba_ptr_to_offset(hdr_ptr)
                if hdr_off + 8 > rom_len:
                    break
                tracks = rom[hdr_off]
                if tracks == 0 or tracks > 16:
                    break

                valid_count += 1
                curr_off += 8

            if valid_count >= min_consecutive_songs:
                candidates.append(off)

        return candidates

    @classmethod
    def parse_song_table(
        cls,
        rom: bytes,
        table_offset: int,
        max_songs: int = 256,
    ) -> List[SappySongEntry]:
        """
        Parses consecutive song entries from a Sappy Song Table offset.
        """
        rom_len = len(rom)
        entries: List[SappySongEntry] = []

        curr_off = table_offset
        idx = 0
        while curr_off + 8 <= rom_len and idx < max_songs:
            hdr_ptr, ms, _ = struct.unpack_from("<IHH", rom, curr_off)
            if not is_gba_rom_ptr(hdr_ptr, rom_len):
                break
            if ms > 15:
                break

            hdr_off = gba_ptr_to_offset(hdr_ptr)
            if hdr_off + 8 > rom_len:
                break
            track_count = rom[hdr_off]
            if track_count == 0 or track_count > 16:
                break

            voice_table_ptr = struct.unpack_from("<I", rom, hdr_off + 4)[0]
            voice_table_off = (
                gba_ptr_to_offset(voice_table_ptr)
                if is_gba_rom_ptr(voice_table_ptr, rom_len)
                else 0
            )

            entries.append(
                SappySongEntry(
                    song_index=idx,
                    header_ptr=hdr_ptr,
                    header_offset=hdr_off,
                    player_group=ms,
                    track_count=track_count,
                    voice_table_ptr=voice_table_ptr,
                    voice_table_offset=voice_table_off,
                )
            )
            curr_off += 8
            idx += 1

        return entries

    @classmethod
    def parse_voice_table(
        cls,
        rom: bytes,
        table_offset: int,
        count: int = 128,
    ) -> List[SappyInstrument]:
        """
        Parses instrument records from a Sappy Voice Table (12 bytes per instrument).
        """
        rom_len = len(rom)
        instruments: List[SappyInstrument] = []

        for i in range(count):
            entry_off = table_offset + i * 12
            if entry_off + 12 > rom_len:
                break

            inst_type, root_key, _, pan_sweep = struct.unpack_from("BBBB", rom, entry_off)
            sample_ptr = struct.unpack_from("<I", rom, entry_off + 4)[0]
            attack, decay, sustain, release = struct.unpack_from("BBBB", rom, entry_off + 8)

            sub_table_ptr = None
            sample_obj = None

            if (inst_type & 0x40) or (inst_type & 0x80):
                sub_table_ptr = sample_ptr
            elif (inst_type & 0x03) in (0, 1) and is_gba_rom_ptr(sample_ptr, rom_len):
                sample_off = gba_ptr_to_offset(sample_ptr)
                try:
                    sample_obj = SappyCodec.parse_sample(rom, sample_off)
                except Exception:
                    sample_obj = None

            instruments.append(
                SappyInstrument(
                    instrument_type=inst_type,
                    root_key=root_key,
                    pan_sweep=pan_sweep,
                    sample_ptr=sample_ptr,
                    attack=attack,
                    decay=decay,
                    sustain=sustain,
                    release=release,
                    sub_table_ptr=sub_table_ptr,
                    sample=sample_obj,
                )
            )

        return instruments

    @classmethod
    def rip_samples(
        cls,
        rom: bytes,
        voice_table_offset: int,
    ) -> Dict[int, SappySample]:
        """
        Extracts all DirectSound samples from a voice table, mapping instrument index to SappySample.
        """
        instruments = cls.parse_voice_table(rom, voice_table_offset)
        samples: Dict[int, SappySample] = {}
        for idx, inst in enumerate(instruments):
            if inst.sample is not None:
                samples[idx] = inst.sample
        return samples
