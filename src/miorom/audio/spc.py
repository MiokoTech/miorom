"""
miorom.audio.spc
~~~~~~~~~~~~~~~~
Super Nintendo (SNES) SPC700 Sound File (.spc) Container Parser and BRR Dumper.
Extracts 64KB SPC700 sound RAM, DSP registers, ID666 metadata tags,
and parses S-DSP BRR sample directories for direct WAV export.
"""

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from miorom.audio.brr import BRRCodec
from miorom.result import MioRomResult


@dataclass
class SpcHeader(MioRomResult):
    """Metadata and CPU registers extracted from an SPC700 sound file header."""
    song_title: str
    game_title: str
    dumper_name: str
    artist: str
    comments: str
    date_dumped: str
    pc: int
    a: int
    x: int
    y: int
    psw: int
    sp: int
    duration_seconds: int = 0


class SpcFile(MioRomResult):
    """
    Super Nintendo SPC700 sound file format (.spc) reader and audio sample extractor.
    Houses the 64KB audio RAM, DSP registers, CPU execution context, and sample directory.
    """

    MAGIC = b"SNES-SPC700 Sound File Data v0.30"
    HEADER_SIZE = 0x100
    RAM_SIZE = 0x10000
    DSP_REGS_SIZE = 128
    TOTAL_MIN_SIZE = 0x10180

    def __init__(
        self,
        header: SpcHeader,
        ram: Union[bytes, bytearray],
        dsp_regs: Union[bytes, bytearray],
        ipl_rom: Optional[Union[bytes, bytearray]] = None,
    ):
        self.header = header
        self.ram = bytearray(ram)
        self.dsp_regs = bytearray(dsp_regs)
        self.ipl_rom = bytearray(ipl_rom or (b"\x00" * 64))

    @classmethod
    def from_bytes(cls, data: Union[bytes, bytearray]) -> "SpcFile":
        """Parse an SPC sound file from a binary byte buffer."""
        if len(data) < cls.TOTAL_MIN_SIZE:
            raise ValueError(f"SPC data too small ({len(data)} < {cls.TOTAL_MIN_SIZE} bytes)")

        if not data.startswith(cls.MAGIC):
            raise ValueError("Invalid SPC file magic signature")

        pc, a, x, y, psw, sp = struct.unpack_from("<HBBBBB", data, 0x25)

        # Parse ID666 textual tags
        song_title = data[0x2E:0x4E].decode("ascii", errors="replace").rstrip("\x00").strip()
        game_title = data[0x4E:0x6E].decode("ascii", errors="replace").rstrip("\x00").strip()
        dumper_name = data[0x6E:0x7E].decode("ascii", errors="replace").rstrip("\x00").strip()
        comments = data[0x7E:0x9E].decode("ascii", errors="replace").rstrip("\x00").strip()
        date_dumped = data[0x9E:0xA9].decode("ascii", errors="replace").rstrip("\x00").strip()
        artist = data[0xB1:0xD1].decode("ascii", errors="replace").rstrip("\x00").strip()

        duration_raw = data[0xA9:0xAC].decode("ascii", errors="replace").rstrip("\x00").strip()
        duration_sec = 0
        if duration_raw.isdigit():
            duration_sec = int(duration_raw)

        header = SpcHeader(
            song_title=song_title,
            game_title=game_title,
            dumper_name=dumper_name,
            artist=artist,
            comments=comments,
            date_dumped=date_dumped,
            pc=pc,
            a=a,
            x=x,
            y=y,
            psw=psw,
            sp=sp,
            duration_seconds=duration_sec,
        )

        ram = data[0x100:0x10100]
        dsp_regs = data[0x10100:0x10180]
        ipl_rom = data[0x101C0:0x10200] if len(data) >= 0x10200 else None

        return cls(header=header, ram=ram, dsp_regs=dsp_regs, ipl_rom=ipl_rom)

    def to_bytes(self) -> bytes:
        """Serialize the SPC file back into binary format."""
        out = bytearray(0x10200)

        # Magic and header identifiers
        out[0:len(self.MAGIC)] = self.MAGIC
        out[0x21:0x23] = b"\x1A\x1A"
        out[0x23] = 0x1A  # ID666 present
        out[0x24] = 0x1E  # v0.30

        struct.pack_into(
            "<HBBBBB",
            out,
            0x25,
            self.header.pc,
            self.header.a,
            self.header.x,
            self.header.y,
            self.header.psw,
            self.header.sp,
        )

        out[0x2E:0x4E] = self.header.song_title.encode("ascii", errors="replace")[:32].ljust(32, b"\x00")
        out[0x4E:0x6E] = self.header.game_title.encode("ascii", errors="replace")[:32].ljust(32, b"\x00")
        out[0x6E:0x7E] = self.header.dumper_name.encode("ascii", errors="replace")[:16].ljust(16, b"\x00")
        out[0x7E:0x9E] = self.header.comments.encode("ascii", errors="replace")[:32].ljust(32, b"\x00")
        out[0x9E:0xA9] = self.header.date_dumped.encode("ascii", errors="replace")[:11].ljust(11, b"\x00")
        out[0xB1:0xD1] = self.header.artist.encode("ascii", errors="replace")[:32].ljust(32, b"\x00")

        if self.header.duration_seconds > 0:
            dur_str = f"{self.header.duration_seconds:03d}"[:3].encode("ascii")
            out[0xA9:0xAC] = dur_str

        out[0x100:0x10100] = self.ram[:self.RAM_SIZE]
        out[0x10100:0x10180] = self.dsp_regs[:self.DSP_REGS_SIZE]
        out[0x101C0:0x10200] = self.ipl_rom[:64]

        return bytes(out)

    def get_dsp_dir_address(self) -> int:
        """Return the base address in SPC700 RAM of the BRR sample directory table."""
        # S-DSP register 0x3D specifies the DIR page byte
        dir_page = self.dsp_regs[0x3D] if len(self.dsp_regs) > 0x3D else 0
        return dir_page << 8

    def list_samples(self, max_samples: int = 128) -> List[Tuple[int, int, int]]:
        """
        Parse the S-DSP sample directory table from RAM.
        Returns list of (sample_index, start_address, loop_address).
        """
        dir_addr = self.get_dsp_dir_address()
        samples: List[Tuple[int, int, int]] = []

        for idx in range(max_samples):
            entry_off = dir_addr + (idx * 4)
            if entry_off + 4 > len(self.ram):
                break

            start_addr, loop_addr = struct.unpack_from("<HH", self.ram, entry_off)
            if start_addr == 0 and loop_addr == 0:
                continue
            if start_addr >= len(self.ram):
                continue

            samples.append((idx, start_addr, loop_addr))

        return samples

    def extract_brr_sample(self, start_addr: int) -> bytes:
        """
        Extract raw BRR audio blocks for a sample starting at start_addr until the end bit.
        """
        if start_addr >= len(self.ram):
            return b""

        blocks = bytearray()
        pos = start_addr

        while pos + 9 <= len(self.ram):
            block = self.ram[pos : pos + 9]
            blocks.extend(block)
            header = block[0]
            pos += 9
            # Bit 0 of header byte indicates end of sample
            if (header & 0x01) != 0:
                break

        return bytes(blocks)

    def extract_all_samples(self, max_samples: int = 128) -> Dict[int, bytes]:
        """Extract all valid BRR samples defined in the S-DSP directory table."""
        entries = self.list_samples(max_samples=max_samples)
        sample_dict: Dict[int, bytes] = {}

        for idx, start_addr, _ in entries:
            brr_bytes = self.extract_brr_sample(start_addr)
            if brr_bytes:
                sample_dict[idx] = brr_bytes

        return sample_dict

    def dump_samples_to_wav(self, sample_rate: int = 32000, max_samples: int = 128) -> Dict[int, bytes]:
        """
        Extract all BRR samples and convert them directly into RIFF/WAVE PCM format.
        Returns mapping of sample_index -> wav_bytes.
        """
        brr_map = self.extract_all_samples(max_samples=max_samples)
        wav_map: Dict[int, bytes] = {}

        for idx, brr_bytes in brr_map.items():
            try:
                wav_map[idx] = BRRCodec.to_wav(brr_bytes, sample_rate=sample_rate)
            except Exception:
                continue

        return wav_map

    def read_ram(self, address: int, size: int) -> bytes:
        """Read bytes directly from SPC700 audio RAM."""
        if address + size > len(self.ram):
            raise IndexError(f"RAM read out of bounds (0x{address:04X} + {size} > {len(self.ram)})")
        return bytes(self.ram[address : address + size])

    def write_ram(self, address: int, data: Union[bytes, bytearray]) -> None:
        """Write bytes directly into SPC700 audio RAM."""
        if address + len(data) > len(self.ram):
            raise IndexError(f"RAM write out of bounds (0x{address:04X} + {len(data)} > {len(self.ram)})")
        self.ram[address : address + len(data)] = data
