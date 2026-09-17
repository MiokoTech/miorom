"""
miorom.platforms.wii.brsar
~~~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo Wii BRSAR (Binary Revolution Sound Archive — .brsar) Engine.

Pure-Python, zero-dependency parser, builder, extractor, and voice undubbing engine
for Nintendo NW4R monolithic sound archives (.brsar).
Used across Wii titles (e.g., Mario Kart Wii, Super Smash Bros. Brawl, Super Mario Galaxy,
The Legend of Zelda: Twilight Princess, Xenoblade Chronicles, Fire Emblem: Radiant Dawn).

Features:
- Full parsing and serialization of RSAR header, SYMB, INFO, and FILE sections.
- Resolves developer symbol strings (SYMB) to Sound IDs and internal File IDs.
- High-level RWSD (Revolution Wave Sound Data) sub-file parser and builder.
- Bi-directional WAV bridge: extract DSP-ADPCM and PCM16 voice/SFX clips to standard WAV,
  and inject custom WAV audio into the archive with automatic DSP-ADPCM encoding.
- Automatic 32-byte alignment and relational offset/size recalculation across all tables.
- One-click cross-archive voice transfer engine (apply_undub_from) for undub projects.
- 100% zero external dependencies (no ffmpeg, no numpy, no C extensions).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Union

from miorom.audio.dsp_adpcm import DEFAULT_DSP_COEFFS, DSPADPCMCodec
from miorom.audio.wav_codec import WavCodec, WavSound
from miorom.core.schema import (
    U16,
    U32,
    BinaryStruct,
    RawBytes,
)
from miorom.errors import ParseError
from miorom.platforms.wii.brstm import encode_dsp_adpcm_channel

# ==============================================================================
# Constants & Magic Identifiers
# ==============================================================================

RSAR_MAGIC = b"RSAR"
SYMB_MAGIC = b"SYMB"
INFO_MAGIC = b"INFO"
FILE_MAGIC = b"FILE"
RWSD_MAGIC = b"RWSD"
WSD1_MAGIC = b"WSD1"
DATA_MAGIC = b"DATA"

SOUND_TYPE_SEQ = 0
SOUND_TYPE_WSD = 1
SOUND_TYPE_STRM = 2

CODEC_PCM8 = 0
CODEC_PCM16 = 1
CODEC_DSP_ADPCM = 2

ALIGNMENT_32 = 32


# ==============================================================================
# Declarative Binary Struct Definitions (Low-Level Primitives)
# ==============================================================================

class BRSARHeaderStruct(BinaryStruct):
    """
    Root 0x40-byte header of a Nintendo Wii .brsar archive.
    """
    _endian = ">"
    magic = RawBytes(4, default=RSAR_MAGIC)
    bom = U16(default=0xFEFF)
    version = U16(default=0x0104)
    file_size = U32(default=0)
    header_size = U16(default=0x0040)
    num_sections = U16(default=3)
    symb_offset = U32(default=0x0040)
    symb_size = U32(default=0)
    info_offset = U32(default=0)
    info_size = U32(default=0)
    file_offset = U32(default=0)
    file_size_sec = U32(default=0)
    _reserved = RawBytes(24, default=b"\x00" * 24)


class SYMBHeaderStruct(BinaryStruct):
    """
    Header of the SYMB (Symbol) section mapping IDs to developer string names.
    """
    _endian = ">"
    magic = RawBytes(4, default=SYMB_MAGIC)
    size = U32(default=0)
    string_table_sound_offset = U32(default=0x18)
    string_table_player_offset = U32(default=0)
    string_table_group_offset = U32(default=0)
    string_table_bank_offset = U32(default=0)


class INFOHeaderStruct(BinaryStruct):
    """
    Header of the INFO section holding sound metadata and file indexes.
    """
    _endian = ">"
    magic = RawBytes(4, default=INFO_MAGIC)
    size = U32(default=0)
    sound_table_offset = U32(default=0x1C)
    bank_table_offset = U32(default=0)
    player_table_offset = U32(default=0)
    file_table_offset = U32(default=0)
    group_table_offset = U32(default=0)


class FILEHeaderStruct(BinaryStruct):
    """
    Header of the FILE section containing the pool of raw sub-files.
    """
    _endian = ">"
    magic = RawBytes(4, default=FILE_MAGIC)
    size = U32(default=0)


class RWSDHeaderStruct(BinaryStruct):
    """
    Header of an RWSD (Revolution Wave Sound Data) sub-file.
    """
    _endian = ">"
    magic = RawBytes(4, default=RWSD_MAGIC)
    bom = U16(default=0xFEFF)
    version = U16(default=0x0102)
    filesize = U32(default=0)
    header_size = U16(default=0x0020)
    num_blocks = U16(default=2)
    wsd1_offset = U32(default=0x0020)
    wsd1_size = U32(default=0)
    data_offset = U32(default=0)
    data_size = U32(default=0)


class WSD1HeaderStruct(BinaryStruct):
    """
    Header of the WSD1 metadata block inside an RWSD sub-file.
    """
    _endian = ">"
    magic = RawBytes(4, default=WSD1_MAGIC)
    size = U32(default=0)


class DATAHeaderStruct(BinaryStruct):
    """
    Header of the DATA audio payload block inside an RWSD sub-file.
    """
    _endian = ">"
    magic = RawBytes(4, default=DATA_MAGIC)
    size = U32(default=0)


# ==============================================================================
# Analytical Data Models
# ==============================================================================

@dataclass
class SoundEntry:
    """
    Represents a single sound entity within the BRSAR archive.
    """
    sound_id: int
    name: str
    sound_type: str        # "WSD", "SEQ", or "STRM"
    file_id: int
    file_offset: int
    file_size: int
    volume: int = 100
    pan: int = 64
    priority: int = 64

    @property
    def is_wave(self) -> bool:
        """True if this sound is a wave sound (RWSD payload)."""
        return self.sound_type == "WSD"


@dataclass
class UndubTransferReport:
    """
    Statistical summary of a cross-archive voice undub transfer operation.
    """
    total_scanned: int
    transferred_count: int
    skipped_count: int
    transferred_names: List[str]
    source_archive_name: str = ""


# ==============================================================================
# High-Level RWSD Sub-File Handler
# ==============================================================================

class RWSDFile:
    """
    High-level representation of an RWSD (Wave Sound Data) sub-file.
    Encapsulates audio parameters, DSP-ADPCM / PCM16 sample payload, and WAV conversion.
    """

    def __init__(
        self,
        samples: List[int],
        sample_rate: int = 32000,
        channels: int = 1,
        codec: int = CODEC_DSP_ADPCM,
        loop_flag: bool = False,
        loop_start: int = 0,
        coefs: Optional[List[int]] = None,
    ):
        self.samples = samples
        self.sample_rate = sample_rate
        self.channels = channels
        self.codec = codec
        self.loop_flag = loop_flag
        self.loop_start = loop_start
        self.coefs = coefs or list(DEFAULT_DSP_COEFFS)

    @classmethod
    def from_bytes(cls, data: bytes) -> RWSDFile:
        """
        Parses an RWSD sub-file from raw binary bytes.
        """
        if len(data) < 0x20:
            raise ParseError(f"RWSD data too short ({len(data)} < 32 bytes)")

        header = RWSDHeaderStruct.from_bytes(data, offset=0)
        if header.magic != RWSD_MAGIC:
            raise ParseError(f"Invalid RWSD magic: {header.magic!r} (expected {RWSD_MAGIC!r})")

        wsd1_off = header.wsd1_offset
        data_off = header.data_offset

        if wsd1_off >= len(data) or data_off >= len(data):
            raise ParseError("RWSD internal chunk offsets exceed file bounds")

        # Parse WSD1
        wsd1_hdr = WSD1HeaderStruct.from_bytes(data, offset=wsd1_off)
        if wsd1_hdr.magic != WSD1_MAGIC:
            raise ParseError(f"Invalid WSD1 magic: {wsd1_hdr.magic!r}")

        wsd1_data = data[wsd1_off + 8 : wsd1_off + wsd1_hdr.size]
        # Layout of WSD1 content:
        # 0x00: count (U32)
        # 0x04: offsets...
        # Wave descriptor record:
        # codec (U8), loop_flag (U8), channels (U8), pad (U8), sample_rate (U16),
        # pad2 (U16), loop_start (U32), num_samples (U32), sample_offset (U32), channel_info_offset (U32)
        if len(wsd1_data) < 24:
            raise ParseError("WSD1 block payload too short")

        # Read wave descriptor fields
        codec = wsd1_data[4]
        loop_flag = bool(wsd1_data[5])
        channels = max(1, wsd1_data[6])
        sample_rate = int.from_bytes(wsd1_data[8:10], "big")
        loop_start = int.from_bytes(wsd1_data[12:16], "big")
        num_samples = int.from_bytes(wsd1_data[16:20], "big")
        sample_offset = int.from_bytes(wsd1_data[20:24], "big")

        # Parse DATA block
        data_hdr = DATAHeaderStruct.from_bytes(data, offset=data_off)
        if data_hdr.magic != DATA_MAGIC:
            raise ParseError(f"Invalid DATA magic: {data_hdr.magic!r}")

        raw_audio_payload = data[data_off + 8 : data_off + data_hdr.size]

        # Extract coefficients if DSP-ADPCM
        coefs = list(DEFAULT_DSP_COEFFS)
        if len(wsd1_data) >= 28:
            chan_info_off = int.from_bytes(wsd1_data[24:28], "big")
            if chan_info_off + 32 <= len(raw_audio_payload):
                coefs = [
                    int.from_bytes(raw_audio_payload[chan_info_off + i * 2 : chan_info_off + i * 2 + 2], "big", signed=True)
                    for i in range(16)
                ]

        # Decode audio samples
        samples: List[int] = []
        if codec == CODEC_DSP_ADPCM:
            audio_bytes = raw_audio_payload[sample_offset:]
            decoded = DSPADPCMCodec.decode(audio_bytes, coefs=coefs)
            samples = decoded[:num_samples] if num_samples > 0 else decoded
        elif codec == CODEC_PCM16:
            audio_bytes = raw_audio_payload[sample_offset:]
            count = len(audio_bytes) // 2
            samples = [
                int.from_bytes(audio_bytes[i * 2 : i * 2 + 2], "big", signed=True)
                for i in range(count)
            ]
            if num_samples > 0:
                samples = samples[:num_samples]
        else:
            raise ParseError(f"Unsupported RWSD codec: {codec}")

        return cls(
            samples=samples,
            sample_rate=sample_rate if sample_rate > 0 else 32000,
            channels=channels,
            codec=codec,
            loop_flag=loop_flag,
            loop_start=loop_start,
            coefs=coefs,
        )

    @classmethod
    def from_wav(
        cls,
        wav_input: Union[WavSound, bytes, str, os.PathLike],
        codec: int = CODEC_DSP_ADPCM,
    ) -> RWSDFile:
        """
        Creates an RWSDFile from a WavSound object, raw WAV file bytes, or a filesystem path.
        """
        if isinstance(wav_input, (str, os.PathLike)):
            with open(wav_input, "rb") as f:
                wav_sound = WavCodec.decode(f.read())
        elif isinstance(wav_input, bytes):
            wav_sound = WavCodec.decode(wav_input)
        elif isinstance(wav_input, WavSound):
            wav_sound = wav_input
        else:
            raise TypeError(f"Invalid WAV input type: {type(wav_input)}")

        # For RWSD voice clips, convert to mono if multi-channel
        mono_sound = wav_sound.to_mono() if wav_sound.channels > 1 else wav_sound

        return cls(
            samples=mono_sound.samples,
            sample_rate=mono_sound.sample_rate,
            channels=1,
            codec=codec,
            loop_flag=False,
            loop_start=0,
            coefs=list(DEFAULT_DSP_COEFFS),
        )

    def to_wav(self) -> WavSound:
        """
        Exports the in-memory audio samples as a standard 16-bit uncompressed WavSound.
        """
        return WavSound(
            samples=list(self.samples),
            sample_rate=self.sample_rate,
            channels=self.channels,
            bits_per_sample=16,
        )

    def to_wav_bytes(self) -> bytes:
        """
        Encodes the audio samples into standard RIFF/WAVE file bytes.
        """
        return WavCodec.encode(self.to_wav())

    def to_bytes(self) -> bytes:
        """
        Serializes this RWSD sub-file into binary format with proper 32-byte alignment.
        """
        # 1. Build DATA block
        if self.codec == CODEC_DSP_ADPCM:
            adpcm_data, coefs, _, _ = encode_dsp_adpcm_channel(self.samples, coefs=self.coefs)
            self.coefs = coefs

            # Store coefficients at start of DATA payload (32 bytes), followed by ADPCM samples
            coef_bytes = bytearray()
            for c in self.coefs:
                coef_bytes.extend(c.to_bytes(2, "big", signed=True))
            chan_info_offset = 0
            sample_offset = 32

            data_payload = bytes(coef_bytes) + adpcm_data
        elif self.codec == CODEC_PCM16:
            chan_info_offset = 0
            sample_offset = 0
            pcm_bytes = bytearray()
            for s in self.samples:
                clamped = max(-32768, min(32767, s))
                pcm_bytes.extend(clamped.to_bytes(2, "big", signed=True))
            data_payload = bytes(pcm_bytes)
        else:
            raise ParseError(f"Unsupported serialization codec: {self.codec}")

        # Pad DATA payload to 32-byte alignment
        data_pad = (32 - (len(data_payload) % 32)) % 32
        data_payload += b"\x00" * data_pad

        data_chunk_size = 8 + len(data_payload)
        data_chunk = (
            DATA_MAGIC
            + data_chunk_size.to_bytes(4, "big")
            + data_payload
        )

        # 2. Build WSD1 block
        wsd1_payload = bytearray()
        wsd1_payload.extend((1).to_bytes(4, "big"))  # count = 1
        wsd1_payload.append(self.codec)
        wsd1_payload.append(1 if self.loop_flag else 0)
        wsd1_payload.append(self.channels)
        wsd1_payload.append(0)  # pad
        wsd1_payload.extend(self.sample_rate.to_bytes(2, "big"))
        wsd1_payload.extend((0).to_bytes(2, "big"))  # pad2
        wsd1_payload.extend(self.loop_start.to_bytes(4, "big"))
        wsd1_payload.extend(len(self.samples).to_bytes(4, "big"))
        wsd1_payload.extend(sample_offset.to_bytes(4, "big"))
        wsd1_payload.extend(chan_info_offset.to_bytes(4, "big"))

        # Pad WSD1 payload to 32-byte alignment
        wsd1_pad = (32 - (len(wsd1_payload) % 32)) % 32
        wsd1_payload.extend(b"\x00" * wsd1_pad)

        wsd1_chunk_size = 8 + len(wsd1_payload)
        wsd1_chunk = (
            WSD1_MAGIC
            + wsd1_chunk_size.to_bytes(4, "big")
            + bytes(wsd1_payload)
        )

        # 3. Build RWSD Header
        rwsd_header_size = 0x20
        wsd1_offset = rwsd_header_size
        data_offset = wsd1_offset + len(wsd1_chunk)
        total_file_size = data_offset + len(data_chunk)

        header_struct = RWSDHeaderStruct(
            magic=RWSD_MAGIC,
            bom=0xFEFF,
            version=0x0102,
            filesize=total_file_size,
            header_size=rwsd_header_size,
            num_blocks=2,
            wsd1_offset=wsd1_offset,
            wsd1_size=len(wsd1_chunk),
            data_offset=data_offset,
            data_size=len(data_chunk),
        )
        return header_struct.to_bytes() + wsd1_chunk + data_chunk


# ==============================================================================
# High-Level BRSAR Sound Archive Engine
# ==============================================================================

class BRSARSoundArchive:
    """
    Nintendo Wii BRSAR Sound Archive Engine.
    Represents an in-memory parsed .brsar sound container with automatic relational
    pointer management, voice clip replacement, and cross-archive undubbing.
    """

    def __init__(self, raw_data: bytes):
        self._raw_data = raw_data
        self._header: BRSARHeaderStruct = BRSARHeaderStruct()
        self._sound_names: Dict[int, str] = {}
        self._name_to_id: Dict[str, int] = {}
        self._sounds: Dict[int, SoundEntry] = {}
        self._files: Dict[int, bytes] = {}
        self._parse(raw_data)

    @classmethod
    def from_bytes(cls, data: bytes) -> BRSARSoundArchive:
        """
        Parses a .brsar archive from binary bytes.
        """
        return cls(data)

    @classmethod
    def from_file(cls, filepath: Union[str, os.PathLike]) -> BRSARSoundArchive:
        """
        Loads and parses a .brsar archive from the filesystem.
        """
        with open(filepath, "rb") as f:
            return cls(f.read())

    def _parse(self, data: bytes) -> None:
        """
        Internal parser for RSAR header, SYMB, INFO, and FILE sections.
        """
        if len(data) < 0x40:
            raise ParseError(f"Data too short for BRSAR header ({len(data)} < 64 bytes)")

        self._header = BRSARHeaderStruct.from_bytes(data, offset=0)
        if self._header.magic != RSAR_MAGIC:
            raise ParseError(f"Invalid BRSAR magic: {self._header.magic!r} (expected {RSAR_MAGIC!r})")

        symb_off = self._header.symb_offset
        symb_sz = self._header.symb_size
        info_off = self._header.info_offset
        info_sz = self._header.info_size
        file_off = self._header.file_offset
        file_sz = self._header.file_size_sec

        if symb_off + symb_sz > len(data) or info_off + info_sz > len(data):
            raise ParseError("BRSAR section offsets exceed archive file size")

        # 1. Parse SYMB section
        if symb_sz >= 8:
            symb_bytes = data[symb_off : symb_off + symb_sz]
            symb_hdr = SYMBHeaderStruct.from_bytes(symb_bytes, offset=0)
            if symb_hdr.magic != SYMB_MAGIC:
                raise ParseError(f"Invalid SYMB magic: {symb_hdr.magic!r}")

            snd_tbl_off = symb_hdr.string_table_sound_offset
            if snd_tbl_off < len(symb_bytes):
                snd_tbl_data = symb_bytes[snd_tbl_off:]
                if len(snd_tbl_data) >= 4:
                    count = int.from_bytes(snd_tbl_data[0:4], "big")
                    for i in range(count):
                        ent_off_idx = 4 + i * 4
                        if ent_off_idx + 4 <= len(snd_tbl_data):
                            str_off = int.from_bytes(snd_tbl_data[ent_off_idx : ent_off_idx + 4], "big")
                            if str_off < len(symb_bytes):
                                # Read null-terminated string
                                end = symb_bytes.find(b"\x00", str_off)
                                if end == -1:
                                    end = len(symb_bytes)
                                name = symb_bytes[str_off:end].decode("ascii", errors="replace")
                                self._sound_names[i] = name
                                self._name_to_id[name] = i

        # 2. Parse INFO section
        file_entries: List[Tuple[int, int]] = []  # [(file_size, data_offset), ...]
        if info_sz >= 8:
            info_bytes = data[info_off : info_off + info_sz]
            info_hdr = INFOHeaderStruct.from_bytes(info_bytes, offset=0)
            if info_hdr.magic != INFO_MAGIC:
                raise ParseError(f"Invalid INFO magic: {info_hdr.magic!r}")

            # Parse File Table
            file_tbl_off = info_hdr.file_table_offset
            if file_tbl_off > 0 and file_tbl_off < len(info_bytes):
                file_tbl_data = info_bytes[file_tbl_off:]
                if len(file_tbl_data) >= 4:
                    num_files = int.from_bytes(file_tbl_data[0:4], "big")
                    for i in range(num_files):
                        ent_off = 4 + i * 8
                        if ent_off + 8 <= len(file_tbl_data):
                            f_sz = int.from_bytes(file_tbl_data[ent_off : ent_off + 4], "big")
                            f_off = int.from_bytes(file_tbl_data[ent_off + 4 : ent_off + 8], "big")
                            file_entries.append((f_sz, f_off))

            # Parse Sound Table
            snd_tbl_off = info_hdr.sound_table_offset
            if snd_tbl_off > 0 and snd_tbl_off < len(info_bytes):
                snd_tbl_data = info_bytes[snd_tbl_off:]
                if len(snd_tbl_data) >= 4:
                    num_sounds = int.from_bytes(snd_tbl_data[0:4], "big")
                    for i in range(num_sounds):
                        # Each entry: file_id(4), player_id(4), sound_type(1), volume(1), pan(1), priority(1)
                        ent_off = 4 + i * 12
                        if ent_off + 12 <= len(snd_tbl_data):
                            f_id = int.from_bytes(snd_tbl_data[ent_off : ent_off + 4], "big")
                            s_type_num = snd_tbl_data[ent_off + 8]
                            vol = snd_tbl_data[ent_off + 9]
                            pan = snd_tbl_data[ent_off + 10]
                            pri = snd_tbl_data[ent_off + 11]

                            type_str = "WSD" if s_type_num == SOUND_TYPE_WSD else ("SEQ" if s_type_num == SOUND_TYPE_SEQ else "STRM")
                            name = self._sound_names.get(i, f"Sound_{i:04d}")

                            f_sz, f_off = (file_entries[f_id] if f_id < len(file_entries) else (0, 0))

                            self._sounds[i] = SoundEntry(
                                sound_id=i,
                                name=name,
                                sound_type=type_str,
                                file_id=f_id,
                                file_offset=f_off,
                                file_size=f_sz,
                                volume=vol,
                                pan=pan,
                                priority=pri,
                            )

        # 3. Parse FILE section
        if file_sz >= 8 and file_off + file_sz <= len(data):
            file_bytes = data[file_off : file_off + file_sz]
            file_hdr = FILEHeaderStruct.from_bytes(file_bytes, offset=0)
            if file_hdr.magic != FILE_MAGIC:
                raise ParseError(f"Invalid FILE magic: {file_hdr.magic!r}")

            file_payload = file_bytes[0x20:]  # Sub-files start at 0x20 relative to FILE section
            for i, (f_sz, f_off) in enumerate(file_entries):
                if f_sz > 0 and f_off + f_sz <= len(file_payload):
                    self._files[i] = file_payload[f_off : f_off + f_sz]
                else:
                    self._files[i] = b""


    def list_sounds(self) -> List[SoundEntry]:
        """
        Returns a sorted list of all sound entries in the archive.
        """
        return sorted(self._sounds.values(), key=lambda s: s.sound_id)

    def find_sounds(self, query: str) -> List[SoundEntry]:
        """
        Finds sounds matching a substring or pattern (case-insensitive).
        """
        q = query.lower()
        return [s for s in self.list_sounds() if q in s.name.lower()]

    def get_sound(self, name_or_id: Union[str, int]) -> Optional[SoundEntry]:
        """
        Retrieves a sound entry by exact name or integer Sound ID.
        """
        if isinstance(name_or_id, int):
            return self._sounds.get(name_or_id)
        if isinstance(name_or_id, str):
            sound_id = self._name_to_id.get(name_or_id)
            if sound_id is not None:
                return self._sounds.get(sound_id)
            # Case-insensitive fallback
            for s in self._sounds.values():
                if s.name.lower() == name_or_id.lower():
                    return s
        return None

    def export_wav(self, name_or_id: Union[str, int]) -> WavSound:
        """
        Extracts a wave sound (RWSD) as an uncompressed 16-bit PCM WavSound.
        """
        sound = self.get_sound(name_or_id)
        if sound is None:
            raise KeyError(f"Sound {name_or_id!r} not found in archive")
        if not sound.is_wave:
            raise ValueError(f"Sound {sound.name} is not a wave sound (type: {sound.sound_type})")

        file_data = self._files.get(sound.file_id)
        if not file_data:
            raise ValueError(f"No file payload found for sound {sound.name} (File ID: {sound.file_id})")

        rwsd = RWSDFile.from_bytes(file_data)
        return rwsd.to_wav()

    def import_wav(
        self,
        name_or_id: Union[str, int],
        wav_input: Union[WavSound, bytes, str, os.PathLike],
    ) -> None:
        """
        Replaces the audio of a wave sound with a new WAV file or WavSound.
        Automatically compresses to DSP-ADPCM and updates file tables.
        """
        sound = self.get_sound(name_or_id)
        if sound is None:
            raise KeyError(f"Sound {name_or_id!r} not found in archive")
        if not sound.is_wave:
            raise ValueError(f"Sound {sound.name} is not a wave sound (type: {sound.sound_type})")

        new_rwsd = RWSDFile.from_wav(wav_input)
        new_payload = new_rwsd.to_bytes()

        self._files[sound.file_id] = new_payload
        sound.file_size = len(new_payload)

    def apply_undub_from(
        self,
        source_archive: BRSARSoundArchive,
        prefix_filter: str = "VO_",
    ) -> UndubTransferReport:
        """
        Performs automated cross-archive voice undubbing:
        Copies matching voice clips from source_archive into this archive by symbol name.
        """
        src_sounds = source_archive.list_sounds()
        transferred: List[str] = []
        skipped = 0

        for src_s in src_sounds:
            if not src_s.is_wave:
                continue
            if prefix_filter and not src_s.name.startswith(prefix_filter):
                continue

            target_s = self.get_sound(src_s.name)
            if target_s is not None and target_s.is_wave:
                src_payload = source_archive._files.get(src_s.file_id)
                if src_payload:
                    self._files[target_s.file_id] = src_payload
                    target_s.file_size = len(src_payload)
                    transferred.append(src_s.name)
                else:
                    skipped += 1
            else:
                skipped += 1

        return UndubTransferReport(
            total_scanned=len(src_sounds),
            transferred_count=len(transferred),
            skipped_count=skipped,
            transferred_names=transferred,
        )

    def to_bytes(self) -> bytes:
        """
        Serializes and repacks the entire .brsar archive into binary bytes with 32-byte alignment.
        Recalculates all section offsets and file tables automatically.
        """
        # 1. Build SYMB Section
        symb_strings_bytes = bytearray()
        symb_offsets: List[int] = []

        # Ensure all sounds have entries
        all_sounds = self.list_sounds()
        num_sounds = len(all_sounds)

        # Base offset where strings start (relative to SYMB section start):
        # Header (0x18) + count (4) + offsets (num_sounds * 4)
        str_start_rel_symb = 0x18 + 4 + num_sounds * 4

        for s in all_sounds:
            symb_offsets.append(str_start_rel_symb + len(symb_strings_bytes))
            symb_strings_bytes.extend(s.name.encode("ascii", errors="replace") + b"\x00")

        # Build Sound String Table
        snd_str_tbl = bytearray()
        snd_str_tbl.extend(num_sounds.to_bytes(4, "big"))
        for off in symb_offsets:
            snd_str_tbl.extend(off.to_bytes(4, "big"))
        snd_str_tbl.extend(symb_strings_bytes)

        # Pad string table to 32 bytes
        symb_pad = (32 - ((0x18 + len(snd_str_tbl)) % 32)) % 32
        symb_total_size = 0x18 + len(snd_str_tbl) + symb_pad

        symb_hdr = SYMBHeaderStruct(
            magic=SYMB_MAGIC,
            size=symb_total_size,
            string_table_sound_offset=0x18,
            string_table_player_offset=0,
            string_table_group_offset=0,
            string_table_bank_offset=0,
        )
        symb_bytes = symb_hdr.to_bytes() + bytes(snd_str_tbl) + (b"\x00" * symb_pad)

        # 2. Build FILE Section & calculate file offsets
        file_payload = bytearray()
        new_file_table_records: List[Tuple[int, int]] = []  # (size, offset_rel_to_payload)

        # Accommodate all file IDs up to maximum referenced ID so indices map 1:1 with file_id
        max_f_id = max(
            max(self._files.keys(), default=-1),
            max((s.file_id for s in all_sounds), default=-1),
        )
        num_files = max_f_id + 1

        for f_id in range(num_files):
            data_blob = self._files.get(f_id, b"")
            if data_blob:
                # Align each sub-file to 32 bytes
                pad_len = (32 - (len(file_payload) % 32)) % 32
                if pad_len > 0:
                    file_payload.extend(b"\x00" * pad_len)

                cur_offset = len(file_payload)
                file_payload.extend(data_blob)
                new_file_table_records.append((len(data_blob), cur_offset))
            else:
                new_file_table_records.append((0, 0))

        # Pad FILE payload
        file_sec_pad = (32 - ((0x20 + len(file_payload)) % 32)) % 32
        file_total_size = 0x20 + len(file_payload) + file_sec_pad

        file_hdr = FILEHeaderStruct(
            magic=FILE_MAGIC,
            size=file_total_size,
        )
        file_bytes = file_hdr.to_bytes() + (b"\x00" * 0x18) + bytes(file_payload) + (b"\x00" * file_sec_pad)

        # 3. Build INFO Section
        # Layout:
        # 0x00: INFOHeaderStruct (0x1C)
        # File Table: count (4), then records: size(4), offset(4)
        # Sound Table: count (4), then records: file_id(4), player_id(4), type(1), vol(1), pan(1), pri(1)
        file_tbl_offset = 0x1C


        info_file_tbl = bytearray()
        info_file_tbl.extend(num_files.to_bytes(4, "big"))
        for f_sz, f_off in new_file_table_records:
            info_file_tbl.extend(f_sz.to_bytes(4, "big"))
            info_file_tbl.extend(f_off.to_bytes(4, "big"))

        sound_tbl_offset = file_tbl_offset + len(info_file_tbl)

        info_sound_tbl = bytearray()
        info_sound_tbl.extend(num_sounds.to_bytes(4, "big"))
        for s in all_sounds:
            type_num = (
                SOUND_TYPE_WSD if s.sound_type == "WSD"
                else (SOUND_TYPE_SEQ if s.sound_type == "SEQ" else SOUND_TYPE_STRM)
            )
            info_sound_tbl.extend(s.file_id.to_bytes(4, "big"))
            info_sound_tbl.extend((0).to_bytes(4, "big"))  # player_id
            info_sound_tbl.append(type_num)
            info_sound_tbl.append(s.volume)
            info_sound_tbl.append(s.pan)
            info_sound_tbl.append(s.priority)

        info_payload = bytes(info_file_tbl) + bytes(info_sound_tbl)
        info_pad = (32 - ((0x1C + len(info_payload)) % 32)) % 32
        info_total_size = 0x1C + len(info_payload) + info_pad

        info_hdr = INFOHeaderStruct(
            magic=INFO_MAGIC,
            size=info_total_size,
            sound_table_offset=sound_tbl_offset,
            bank_table_offset=0,
            player_table_offset=0,
            file_table_offset=file_tbl_offset,
            group_table_offset=0,
        )
        info_bytes = info_hdr.to_bytes() + info_payload + (b"\x00" * info_pad)

        # 4. Assemble Entire BRSAR
        rsar_header_size = 0x40
        symb_offset = rsar_header_size
        info_offset = symb_offset + len(symb_bytes)
        file_offset = info_offset + len(info_bytes)
        total_archive_size = file_offset + len(file_bytes)

        rsar_hdr = BRSARHeaderStruct(
            magic=RSAR_MAGIC,
            bom=0xFEFF,
            version=0x0104,
            file_size=total_archive_size,
            header_size=rsar_header_size,
            num_sections=3,
            symb_offset=symb_offset,
            symb_size=len(symb_bytes),
            info_offset=info_offset,
            info_size=len(info_bytes),
            file_offset=file_offset,
            file_size_sec=len(file_bytes),
        )

        return rsar_hdr.to_bytes() + symb_bytes + info_bytes + file_bytes

    def save(self, filepath: Union[str, os.PathLike]) -> None:
        """
        Saves the repacked .brsar archive to the filesystem.
        """
        with open(filepath, "wb") as f:
            f.write(self.to_bytes())


# ==============================================================================
# Factory / Helper Functions
# ==============================================================================

def create_synthetic_brsar(
    sounds: Sequence[Tuple[str, List[int], int]],
) -> bytes:
    """
    Utility helper to create a valid synthetic .brsar archive for testing and scaffolding.

    Args:
        sounds: List of tuples (sound_name, pcm_samples, sample_rate).

    Returns:
        Raw binary bytes of the created .brsar archive.
    """
    # Pre-build sub-files
    sub_files: List[bytes] = []
    sound_entries: List[SoundEntry] = []

    for i, (name, samples, srate) in enumerate(sounds):
        rwsd = RWSDFile(
            samples=samples,
            sample_rate=srate,
            channels=1,
            codec=CODEC_DSP_ADPCM,
        )
        rwsd_bytes = rwsd.to_bytes()
        sub_files.append(rwsd_bytes)
        sound_entries.append(
            SoundEntry(
                sound_id=i,
                name=name,
                sound_type="WSD",
                file_id=i,
                file_offset=0,
                file_size=len(rwsd_bytes),
                volume=100,
                pan=64,
                priority=64,
            )
        )

    # Empty dummy archive to leverage to_bytes()
    empty_header = BRSARHeaderStruct(
        magic=RSAR_MAGIC,
        bom=0xFEFF,
        version=0x0104,
        file_size=0x40,
        header_size=0x40,
        num_sections=3,
        symb_offset=0x40,
        symb_size=0,
        info_offset=0x40,
        info_size=0,
        file_offset=0x40,
        file_size_sec=0,
    )
    raw_dummy = empty_header.to_bytes()

    # Construct and populate archive object
    archive = BRSARSoundArchive.__new__(BRSARSoundArchive)
    archive._raw_data = raw_dummy
    archive._header = empty_header
    archive._sound_names = {s.sound_id: s.name for s in sound_entries}
    archive._name_to_id = {s.name: s.sound_id for s in sound_entries}
    archive._sounds = {s.sound_id: s for s in sound_entries}
    archive._files = {i: data for i, data in enumerate(sub_files)}

    return archive.to_bytes()
