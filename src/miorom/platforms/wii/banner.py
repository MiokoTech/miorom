"""
Nintendo Wii & GameCube Opening Banner Engine (opening.bnr).
Provides low-level declarative structures (BinaryStruct), checksum calculators (IMET MD5, IMD5),
multilingual title editors, RGB5A3 icon codecs, and BNS banner sound decoders/encoders.
Powered by MioROM.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Union

from miorom.audio.dsp_adpcm import DEFAULT_DSP_COEFFS, DSPADPCMCodec
from miorom.audio.wav_codec import WavCodec, WavSound
from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import (
    U16,
    U32,
    BinaryStruct,
    FixedString,
    RawBytes,
)
from miorom.errors import ParseError
from miorom.graphics.png_codec import PNGCodec, PNGImage
from miorom.platforms.wii.brstm import encode_dsp_adpcm_channel
from miorom.platforms.wii.u8 import U8Archive

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ==============================================================================
# Constants & Language Tables
# ==============================================================================

WII_LANGUAGES: List[str] = [
    "jp",   # 0: Japanese
    "en",   # 1: English
    "de",   # 2: German
    "fr",   # 3: French
    "es",   # 4: Spanish
    "it",   # 5: Italian
    "nl",   # 6: Dutch
    "zhs",  # 7: Simplified Chinese
    "zht",  # 8: Traditional Chinese
    "ko",   # 9: Korean
]

WII_LANGUAGE_ALIASES: Dict[str, str] = {
    "japanese": "jp", "ja": "jp", "jpn": "jp", "0": "jp",
    "english": "en", "us": "en", "uk": "en", "1": "en",
    "german": "de", "ge": "de", "ger": "de", "2": "de",
    "french": "fr", "fra": "fr", "fre": "fr", "3": "fr",
    "spanish": "es", "spa": "es", "4": "es",
    "italian": "it", "ita": "it", "5": "it",
    "dutch": "nl", "nld": "nl", "dut": "nl", "6": "nl",
    "simplified_chinese": "zhs", "zh_cn": "zhs", "zh-cn": "zhs", "cn": "zhs", "7": "zhs",
    "traditional_chinese": "zht", "zh_tw": "zht", "zh-tw": "zht", "tw": "zht", "8": "zht",
    "korean": "ko", "kor": "ko", "kr": "ko", "9": "ko",
}

GC_LANGUAGES: List[str] = [
    "en",   # 0: English
    "de",   # 1: German
    "fr",   # 2: French
    "es",   # 3: Spanish
    "it",   # 4: Italian
    "nl",   # 5: Dutch
]

IMET_MAGIC = b"IMET"
IMD5_MAGIC = b"IMD5"
BNR1_MAGIC = b"BNR1"
BNR2_MAGIC = b"BNR2"
BNS_MAGIC = b"BNS "

GC_IMAGE_WIDTH = 96
GC_IMAGE_HEIGHT = 32
GC_IMAGE_SIZE = GC_IMAGE_WIDTH * GC_IMAGE_HEIGHT * 2  # 6,144 bytes


# ==============================================================================
# Low-Level Binary Structures (Layer 1)
# ==============================================================================


class IMETHeaderStruct(BinaryStruct):
    """
    Standard Nintendo Wii IMET header structure (1536 bytes / 0x600 on optical disc).
    Offset 0x00..0x40 is zero padding on optical disc titles.
    """
    _endian = ">"
    zeroes_prefix = RawBytes(0x40, default=b"\x00" * 0x40)
    magic = RawBytes(4, default=IMET_MAGIC)
    hash_size = U32(default=0x0600)
    version = U32(default=3)
    icon_size = U32(default=0)
    banner_size = U32(default=0)
    sound_size = U32(default=0)
    flags = U32(default=0)
    names_raw = RawBytes(10 * 84, default=b"\x00" * (10 * 84))
    zeroes_padding = RawBytes(588, default=b"\x00" * 588)
    crypto = RawBytes(16, default=b"\x00" * 16)


class IMD5HeaderStruct(BinaryStruct):
    """
    32-byte IMD5 wrapper prepended to banner.bin, icon.bin, and sound.bin.
    """
    _endian = ">"
    magic = RawBytes(4, default=IMD5_MAGIC)
    filesize = U32(default=0)
    zeroes = RawBytes(8, default=b"\x00" * 8)
    crypto = RawBytes(16, default=b"\x00" * 16)


class GCBannerHeaderStruct(BinaryStruct):
    """
    32-byte header for GameCube BNR1 / BNR2 banners.
    """
    _endian = ">"
    magic = RawBytes(4, default=BNR1_MAGIC)
    padding = RawBytes(28, default=b"\x00" * 28)


class GCCommentStruct(BinaryStruct):
    """
    320-byte comment/title block per language in GameCube BNR files.
    Supports both Shift-JIS (NTSC-J BNR1) and CP1252/Latin-1 (PAL BNR2 and NTSC-U).
    """
    _endian = ">"
    _short_title_raw = RawBytes(32, default=b"\x00" * 32)
    _short_company_raw = RawBytes(32, default=b"\x00" * 32)
    _full_title_raw = RawBytes(64, default=b"\x00" * 64)
    _full_company_raw = RawBytes(64, default=b"\x00" * 64)
    _description_raw = RawBytes(128, default=b"\x00" * 128)

    def __init__(
        self,
        short_title: str = "",
        short_company: str = "",
        full_title: str = "",
        full_company: str = "",
        description: str = "",
        encoding: str = "cp1252",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.encoding = encoding
        if short_title:
            self.short_title = short_title
        if short_company:
            self.short_company = short_company
        if full_title:
            self.full_title = full_title
        if full_company:
            self.full_company = full_company
        if description:
            self.description = description

    def _decode_text(self, raw: bytes) -> str:
        stripped = bytes(raw).rstrip(b"\x00")
        if not stripped:
            return ""
        enc = getattr(self, "encoding", "cp1252")
        try:
            return stripped.decode(enc)
        except (UnicodeDecodeError, LookupError):
            pass
        for fallback in ("cp1252", "shift-jis", "latin-1"):
            try:
                return stripped.decode(fallback)
            except UnicodeDecodeError:
                continue
        return stripped.decode("latin-1", errors="replace")

    def _encode_text(self, value: Union[str, bytes], max_len: int) -> bytes:
        if isinstance(value, (bytes, bytearray)):
            raw = bytes(value)
        else:
            text = str(value)
            enc = getattr(self, "encoding", "cp1252")
            try:
                raw = text.encode(enc)
            except UnicodeEncodeError:
                alt_enc = "shift-jis" if enc == "cp1252" else "cp1252"
                try:
                    raw = text.encode(alt_enc)
                    self.encoding = alt_enc
                except UnicodeEncodeError:
                    raw = text.encode("cp1252", errors="replace")
            while len(raw) > max_len and text:
                text = text[:-1]
                try:
                    raw = text.encode(getattr(self, "encoding", "cp1252"))
                except UnicodeEncodeError:
                    raw = raw[:max_len]
        return raw[:max_len].ljust(max_len, b"\x00")

    @property
    def short_title(self) -> str:
        return self._decode_text(self._short_title_raw)

    @short_title.setter
    def short_title(self, value: Union[str, bytes]) -> None:
        self._short_title_raw = self._encode_text(value, 32)

    @property
    def short_company(self) -> str:
        return self._decode_text(self._short_company_raw)

    @short_company.setter
    def short_company(self, value: Union[str, bytes]) -> None:
        self._short_company_raw = self._encode_text(value, 32)

    @property
    def full_title(self) -> str:
        return self._decode_text(self._full_title_raw)

    @full_title.setter
    def full_title(self, value: Union[str, bytes]) -> None:
        self._full_title_raw = self._encode_text(value, 64)

    @property
    def full_company(self) -> str:
        return self._decode_text(self._full_company_raw)

    @full_company.setter
    def full_company(self, value: Union[str, bytes]) -> None:
        self._full_company_raw = self._encode_text(value, 64)

    @property
    def description(self) -> str:
        return self._decode_text(self._description_raw)

    @description.setter
    def description(self, value: Union[str, bytes]) -> None:
        self._description_raw = self._encode_text(value, 128)


class BNSHeaderStruct(BinaryStruct):
    """
    Standard Nintendo BNS (Banner Nintendo Sound) file header.
    """
    _endian = ">"
    magic = RawBytes(4, default=BNS_MAGIC)
    bom = U32(default=0xFEFF0100)
    filesize = U32(default=0)
    headersize = U16(default=0x20)
    chunkcount = U16(default=2)


# ==============================================================================
# Helper Functions & Checksum Calculators
# ==============================================================================


def calculate_imet_md5(imet_bytes: bytes) -> bytes:
    """
    Computes the standard Nintendo MD5 hash for an IMET header.
    Hashed from b'IMET' through the end of the header (offset 0x40..0x600 on disc),
    with the 16-byte crypto field zeroed during computation.
    """
    imet_pos = imet_bytes.find(IMET_MAGIC)
    if imet_pos == -1:
        raise ParseError("Cannot calculate IMET MD5: magic b'IMET' not found.")

    header_block = bytearray(imet_bytes[imet_pos : imet_pos + 1472])
    if len(header_block) < 1472:
        header_block.extend(b"\x00" * (1472 - len(header_block)))

    # Zero out crypto field (last 16 bytes)
    header_block[-16:] = b"\x00" * 16
    return hashlib.md5(header_block).digest()


def wrap_imd5(payload: bytes) -> bytes:
    """Wraps binary payload with a 32-byte IMD5 header containing its MD5 digest."""
    digest = hashlib.md5(payload).digest()
    hdr = IMD5HeaderStruct(
        magic=IMD5_MAGIC,
        filesize=len(payload),
        crypto=digest,
    )
    return hdr.to_bytes() + payload


def unwrap_imd5(data: bytes) -> bytes:
    """Unwraps an IMD5 payload and verifies the MD5 checksum."""
    if len(data) < 32 or data[:4] != IMD5_MAGIC:
        return data  # Raw payload without IMD5 header

    hdr = IMD5HeaderStruct.from_bytes(data[:32])
    payload = data[32 : 32 + hdr.filesize] if hdr.filesize > 0 else data[32:]
    actual_md5 = hashlib.md5(payload).digest()
    if hdr.crypto != actual_md5 and hdr.crypto != b"\x00" * 16:
        # Checksum mismatch, but return payload gracefully
        pass
    return payload


# ==============================================================================
# Codecs: RGB5A3 Micro-Tiled Texture & BNS Sound
# ==============================================================================


def decode_rgb5a3(raw: bytes, width: int = GC_IMAGE_WIDTH, height: int = GC_IMAGE_HEIGHT) -> bytes:
    """
    Decodes Nintendo GX 4x4 micro-tiled RGB5A3 data into 32-bit RGBA raw bytes.
    """
    out = bytearray(width * height * 4)
    tiles_x = (width + 3) // 4
    tiles_y = (height + 3) // 4
    pos = 0

    for ty in range(tiles_y):
        for tx in range(tiles_x):
            for py in range(4):
                for px in range(4):
                    x = tx * 4 + px
                    y = ty * 4 + py
                    if pos + 2 <= len(raw) and x < width and y < height:
                        val = (raw[pos] << 8) | raw[pos + 1]
                        if val & 0x8000:
                            # 15-bit RGB opaque (5-5-5)
                            r = ((val >> 10) & 0x1F) * 255 // 31
                            g = ((val >> 5) & 0x1F) * 255 // 31
                            b = (val & 0x1F) * 255 // 31
                            a = 255
                        else:
                            # 12-bit ARGB (3-4-4-4)
                            a = ((val >> 12) & 0x07) * 255 // 7
                            r = ((val >> 8) & 0x0F) * 255 // 15
                            g = ((val >> 4) & 0x0F) * 255 // 15
                            b = (val & 0x0F) * 255 // 15
                        idx = (y * width + x) * 4
                        out[idx : idx + 4] = bytes([r, g, b, a])
                    pos += 2

    return bytes(out)


def encode_rgb5a3(rgba: bytes, width: int = GC_IMAGE_WIDTH, height: int = GC_IMAGE_HEIGHT) -> bytes:
    """
    Encodes 32-bit RGBA pixel bytes into Nintendo GX 4x4 micro-tiled RGB5A3 data.
    """
    out = bytearray()
    tiles_x = (width + 3) // 4
    tiles_y = (height + 3) // 4

    for ty in range(tiles_y):
        for tx in range(tiles_x):
            for py in range(4):
                for px in range(4):
                    x = tx * 4 + px
                    y = ty * 4 + py
                    if x < width and y < height:
                        idx = (y * width + x) * 4
                        if idx + 4 <= len(rgba):
                            r = rgba[idx]
                            g = rgba[idx + 1]
                            b = rgba[idx + 2]
                            a = rgba[idx + 3]
                        else:
                            r, g, b, a = 0, 0, 0, 0
                        if a >= 224:
                            val = 0x8000 | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
                        else:
                            val = ((a >> 5) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
                    else:
                        val = 0
                    out.append((val >> 8) & 0xFF)
                    out.append(val & 0xFF)

    return bytes(out)


def decode_bns_to_wav(bns_bytes: bytes) -> bytes:
    """
    Decodes a BNS audio stream to standard 16-bit PCM WAV.
    """
    if len(bns_bytes) < 32 or bns_bytes[:4] != BNS_MAGIC:
        raise ParseError(f"Invalid BNS magic: expected b'BNS ', got {bns_bytes[:4]!r}")

    # Read chunk info table
    chunk_count = BinaryReader.unpack_u16(bns_bytes, 0x0E, endian=">")
    info_offset = 0
    info_size = 0
    data_offset = 0
    data_size = 0

    table_pos = 0x10
    for _ in range(chunk_count):
        if table_pos + 8 > len(bns_bytes):
            break
        c_off = BinaryReader.unpack_u32(bns_bytes, table_pos, endian=">")
        c_sz = BinaryReader.unpack_u32(bns_bytes, table_pos + 4, endian=">")
        table_pos += 8
        if c_off + 4 <= len(bns_bytes):
            c_type = bns_bytes[c_off : c_off + 4]
            if c_type == b"INFO":
                info_offset = c_off
                info_size = c_sz
            elif c_type == b"DATA":
                data_offset = c_off
                data_size = c_sz

    if info_offset == 0 or data_offset == 0:
        raise ParseError("Corrupt BNS: missing INFO or DATA chunk.")

    # Parse INFO chunk
    info_payload = bns_bytes[info_offset + 8 : info_offset + info_size]
    codec = info_payload[0]
    channels = info_payload[2]
    sample_rate = BinaryReader.unpack_u16(info_payload, 4, endian=">")
    samples_count = BinaryReader.unpack_u32(info_payload, 12, endian=">")

    raw_audio = bns_bytes[data_offset + 8 : data_offset + data_size]

    if codec == 1:  # PCM16 Big-Endian
        pcm16_samples: List[int] = []
        for i in range(min(samples_count * channels, len(raw_audio) // 2)):
            val = BinaryReader.unpack_s16(raw_audio, i * 2, endian=">")
            pcm16_samples.append(val)
        return WavCodec.encode(WavSound(
            samples=pcm16_samples,
            sample_rate=sample_rate if sample_rate > 0 else 32000,
            channels=max(1, channels),
            bits_per_sample=16,
        ))
    elif codec in (0, 2):  # DSP-ADPCM (0 in standard Nintendo BNS, 2 in extended)
        # Parse channel pointer list offset (relative to INFO chunk payload start)
        list_offset = BinaryReader.unpack_u32(info_payload, 0x10, endian=">") if len(info_payload) >= 0x14 else 0x18
        coeffs_list: List[List[int]] = []
        channel_data_offsets: List[int] = []

        bytes_per_ch = len(raw_audio) // max(1, channels)
        for ch in range(channels):
            ch_info_ptr = 0
            if list_offset + ch * 4 + 4 <= len(info_payload):
                ch_info_ptr = BinaryReader.unpack_u32(info_payload, list_offset + ch * 4, endian=">")

            dsp_offset = 0
            ch_data_off = ch * bytes_per_ch

            # Check if ch_info_ptr points to a standard 12-byte Channel Info struct (data_off, dsp_off, 0)
            if ch_info_ptr > 0 and ch_info_ptr + 12 <= len(info_payload):
                cand_data_off = BinaryReader.unpack_u32(info_payload, ch_info_ptr, endian=">")
                cand_dsp_off = BinaryReader.unpack_u32(info_payload, ch_info_ptr + 4, endian=">")
                reserved = BinaryReader.unpack_u32(info_payload, ch_info_ptr + 8, endian=">")
                if reserved == 0 and cand_dsp_off + 32 <= len(info_payload):
                    ch_data_off = cand_data_off
                    dsp_offset = cand_dsp_off

            if dsp_offset == 0:
                # Direct pointer to coefficient block or fallback offset
                dsp_offset = ch_info_ptr if ch_info_ptr > 0 else (0x20 + ch * 0x30)

            channel_data_offsets.append(ch_data_off)

            ch_coeffs = list(DEFAULT_DSP_COEFFS)
            if dsp_offset + 32 <= len(info_payload):
                ch_coeffs = [
                    BinaryReader.unpack_s16(info_payload, dsp_offset + k * 2, endian=">")
                    for k in range(16)
                ]
            coeffs_list.append(ch_coeffs)

        # Decode channels
        decoded_channels: List[List[int]] = []
        for ch in range(channels):
            start_off = channel_data_offsets[ch]
            end_off = channel_data_offsets[ch + 1] if ch + 1 < channels else len(raw_audio)
            if end_off <= start_off or end_off > len(raw_audio):
                end_off = min(len(raw_audio), start_off + bytes_per_ch)
            ch_data = raw_audio[start_off:end_off]
            s1, s2 = 0, 0
            ch_samples: List[int] = []
            for f_idx in range(len(ch_data) // 8):
                frame = ch_data[f_idx * 8 : (f_idx + 1) * 8]
                f_samps, s1, s2 = DSPADPCMCodec.decode_frame(frame, coeffs_list[ch], s1, s2)
                ch_samples.extend(f_samps)
            decoded_channels.append(ch_samples[:samples_count] if samples_count > 0 else ch_samples)

        # Interleave channels
        interleaved: List[int] = []
        min_samples = min((len(ch_samples) for ch_samples in decoded_channels), default=0)
        for s_idx in range(min_samples):
            for ch in range(channels):
                interleaved.append(decoded_channels[ch][s_idx])

        return WavCodec.encode(WavSound(
            samples=interleaved,
            sample_rate=sample_rate if sample_rate > 0 else 32000,
            channels=max(1, channels),
            bits_per_sample=16,
        ))
    else:
        # Fallback: synthesize silent wav
        return WavCodec.encode(WavSound(
            samples=[0] * 1000,
            sample_rate=32000,
            channels=1,
            bits_per_sample=16,
        ))


def encode_wav_to_bns(wav_bytes: bytes, loop: bool = True) -> bytes:
    """
    Encodes WAV audio into a standard Nintendo BNS (Banner Nintendo Sound) file.
    Fully compliant with the Nintendo Wii SDK and third-party decoders (vgmstream).
    """
    sound = WavCodec.decode(wav_bytes)
    channels = max(1, min(2, sound.channels))
    sample_rate = sound.sample_rate

    # Split channels
    channel_samples: List[List[int]] = [[] for _ in range(channels)]
    for i, s in enumerate(sound.samples):
        channel_samples[i % channels].append(s)

    # Encode with DSP-ADPCM
    encoded_channel_bytes: List[bytes] = []
    for ch_s in channel_samples:
        ch_encoded, _, _, _ = encode_dsp_adpcm_channel(ch_s, list(DEFAULT_DSP_COEFFS))
        encoded_channel_bytes.append(ch_encoded)

    data_payload = b"".join(encoded_channel_bytes)
    data_size = 8 + len(data_payload)
    data_chunk = b"DATA" + BinaryWriter.pack_u32(data_size, endian=">") + data_payload

    # Build standard INFO chunk:
    # 0x00: codec (0 for standard Nintendo BNS DSP-ADPCM)
    # 0x01: loop flag
    # 0x02: channels
    # 0x03: pad
    # 0x04: sample_rate (u16)
    # 0x06: pad2
    # 0x08: loopstart (u32)
    # 0x0C: samples_count (u32)
    # 0x10: channel info offset list offset (0x18)
    # 0x14: unk/reserved (0)
    # 0x18: channel pointer list (channels * 4 bytes)
    # 0x18 + channels * 4: Channel Info structures (channels * 12 bytes: data_off, dsp_off, 0)
    # followed by DSP ADPCM coefficient blocks (channels * 48 bytes)
    samples_count = len(channel_samples[0]) if channel_samples else 0
    info_writer = BinaryWriter(endian=">")
    info_writer.write_u8(0)  # Codec: 0 = DSP-ADPCM (Nintendo BNS standard)
    info_writer.write_u8(1 if loop else 0)
    info_writer.write_u8(channels)
    info_writer.write_u8(0)  # pad
    info_writer.write_u16(sample_rate)
    info_writer.write_u16(0)  # pad2
    info_writer.write_u32(0)  # loopstart
    info_writer.write_u32(samples_count)
    info_writer.write_u32(0x18)  # channel info offset list offset
    info_writer.write_u32(0)  # unk/reserved

    # Calculate layout offsets
    ch_info_base = 0x18 + (channels * 4)
    dsp_coeff_base = ch_info_base + (channels * 12)

    # 1. Write Channel Info Pointer Table at 0x18
    for ch in range(channels):
        info_writer.write_u32(ch_info_base + (ch * 12))

    # 2. Write Channel Info structures (12 bytes each)
    bytes_per_ch = len(encoded_channel_bytes[0]) if encoded_channel_bytes else 0
    for ch in range(channels):
        ch_data_offset = ch * bytes_per_ch
        ch_dsp_offset = dsp_coeff_base + (ch * 0x30)
        info_writer.write_u32(ch_data_offset)  # offset to channel data in DATA chunk
        info_writer.write_u32(ch_dsp_offset)   # offset to DSP coefficients in INFO chunk
        info_writer.write_u32(0)               # reserved (always 0)

    # 3. Write Channel coefficient blocks (48 bytes each)
    for _ in range(channels):
        for c in DEFAULT_DSP_COEFFS:
            info_writer.write_s16(c)
        info_writer.write_bytes(b"\x00" * 16)  # padding/history

    info_payload = info_writer.to_bytes()
    # Pad INFO chunk to 4-byte boundary
    pad_len = (4 - (len(info_payload) % 4)) % 4
    info_payload += b"\x00" * pad_len
    info_size = 8 + len(info_payload)
    info_chunk = b"INFO" + BinaryWriter.pack_u32(info_size, endian=">") + info_payload

    # Build BNS file
    header_size = 0x20  # 16 bytes header + 2 * 8 bytes chunkinfo
    info_chunk_offset = header_size
    data_chunk_offset = info_chunk_offset + len(info_chunk)
    total_file_size = data_chunk_offset + len(data_chunk)

    hdr = BNSHeaderStruct(
        magic=BNS_MAGIC,
        bom=0xFEFF0100,
        filesize=total_file_size,
        headersize=header_size,
        chunkcount=2,
    )
    bns_out = bytearray(hdr.to_bytes())
    # Chunk 0: INFO
    bns_out.extend(BinaryWriter.pack_u32(info_chunk_offset, endian=">"))
    bns_out.extend(BinaryWriter.pack_u32(info_size, endian=">"))
    # Chunk 1: DATA
    bns_out.extend(BinaryWriter.pack_u32(data_chunk_offset, endian=">"))
    bns_out.extend(BinaryWriter.pack_u32(data_size, endian=">"))

    bns_out.extend(info_chunk)
    bns_out.extend(data_chunk)
    return bytes(bns_out)


# ==============================================================================
# High-Level Classes: WiiBanner & GCBanner
# ==============================================================================


class GCBanner:
    """
    GameCube optical disc opening banner (BNR1 / BNR2).
    Contains 96x32 RGB5A3 icon graphics and single- or multi-language comments.
    """

    def __init__(
        self,
        magic: bytes = BNR1_MAGIC,
        image_data: Optional[bytes] = None,
        comments: Optional[List[GCCommentStruct]] = None,
    ) -> None:
        self.magic: bytes = magic
        self.image_data: bytes = image_data or (b"\x00" * GC_IMAGE_SIZE)
        self.comments: List[GCCommentStruct] = comments or [GCCommentStruct()]

    @property
    def is_multi_language(self) -> bool:
        return self.magic == BNR2_MAGIC or len(self.comments) > 1

    @classmethod
    def from_bytes(cls, data: bytes) -> GCBanner:
        """Parses GameCube BNR1 / BNR2 banner bytes."""
        if len(data) < 32 + GC_IMAGE_SIZE:
            raise ParseError(f"Data too short for GameCube banner ({len(data)} bytes).")

        magic = data[:4]
        if magic not in (BNR1_MAGIC, BNR2_MAGIC):
            raise ParseError(f"Invalid GameCube banner magic: expected BNR1/BNR2, got {magic!r}")

        image_data = data[32 : 32 + GC_IMAGE_SIZE]
        pos = 32 + GC_IMAGE_SIZE
        comment_count = 6 if magic == BNR2_MAGIC else 1
        default_enc = "cp1252" if magic == BNR2_MAGIC else "shift-jis"
        comments: List[GCCommentStruct] = []

        for _ in range(comment_count):
            if pos + 320 <= len(data):
                comment = GCCommentStruct.from_bytes(data[pos : pos + 320])
                comment.encoding = default_enc
                comments.append(comment)
                pos += 320
            else:
                comments.append(GCCommentStruct(encoding=default_enc))

        return cls(magic=magic, image_data=image_data, comments=comments)

    def to_bytes(self) -> bytes:
        """Serializes GameCube banner into valid binary bytes."""
        hdr = GCBannerHeaderStruct(magic=self.magic)
        out = bytearray(hdr.to_bytes())

        # Ensure image is exactly 6,144 bytes
        img = self.image_data
        if len(img) < GC_IMAGE_SIZE:
            img = img + b"\x00" * (GC_IMAGE_SIZE - len(img))
        elif len(img) > GC_IMAGE_SIZE:
            img = img[:GC_IMAGE_SIZE]
        out.extend(img)

        comment_count = 6 if self.magic == BNR2_MAGIC else 1
        default_enc = "cp1252" if self.magic == BNR2_MAGIC else "shift-jis"
        for i in range(comment_count):
            if i < len(self.comments):
                out.extend(self.comments[i].to_bytes())
            else:
                out.extend(GCCommentStruct(encoding=default_enc).to_bytes())

        return bytes(out)

    def save(self, path: Union[str, Path]) -> None:
        """Saves banner bytes to file."""
        Path(path).write_bytes(self.to_bytes())

    def get_title(self, lang_idx: int = 0) -> str:
        """Retrieves short game title for language index."""
        if 0 <= lang_idx < len(self.comments):
            return self.comments[lang_idx].short_title
        return ""

    def set_title(
        self,
        title: str,
        lang_idx: int = 0,
        full_title: Optional[str] = None,
        company: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        """Updates game title and metadata for language index."""
        default_enc = "cp1252" if self.magic == BNR2_MAGIC else "shift-jis"
        while len(self.comments) <= lang_idx:
            self.comments.append(GCCommentStruct(encoding=default_enc))
        c = self.comments[lang_idx]
        c.short_title = title
        c.full_title = full_title or title
        if company is not None:
            c.short_company = company
            c.full_company = company
        if description is not None:
            c.description = description

    def get_image(self) -> PNGImage:
        """Decodes the 96x32 RGB5A3 icon to a PNGImage."""
        rgba = decode_rgb5a3(self.image_data, GC_IMAGE_WIDTH, GC_IMAGE_HEIGHT)
        return PNGImage(
            width=GC_IMAGE_WIDTH,
            height=GC_IMAGE_HEIGHT,
            color_type=6,  # RGBA
            bit_depth=8,
            pixels=rgba,
        )

    def set_image(self, image_or_rgba: Any) -> None:
        """
        Encodes an image (PNGImage, PIL Image, file path, or RGBA bytes)
        into the 96x32 RGB5A3 icon.
        """
        if HAS_PIL and isinstance(image_or_rgba, Image.Image):
            img = image_or_rgba.convert("RGBA")
            if img.size != (GC_IMAGE_WIDTH, GC_IMAGE_HEIGHT):
                img = img.resize((GC_IMAGE_WIDTH, GC_IMAGE_HEIGHT))
            rgba = img.tobytes()
        elif isinstance(image_or_rgba, PNGImage):
            if (image_or_rgba.width, image_or_rgba.height) != (GC_IMAGE_WIDTH, GC_IMAGE_HEIGHT):
                if HAS_PIL:
                    img = Image.frombytes("RGBA", (image_or_rgba.width, image_or_rgba.height), image_or_rgba.to_rgba_bytes()).resize((GC_IMAGE_WIDTH, GC_IMAGE_HEIGHT))
                    rgba = img.tobytes()
                else:
                    raise ValueError(f"PNGImage must be {GC_IMAGE_WIDTH}x{GC_IMAGE_HEIGHT} without Pillow (got {image_or_rgba.width}x{image_or_rgba.height}).")
            else:
                rgba = image_or_rgba.to_rgba_bytes()
        elif isinstance(image_or_rgba, (bytes, bytearray)):
            raw_input = bytes(image_or_rgba)
            if raw_input.startswith(PNGCodec.PNG_SIGNATURE):
                w, h, rgba = PNGCodec.png_to_rgba(raw_input)
                if (w, h) != (GC_IMAGE_WIDTH, GC_IMAGE_HEIGHT):
                    if HAS_PIL:
                        img = Image.frombytes("RGBA", (w, h), rgba).resize((GC_IMAGE_WIDTH, GC_IMAGE_HEIGHT))
                        rgba = img.tobytes()
                    else:
                        raise ValueError(f"PNG image must be {GC_IMAGE_WIDTH}x{GC_IMAGE_HEIGHT} without Pillow (got {w}x{h}).")
            else:
                rgba = raw_input
        elif isinstance(image_or_rgba, (str, Path)):
            file_path = Path(image_or_rgba)
            if not file_path.is_file():
                raise FileNotFoundError(f"Image file not found: {file_path}")
            raw_bytes = file_path.read_bytes()
            if raw_bytes.startswith(PNGCodec.PNG_SIGNATURE):
                w, h, rgba = PNGCodec.png_to_rgba(raw_bytes)
                if (w, h) != (GC_IMAGE_WIDTH, GC_IMAGE_HEIGHT):
                    if HAS_PIL:
                        img = Image.open(file_path).convert("RGBA").resize((GC_IMAGE_WIDTH, GC_IMAGE_HEIGHT))
                        rgba = img.tobytes()
                    else:
                        raise ValueError(f"PNG image must be {GC_IMAGE_WIDTH}x{GC_IMAGE_HEIGHT} without Pillow (got {w}x{h}).")
            elif HAS_PIL:
                img = Image.open(file_path).convert("RGBA").resize((GC_IMAGE_WIDTH, GC_IMAGE_HEIGHT))
                rgba = img.tobytes()
            else:
                raise ImportError("Pillow is required to load non-PNG images from file path.")
        else:
            raise ValueError(f"Unsupported image type: {type(image_or_rgba)}")

        self.image_data = encode_rgb5a3(rgba, GC_IMAGE_WIDTH, GC_IMAGE_HEIGHT)

    def to_png_bytes(self) -> bytes:
        """Encodes the 96x32 icon into PNG binary bytes. Zero dependencies."""
        rgba = decode_rgb5a3(self.image_data, GC_IMAGE_WIDTH, GC_IMAGE_HEIGHT)
        return PNGCodec.rgba_to_png(GC_IMAGE_WIDTH, GC_IMAGE_HEIGHT, rgba)

    def save_image_png(self, path: Union[str, Path]) -> None:
        """Saves the 96x32 icon as a PNG image file on disk. Zero dependencies."""
        Path(path).write_bytes(self.to_png_bytes())


class WiiBanner:
    """
    Nintendo Wii optical disc opening banner (opening.bnr / 00000000.app).
    Manages IMET 10-language UTF-16 titles, IMD5 checksums, root U8 archive,
    and BNS banner audio jingles.
    """

    def __init__(
        self,
        imet_header: Optional[IMETHeaderStruct] = None,
        titles: Optional[Dict[str, str]] = None,
        banner_bin: Optional[bytes] = None,
        icon_bin: Optional[bytes] = None,
        sound_bin: Optional[bytes] = None,
    ) -> None:
        self.imet_header: IMETHeaderStruct = imet_header or IMETHeaderStruct()
        self.titles: Dict[str, str] = dict(titles or {})
        self.banner_bin: bytes = banner_bin or b""
        self.icon_bin: bytes = icon_bin or b""
        self.sound_bin: bytes = sound_bin or b""

    @classmethod
    def from_bytes(cls, data: bytes) -> WiiBanner:
        """Parses Wii opening.bnr binary bytes."""
        imet_offset = data.find(IMET_MAGIC)
        if imet_offset == -1 or len(data) < imet_offset + 1472:
            raise ParseError("Invalid Wii opening.bnr: IMET header not found.")

        # Header begins at imet_offset - 0x40 (or 0x00 if at start)
        prefix_len = min(imet_offset, 0x40)
        imet_raw = data[imet_offset - prefix_len : imet_offset + 1472]
        imet_hdr = IMETHeaderStruct.from_bytes(imet_raw)

        # Parse 10 language titles (each 84 bytes = 42 UTF-16-BE characters)
        titles: Dict[str, str] = {}
        names_bytes = imet_hdr.names_raw
        for i, lang_code in enumerate(WII_LANGUAGES):
            entry_bytes = names_bytes[i * 84 : (i + 1) * 84]
            # Strip trailing UTF-16 nulls
            decoded = entry_bytes.decode("utf-16-be", errors="replace").rstrip("\x00")
            titles[lang_code] = decoded

        # Root U8 archive starts at offset 0x600 on optical disc
        u8_offset = 0x600 if len(data) >= 0x600 else imet_offset + 1472
        banner_bin = b""
        icon_bin = b""
        sound_bin = b""

        if u8_offset < len(data):
            u8_bytes = data[u8_offset:]
            try:
                archive = U8Archive.from_bytes(u8_bytes)
                for fpath, file_data in archive.files.items():
                    norm_path = fpath.replace("\\", "/").lstrip("/")
                    if norm_path.endswith("banner.bin"):
                        banner_bin = file_data
                    elif norm_path.endswith("icon.bin"):
                        icon_bin = file_data
                    elif norm_path.endswith("sound.bin"):
                        sound_bin = file_data
            except Exception:
                # If root is not standard U8, keep tail raw
                pass

        return cls(
            imet_header=imet_hdr,
            titles=titles,
            banner_bin=banner_bin,
            icon_bin=icon_bin,
            sound_bin=sound_bin,
        )

    def to_bytes(self) -> bytes:
        """
        Serializes Wii opening.bnr into valid binary bytes with recomputed IMD5 and IMET MD5.
        """
        # 1. Ensure sub-files are wrapped in IMD5
        wrapped_banner = self.banner_bin
        if wrapped_banner and not wrapped_banner.startswith(IMD5_MAGIC):
            wrapped_banner = wrap_imd5(wrapped_banner)

        wrapped_icon = self.icon_bin
        if wrapped_icon and not wrapped_icon.startswith(IMD5_MAGIC):
            wrapped_icon = wrap_imd5(wrapped_icon)

        wrapped_sound = self.sound_bin
        if wrapped_sound and not wrapped_sound.startswith(IMD5_MAGIC):
            wrapped_sound = wrap_imd5(wrapped_sound)

        # 2. Build root U8 archive
        archive = U8Archive()
        if wrapped_banner:
            archive["meta/banner.bin"] = wrapped_banner
        if wrapped_icon:
            archive["meta/icon.bin"] = wrapped_icon
        if wrapped_sound:
            archive["meta/sound.bin"] = wrapped_sound
        u8_payload = archive.to_bytes()

        # 3. Pack 10 language names into 84-byte UTF-16-BE buffers
        names_buf = bytearray(10 * 84)
        for i, lang_code in enumerate(WII_LANGUAGES):
            title_str = self.titles.get(lang_code, "")
            encoded = title_str.encode("utf-16-be")
            while len(encoded) > 82 and title_str:
                title_str = title_str[:-1]
                encoded = title_str.encode("utf-16-be")
            # Write into slot
            names_buf[i * 84 : i * 84 + len(encoded)] = encoded

        # 4. Prepare IMET Header with updated sizes
        imet_data = bytearray(0x600)
        # Magic at 0x40
        imet_data[0x40:0x44] = IMET_MAGIC
        imet_data[0x44:0x48] = BinaryWriter.pack_u32(0x0600, endian=">")
        imet_data[0x48:0x4C] = BinaryWriter.pack_u32(3, endian=">")  # version 3
        imet_data[0x4C:0x50] = BinaryWriter.pack_u32(len(wrapped_icon), endian=">")
        imet_data[0x50:0x54] = BinaryWriter.pack_u32(len(wrapped_banner), endian=">")
        imet_data[0x54:0x58] = BinaryWriter.pack_u32(len(wrapped_sound), endian=">")
        imet_data[0x58:0x5C] = BinaryWriter.pack_u32(self.imet_header.flags, endian=">")
        # Names table at 0x5C..0x3A4
        imet_data[0x5C : 0x5C + 840] = names_buf

        # 5. Compute IMET MD5
        md5_digest = calculate_imet_md5(bytes(imet_data))
        imet_data[0x5F0:0x600] = md5_digest

        return bytes(imet_data) + u8_payload

    def save(self, path: Union[str, Path]) -> None:
        """Saves banner bytes to file."""
        Path(path).write_bytes(self.to_bytes())

    def _resolve_lang(self, lang: Union[str, int]) -> str:
        if isinstance(lang, int):
            if 0 <= lang < len(WII_LANGUAGES):
                return WII_LANGUAGES[lang]
            raise IndexError(f"Wii language index out of range: {lang} (must be 0..{len(WII_LANGUAGES)-1}).")
        key = str(lang).strip().lower()
        if key in WII_LANGUAGES:
            return key
        if key in WII_LANGUAGE_ALIASES:
            return WII_LANGUAGE_ALIASES[key]
        raise ValueError(f"Unknown Wii language code {lang!r}. Valid: {WII_LANGUAGES}")

    def get_title(self, lang: Union[str, int] = "en") -> str:
        """Retrieves game title for language code (e.g. 'en', 'jp', or 0..9)."""
        code = self._resolve_lang(lang)
        return self.titles.get(code, self.titles.get("en", ""))

    def set_title(self, title: str, lang: Union[str, int] = "en") -> None:
        """Sets game title for language code."""
        code = self._resolve_lang(lang)
        self.titles[code] = str(title)

    def get_all_titles(self) -> Dict[str, str]:
        """Returns all 10 language titles as a dictionary."""
        return dict(self.titles)

    def set_all_titles(self, titles: Dict[str, str]) -> None:
        """Updates multiple language titles at once."""
        for lang, text in titles.items():
            try:
                code = self._resolve_lang(lang)
                self.titles[code] = text
            except (ValueError, IndexError):
                pass

    def get_sound_wav(self) -> bytes:
        """Unwraps and decodes sound.bin audio to standard WAV bytes."""
        raw_sound = unwrap_imd5(self.sound_bin)
        return decode_bns_to_wav(raw_sound)

    def set_sound_wav(self, wav_bytes: bytes, loop: bool = True) -> None:
        """Encodes WAV audio into BNS and wraps with IMD5 for sound.bin."""
        bns_data = encode_wav_to_bns(wav_bytes, loop=loop)
        self.sound_bin = wrap_imd5(bns_data)


# ==============================================================================
# Unified Factory (Layer 2)
# ==============================================================================


class BannerFile:
    """
    Unified entry point for Nintendo opening banner files (opening.bnr).
    Automatically detects whether data belongs to Wii or GameCube.
    """

    @classmethod
    def from_bytes(cls, data: bytes) -> Union[WiiBanner, GCBanner]:
        """Automatically parses either Wii or GameCube banner from binary bytes."""
        if len(data) >= 4 and data[:4] in (BNR1_MAGIC, BNR2_MAGIC):
            return GCBanner.from_bytes(data)

        # Check for IMET magic at 0x00, 0x40, or 0x80
        if IMET_MAGIC in data[:0x100]:
            return WiiBanner.from_bytes(data)

        raise ParseError(f"Unrecognized banner format (magic {data[:4]!r}).")

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> Union[WiiBanner, GCBanner]:
        """Loads and parses banner from a file path."""
        return cls.from_bytes(Path(path).read_bytes())
