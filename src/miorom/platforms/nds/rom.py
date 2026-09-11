from miorom.result import MioRomResult
import os
from miorom.errors import ParseError, RelocationError
from miorom.security import sanitize_extract_path
from dataclasses import dataclass
from miorom.core.schema import BinaryStruct, FixedString, RawBytes, U8, U16, U32
from typing import List, Optional, Tuple, Dict, Any, Union

BANNER_LANGUAGES = {
    0: "Japanese",
    1: "English",
    2: "French",
    3: "German",
    4: "Italian",
    5: "Spanish",
}


@dataclass
class NDSFileEntry(MioRomResult):
    id: int
    start_offset: int
    end_offset: int
    size: int


@dataclass
class NDSOverlayEntry(MioRomResult):
    id: int
    ram_address: int
    ram_size: int
    bss_size: int
    sinit_init: int
    sinit_init_end: int
    file_id: int
    flags: int

    @property
    def ram_hex(self) -> str:
        return f"0x{self.ram_address:08X}"


@dataclass
class NDSHeader(MioRomResult):
    game_title: str
    game_code: str
    maker_code: str
    unit_code: int
    arm9_offset: int
    arm9_entry_address: int
    arm9_ram_address: int
    arm9_size: int
    arm7_offset: int
    arm7_entry_address: int
    arm7_ram_address: int
    arm7_size: int
    fnt_offset: int
    fnt_size: int
    fat_offset: int
    fat_size: int
    banner_offset: int
    arm9_overlay_offset: int = 0
    arm9_overlay_size: int = 0
    arm7_overlay_offset: int = 0
    arm7_overlay_size: int = 0
    header_crc: int = 0

class NDSHeaderStruct(BinaryStruct):
    _endian = "<"
    game_title = FixedString(12)
    game_code = FixedString(4)
    maker_code = FixedString(2)
    unit_code = U8()
    _reserved_0x13 = RawBytes(13)
    arm9_offset = U32()
    arm9_entry_address = U32()
    arm9_ram_address = U32()
    arm9_size = U32()
    arm7_offset = U32()
    arm7_entry_address = U32()
    arm7_ram_address = U32()
    arm7_size = U32()
    fnt_offset = U32()
    fnt_size = U32()
    fat_offset = U32()
    fat_size = U32()
    arm9_overlay_offset = U32()
    arm9_overlay_size = U32()
    arm7_overlay_offset = U32()
    arm7_overlay_size = U32()
    _reserved_0x60 = RawBytes(8)
    banner_offset = U32()
    _reserved_0x6C = RawBytes(0xF2)
    header_crc = U16()

class NDSFatEntryStruct(BinaryStruct):
    _endian = "<"
    start_offset = U32()
    end_offset = U32()

class NDSOverlayEntryStruct(BinaryStruct):
    _endian = "<"
    id = U32()
    ram_address = U32()
    ram_size = U32()
    bss_size = U32()
    sinit_init = U32()
    sinit_init_end = U32()
    file_id = U32()
    flags = U32()

class NDSFntDirectoryEntryStruct(BinaryStruct):
    _endian = "<"
    first_entry_offset = U32()
    first_file_id = U16()
    parent_directory_id = U16()

class NDSHeaderCrcStruct(BinaryStruct):
    _endian = "<"
    checksum = U16()


class NDSRom:
    """
    Nintendo DS ROM (.nds) header and filesystem inspector.
    Extracts internal binaries (ARM9, ARM7), FAT tables, and multilingual banner titles.
    """

    def __init__(self, data: bytes):
        self.data = bytearray(data) if isinstance(data, (bytearray, bytes)) else bytearray(data)
        if len(data) < 0x200:
            raise ParseError("Data too small to be an NDS ROM.")

        self._fnt_cache: Optional[Dict[str, int]] = None
        self._parse_header()

    @classmethod
    def from_file(cls, filepath: str) -> "NDSRom":
        with open(filepath, "rb") as f:
            return cls(f.read())

    def _parse_header(self):
        parsed = NDSHeaderStruct.from_bytes(self.data, offset=0)

        self.header = NDSHeader(
            game_title=parsed.game_title,
            game_code=parsed.game_code,
            maker_code=parsed.maker_code,
            unit_code=parsed.unit_code,
            arm9_offset=parsed.arm9_offset,
            arm9_entry_address=parsed.arm9_entry_address,
            arm9_ram_address=parsed.arm9_ram_address,
            arm9_size=parsed.arm9_size,
            arm7_offset=parsed.arm7_offset,
            arm7_entry_address=parsed.arm7_entry_address,
            arm7_ram_address=parsed.arm7_ram_address,
            arm7_size=parsed.arm7_size,
            fnt_offset=parsed.fnt_offset,
            fnt_size=parsed.fnt_size,
            fat_offset=parsed.fat_offset,
            fat_size=parsed.fat_size,
            banner_offset=parsed.banner_offset,
            arm9_overlay_offset=parsed.arm9_overlay_offset,
            arm9_overlay_size=parsed.arm9_overlay_size,
            arm7_overlay_offset=parsed.arm7_overlay_offset,
            arm7_overlay_size=parsed.arm7_overlay_size,
            header_crc=parsed.header_crc,
        )

        # Backwards-compatible aliases
        self.title = parsed.game_title
        self.game_code = parsed.game_code
        self.maker_code = parsed.maker_code
        self.unit_code = parsed.unit_code
        self.arm9_offset = parsed.arm9_offset
        self.arm9_entry = parsed.arm9_entry_address
        self.arm9_ram_addr = parsed.arm9_ram_address
        self.arm9_size = parsed.arm9_size
        self.arm7_offset = parsed.arm7_offset
        self.arm7_entry = parsed.arm7_entry_address
        self.arm7_ram_addr = parsed.arm7_ram_address
        self.arm7_size = parsed.arm7_size
        self.fnt_offset = parsed.fnt_offset
        self.fnt_size = parsed.fnt_size
        self.fat_offset = parsed.fat_offset
        self.fat_size = parsed.fat_size
        self.banner_offset = parsed.banner_offset
        self.arm9_overlay_offset = parsed.arm9_overlay_offset
        self.arm9_overlay_size = parsed.arm9_overlay_size
        self.arm7_overlay_offset = parsed.arm7_overlay_offset
        self.arm7_overlay_size = parsed.arm7_overlay_size

    def get_arm9_binary(self) -> bytes:
        return self.data[self.arm9_offset : self.arm9_offset + self.arm9_size]

    def get_arm7_binary(self) -> bytes:
        return self.data[self.arm7_offset : self.arm7_offset + self.arm7_size]

    def get_banner_title(self, language: int = 1) -> str:
        """
        Reads game title from the ROM banner.
        Languages: 0=JP, 1=EN, 2=FR, 3=DE, 4=IT, 5=ES. Default: 1 (English).
        """
        if self.banner_offset == 0 or self.banner_offset >= len(self.data):
            return self.title

        banner_data = self.data[self.banner_offset:]
        if len(banner_data) < 0x240:
            return self.title

        # Titles start at banner_offset + 0x240 (576 bytes)
        # Each title is 256 bytes of UTF-16-LE string
        title_start = self.banner_offset + 0x240 + (language * 256)
        if title_start + 256 > len(self.data):
            return self.title

        title_raw = self.data[title_start : title_start + 256]
        null_pos = title_raw.find(b"\x00\x00")
        if null_pos != -1:
            title_raw = title_raw[:null_pos + (null_pos % 2)]

        try:
            return title_raw.decode("utf-16-le").strip()
        except UnicodeDecodeError:
            return self.title

    def list_files(self) -> List[NDSFileEntry]:
        """Lists all files in the ROM File Allocation Table (FAT)."""
        if self.fat_offset == 0 or self.fat_size == 0:
            return []

        entries = []
        count = self.fat_size // 8
        for i in range(count):
            off = self.fat_offset + (i * 8)
            entry = NDSFatEntryStruct.from_bytes(self.data, offset=off)
            start = entry.start_offset
            end = entry.end_offset
            entries.append(NDSFileEntry(
                id=i,
                start_offset=start,
                end_offset=end,
                size=max(0, end - start)
            ))
        return entries

    def get_file(self, file_id_or_path: Union[int, str]) -> bytes:
        """Extracts a file by its FAT ID or FNT path."""
        if isinstance(file_id_or_path, str):
            fnt = self.resolve_fnt()
            norm = file_id_or_path.lstrip("/").replace("\\", "/")
            if norm not in fnt:
                raise FileNotFoundError(f"File '{norm}' not found in NDS FNT.")
            file_id = fnt[norm]
        else:
            file_id = file_id_or_path

        off = self.fat_offset + (file_id * 8)
        if off + 8 > len(self.data):
            raise IndexError(f"File ID {file_id} out of FAT range.")

        entry = NDSFatEntryStruct.from_bytes(self.data, offset=off)
        start = entry.start_offset
        end = entry.end_offset
        return bytes(self.data[start:end])

    def resolve_fnt(self) -> Dict[str, int]:
        """
        Parses the File Name Table (FNT) directory tree into a path -> file_id mapping.
        """
        if self._fnt_cache is not None:
            return self._fnt_cache

        if self.fnt_offset == 0 or self.fnt_size < 8:
            return {}

        d = self.data
        fnt_off = self.fnt_offset

        def walk_dir(dir_idx: int = 0, prefix: str = "") -> Dict[str, int]:
            dir_entry_off = fnt_off + (dir_idx * 8)
            if dir_entry_off + 8 > len(d):
                return {}
            directory_entry = NDSFntDirectoryEntryStruct.from_bytes(d, offset=dir_entry_off)
            sub_off = directory_entry.first_entry_offset
            cur_file_id = directory_entry.first_file_id
            pos = fnt_off + sub_off
            mapping: Dict[str, int] = {}
            while pos < len(d):
                b = d[pos]
                pos += 1
                if b == 0:
                    break
                is_dir = bool(b & 0x80)
                name_len = b & 0x7F
                if pos + name_len > len(d):
                    break
                name = d[pos : pos + name_len].decode("ascii", errors="replace")
                pos += name_len
                if is_dir:
                    if pos + 2 > len(d):
                        break
                    sub_dir_id = U16().unpack(d, pos, "<")[0]
                    pos += 2
                    sub_map = walk_dir(sub_dir_id - 0xF000, f"{prefix}{name}/")
                    mapping.update(sub_map)
                else:
                    mapping[f"{prefix}{name}"] = cur_file_id
                    cur_file_id += 1
            return mapping

        self._fnt_cache = walk_dir()
        return self._fnt_cache

    def get_file_by_name(self, path: str) -> bytes:
        """Extracts a file by its relative path inside the NDS filesystem."""
        fnt = self.resolve_fnt()
        norm_path = path.lstrip("/").replace("\\", "/")
        if norm_path not in fnt:
            raise FileNotFoundError(f"File '{norm_path}' not found in NDS FNT.")
        return self.get_file(fnt[norm_path])

    def replace_file(self, file_id_or_path: Union[int, str], new_data: bytes) -> bytearray:
        """
        Replaces an internal file by FAT ID or path, shifting subsequent files if size changed.
        Returns the updated ROM bytearray.
        """
        if isinstance(file_id_or_path, str):
            fnt = self.resolve_fnt()
            norm = file_id_or_path.lstrip("/").replace("\\", "/")
            if norm not in fnt:
                raise FileNotFoundError(f"File '{norm}' not found in NDS FNT.")
            target_id = fnt[norm]
        else:
            target_id = file_id_or_path

        off = self.fat_offset + (target_id * 8)
        if off + 8 > len(self.data):
            raise IndexError(f"File ID {target_id} out of FAT bounds.")

        cur_entry = NDSFatEntryStruct.from_bytes(self.data, offset=off)
        cur_start = cur_entry.start_offset
        cur_end = cur_entry.end_offset
        old_size = cur_end - cur_start
        delta = len(new_data) - old_size

        if delta == 0:
            self.data[cur_start:cur_end] = new_data
            return self.data

        # Shift all data downstream
        if delta > 0:
            tail = self.data[cur_end:]
            self.data[cur_start : cur_start + len(new_data)] = new_data
            self.data[cur_start + len(new_data) :] = tail
        else:
            del self.data[cur_start + len(new_data) : cur_end]
            self.data[cur_start : cur_start + len(new_data)] = new_data

        # Update FAT entry for target
        self.data[off:off + NDSFatEntryStruct.sizeof()] = NDSFatEntryStruct(
            start_offset=cur_start,
            end_offset=cur_start + len(new_data),
        ).to_bytes()

        # Shift all downstream FAT entries
        file_count = self.fat_size // 8
        for i in range(file_count):
            if i == target_id:
                continue
            entry_off = self.fat_offset + (i * 8)
            entry = NDSFatEntryStruct.from_bytes(self.data, offset=entry_off)
            if entry.start_offset >= cur_end:
                self.data[entry_off:entry_off + NDSFatEntryStruct.sizeof()] = NDSFatEntryStruct(
                    start_offset=entry.start_offset + delta,
                    end_offset=entry.end_offset + delta,
                ).to_bytes()

        if len(self.data) >= 0x160:
            self.fix_header_checksum()

        return self.data

    def append_file(
        self,
        file_id_or_path: Union[int, str],
        new_data: bytes,
        alignment: int = 512,
    ) -> int:
        """
        Appends new_data for a file at EOF with sector alignment (default 512 bytes)
        and updates the FAT entry without shifting downstream files.
        Preserves 512-byte DMA hardware alignment and avoids corrupting other assets.
        Returns the new start offset of the file.
        """
        if isinstance(file_id_or_path, str):
            fnt = self.resolve_fnt()
            norm = file_id_or_path.lstrip("/").replace("\\", "/")
            if norm not in fnt:
                raise FileNotFoundError(f"File '{norm}' not found in NDS FNT.")
            target_id = fnt[norm]
        else:
            target_id = file_id_or_path

        fat_entry_off = self.fat_offset + (target_id * 8)
        if fat_entry_off + 8 > len(self.data):
            raise IndexError(f"File ID {target_id} out of FAT bounds.")

        # Align EOF to sector alignment boundary
        cur_len = len(self.data)
        rem = cur_len % alignment
        pad_before = (alignment - rem) % alignment if alignment > 1 else 0
        if pad_before > 0:
            self.data.extend(b"\x00" * pad_before)

        new_start = len(self.data)
        self.data.extend(new_data)
        new_end = len(self.data)

        # Post-data alignment padding
        rem_after = len(self.data) % alignment
        pad_after = (alignment - rem_after) % alignment if alignment > 1 else 0
        if pad_after > 0:
            self.data.extend(b"\x00" * pad_after)

        # Update FAT entry
        self.data[fat_entry_off:fat_entry_off + 8] = NDSFatEntryStruct(
            start_offset=new_start,
            end_offset=new_end,
        ).to_bytes()

        # Recalculate and update header checksum
        if len(self.data) >= 0x160:
            self.fix_header_checksum()

        return new_start

    def ram_to_file_offset(self, ram_addr: int, processor: str = "auto") -> int:
        """
        Translates a runtime RAM address into its physical ROM file offset.
        Validates that the address lies within loaded ARM9 or ARM7 binary bounds.
        """
        proc = processor.lower()
        if proc in ("auto", "arm9"):
            if self.arm9_ram_addr <= ram_addr < self.arm9_ram_addr + self.arm9_size:
                return self.arm9_offset + (ram_addr - self.arm9_ram_addr)

        if proc in ("auto", "arm7"):
            if self.arm7_ram_addr <= ram_addr < self.arm7_ram_addr + self.arm7_size:
                return self.arm7_offset + (ram_addr - self.arm7_ram_addr)

        raise ParseError(
            f"RAM address 0x{ram_addr:08X} does not map to loaded ARM9 "
            f"[0x{self.arm9_ram_addr:08X}..0x{self.arm9_ram_addr + self.arm9_size:08X}) or ARM7."
        )

    def file_to_ram_offset(self, file_off: int) -> int:
        """
        Translates a physical ROM file offset into its runtime RAM address.
        """
        if self.arm9_offset <= file_off < self.arm9_offset + self.arm9_size:
            return self.arm9_ram_addr + (file_off - self.arm9_offset)
        if self.arm7_offset <= file_off < self.arm7_offset + self.arm7_size:
            return self.arm7_ram_addr + (file_off - self.arm7_offset)
        raise ParseError(
            f"File offset 0x{file_off:08X} is outside ARM9 "
            f"[0x{self.arm9_offset:08X}..0x{self.arm9_offset + self.arm9_size:08X}) and ARM7."
        )

    def read_arm9(self, ram_addr: int, length: int) -> bytes:
        """Reads length bytes from ARM9 memory at ram_addr directly from ROM."""
        file_off = self.ram_to_file_offset(ram_addr, processor="arm9")
        if file_off + length > self.arm9_offset + self.arm9_size:
            raise RelocationError("Read exceeds ARM9 binary bounds.")
        return bytes(self.data[file_off : file_off + length])

    def patch_arm9(self, ram_addr: int, patch_data: Union[bytes, bytearray, int]) -> int:
        """
        Patches ARM9 binary at runtime RAM address ram_addr and updates the header checksum.
        If patch_data is an integer, it is packed as a little-endian 32-bit uint.
        Returns the physical file offset that was modified.
        """
        if isinstance(patch_data, int):
            raw = U32().pack(patch_data, endian="<")
        else:
            raw = bytes(patch_data)

        file_off = self.ram_to_file_offset(ram_addr, processor="arm9")
        if file_off + len(raw) > self.arm9_offset + self.arm9_size:
            raise RelocationError(f"Patch at 0x{ram_addr:08X} exceeds ARM9 binary bounds.")

        self.data[file_off : file_off + len(raw)] = raw
        if len(self.data) >= 0x160:
            self.fix_header_checksum()
        return file_off

    def list_overlays(self, processor: str = "arm9") -> List[NDSOverlayEntry]:
        """
        Parses and returns the overlay table entries for ARM9 or ARM7.
        """
        proc = processor.lower()
        if proc == "arm9":
            table_off = self.arm9_overlay_offset
            table_size = self.arm9_overlay_size
        elif proc == "arm7":
            table_off = self.arm7_overlay_offset
            table_size = self.arm7_overlay_size
        else:
            raise RelocationError("Processor must be 'arm9' or 'arm7'")

        if table_off == 0 or table_size == 0 or table_off + table_size > len(self.data):
            return []

        entry_size = 32
        count = table_size // entry_size
        entries: List[NDSOverlayEntry] = []

        for i in range(count):
            off = table_off + (i * entry_size)
            parsed = NDSOverlayEntryStruct.from_bytes(self.data, offset=off)
            entries.append(NDSOverlayEntry(
                id=parsed.id,
                ram_address=parsed.ram_address,
                ram_size=parsed.ram_size,
                bss_size=parsed.bss_size,
                sinit_init=parsed.sinit_init,
                sinit_init_end=parsed.sinit_init_end,
                file_id=parsed.file_id,
                flags=parsed.flags,
            ))
        return entries

    def get_overlay_binary(self, overlay_id: int, processor: str = "arm9") -> bytes:
        """Extracts the overlay binary file by overlay ID."""
        overlays = self.list_overlays(processor)
        for ov in overlays:
            if ov.id == overlay_id:
                return self.get_file(ov.file_id)
        raise KeyError(f"Overlay ID {overlay_id} not found in {processor} overlay table.")

    def calculate_header_checksum(self) -> int:
        """Calculates CRC-16/IBM header checksum covering 0x000-0x15D."""
        return calculate_nds_checksum(bytes(self.data[:0x15E]))

    def verify_header_checksum(self) -> bool:
        """Verifies if CRC-16/IBM at 0x15E matches header data."""
        return verify_nds_checksum(bytes(self.data[:0x160]))

    def fix_header_checksum(self) -> int:
        """Calculates and writes the valid CRC-16 at offset 0x15E."""
        crc = self.calculate_header_checksum()
        if len(self.data) >= 0x160:
            self.data[0x15E:0x160] = NDSHeaderCrcStruct(checksum=crc).to_bytes()
        return crc

    def get_arm9_vaddr_offset(self, vaddr: int) -> int:
        """Translates an ARM9 virtual RAM address (e.g. 0x02088FC0) to ROM file offset."""
        if self.arm9_ram_addr == 0:
            raise ParseError("ARM9 RAM base address is not set in ROM header.")
        rel = vaddr - self.arm9_ram_addr
        if rel < 0 or rel + 4 > self.arm9_size:
            raise ValueError(
                f"Virtual RAM address 0x{vaddr:08X} is out of bounds for ARM9 binary "
                f"(base 0x{self.arm9_ram_addr:08X}, size 0x{self.arm9_size:08X})."
            )
        return self.arm9_offset + rel

    def get_arm7_vaddr_offset(self, vaddr: int) -> int:
        """Translates an ARM7 virtual RAM address to ROM file offset."""
        if self.arm7_ram_addr == 0:
            raise ParseError("ARM7 RAM base address is not set in ROM header.")
        rel = vaddr - self.arm7_ram_addr
        if rel < 0 or rel + 4 > self.arm7_size:
            raise ValueError(
                f"Virtual RAM address 0x{vaddr:08X} is out of bounds for ARM7 binary "
                f"(base 0x{self.arm7_ram_addr:08X}, size 0x{self.arm7_size:08X})."
            )
        return self.arm7_offset + rel

    def patch_arm9_vaddr(
        self,
        vaddr: int,
        patch_data: Union[bytes, int],
        expected: Optional[Union[bytes, int]] = None,
        auto_fix_checksum: bool = True,
    ) -> bool:
        """
        Patches ARM9 binary code in-place by virtual RAM address (e.g. 0x02088FC0).
        Automatically maps virtual RAM address to the file offset in the ROM,
        verifies expected original bytes/instruction (as bytes or uint32),
        applies patch, and optionally recalculates the valid NDS header CRC16.
        """
        file_offset = self.get_arm9_vaddr_offset(vaddr)
        return self._patch_at_offset(file_offset, patch_data, expected, auto_fix_checksum)

    def patch_arm7_vaddr(
        self,
        vaddr: int,
        patch_data: Union[bytes, int],
        expected: Optional[Union[bytes, int]] = None,
        auto_fix_checksum: bool = True,
    ) -> bool:
        """Patches ARM7 binary code in-place by virtual RAM address."""
        file_offset = self.get_arm7_vaddr_offset(vaddr)
        return self._patch_at_offset(file_offset, patch_data, expected, auto_fix_checksum)

    def _patch_at_offset(
        self,
        offset: int,
        patch_data: Union[bytes, int],
        expected: Optional[Union[bytes, int]] = None,
        auto_fix_checksum: bool = True,
    ) -> bool:
        patch_bytes = patch_data.to_bytes(4, "little") if isinstance(patch_data, int) else patch_data
        n = len(patch_bytes)

        if offset + n > len(self.data):
            raise ValueError(f"Patch data of {n} bytes at offset 0x{offset:X} exceeds ROM length.")

        if expected is not None:
            exp_bytes = expected.to_bytes(4, "little") if isinstance(expected, int) else expected
            cur_bytes = bytes(self.data[offset : offset + len(exp_bytes)])
            if cur_bytes != exp_bytes:
                return False

        self.data[offset : offset + n] = patch_bytes
        if auto_fix_checksum:
            self.fix_header_checksum()
        return True

    def to_bytes(self) -> bytes:
        return bytes(self.data)

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            f.write(self.data)

    def __repr__(self) -> str:
        return f"<NDSRom '{self.title}' code={self.game_code} maker={self.maker_code}>"


def calculate_nds_crc16(data: bytes) -> int:
    """CRC-16/IBM (poly 0xA001, init 0xFFFF) used by Nintendo DS headers and banners."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def calculate_nds_checksum(header_bytes: bytes) -> int:
    """CRC-16/IBM checksum used by NDS header at 0x15E, covering bytes 0x000..0x15D."""
    return calculate_nds_crc16(header_bytes[:0x15E])


def verify_nds_checksum(rom_data: bytes) -> bool:
    if len(rom_data) < 0x160:
        return False
    expected = NDSHeaderCrcStruct.from_bytes(rom_data, offset=0x15E).checksum
    calc = calculate_nds_checksum(rom_data[:0x15E])
    return expected == calc


def fix_nds_checksum(rom_data: Union[bytes, bytearray]) -> bytearray:
    buf = bytearray(rom_data)
    if len(buf) < 0x160:
        raise ParseError("NDS ROM data too short for header checksum.")
    crc = calculate_nds_checksum(buf[:0x15E])
    buf[0x15E:0x160] = NDSHeaderCrcStruct(checksum=crc).to_bytes()
    return buf


def extract_rom(rom_path: str, extract_dir: str, work_dir: str = "") -> None:
    """
    Extracts a Nintendo DS ROM into an unpacked workspace directory.
    Extracts data/ hierarchy, ARM7/ARM9 binaries, banner, and overlays.
    """
    try:
        import ndspy.rom
    except ImportError:
        rom = NDSRom.from_file(rom_path)
        os.makedirs(extract_dir, exist_ok=True)
        data_dir = os.path.join(extract_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        fnt = rom.resolve_fnt()
        for rel_path, file_id in fnt.items():
            dest = sanitize_extract_path(data_dir, rel_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(rom.get_file(file_id))
        with open(os.path.join(extract_dir, "header.bin"), "wb") as f:
            f.write(rom.data[:0x200])
        arm9 = rom.get_arm9_binary()
        if arm9:
            with open(os.path.join(extract_dir, "arm9.bin"), "wb") as f:
                f.write(arm9)
        arm7 = rom.get_arm7_binary()
        if arm7:
            with open(os.path.join(extract_dir, "arm7.bin"), "wb") as f:
                f.write(arm7)
        if rom.banner_offset > 0 and rom.banner_offset + 0x840 <= len(rom.data):
            with open(os.path.join(extract_dir, "banner.bin"), "wb") as f:
                f.write(rom.data[rom.banner_offset : rom.banner_offset + 0x840])
        if work_dir:
            import shutil
            shutil.copytree(extract_dir, work_dir, dirs_exist_ok=True)
        return

    os.makedirs(extract_dir, exist_ok=True)
    datafolder = os.path.join(extract_dir, "data")
    os.makedirs(datafolder, exist_ok=True)

    rom = ndspy.rom.NintendoDSRom.fromFile(rom_path)
    for i, file_bytes in enumerate(rom.files):
        filepath = rom.filenames.filenameOf(i)
        if filepath is not None:
            full_p = sanitize_extract_path(datafolder, filepath)
            os.makedirs(os.path.dirname(full_p), exist_ok=True)
            with open(full_p, "wb") as f:
                f.write(file_bytes)

    if rom.iconBanner:
        with open(os.path.join(extract_dir, "banner.bin"), "wb") as f:
            f.write(rom.iconBanner)

    with open(rom_path, "rb") as fin:
        hdr = fin.read(0x200)
    with open(os.path.join(extract_dir, "header.bin"), "wb") as f:
        f.write(hdr)

    if rom.arm7:
        with open(os.path.join(extract_dir, "arm7.bin"), "wb") as f:
            f.write(rom.arm7)
    if rom.arm9:
        with open(os.path.join(extract_dir, "arm9.bin"), "wb") as f:
            f.write(rom.arm9)
    if rom.arm7OverlayTable:
        with open(os.path.join(extract_dir, "y7.bin"), "wb") as f:
            f.write(rom.arm7OverlayTable)
    if rom.arm9OverlayTable:
        with open(os.path.join(extract_dir, "y9.bin"), "wb") as f:
            f.write(rom.arm9OverlayTable)
        ov_dir = os.path.join(extract_dir, "overlay")
        os.makedirs(ov_dir, exist_ok=True)
        for i in range(len(rom.arm9OverlayTable) // 0x20):
            file_id = NDSOverlayEntryStruct.from_bytes(
                rom.arm9OverlayTable,
                offset=i * NDSOverlayEntryStruct.sizeof(),
            ).id
            ov_path = os.path.join(ov_dir, f"overlay_{i:04d}.bin")
            with open(ov_path, "wb") as f:
                f.write(rom.files[file_id])

    if work_dir:
        import shutil
        shutil.copytree(extract_dir, work_dir, dirs_exist_ok=True)


def repack_rom(rom_in: str, rom_out: str, work_dir: str, patch_file: str = "") -> None:
    """
    Repacks a Nintendo DS ROM, replacing files found in the work directory.
    Updates files in root/ or data/, ARM7/ARM9 binaries, banner, and overlay tables.
    """
    datafolder = os.path.join(work_dir, "root")
    if not os.path.isdir(datafolder):
        datafolder = os.path.join(work_dir, "data")
    if not os.path.isdir(datafolder):
        datafolder = work_dir

    def _find_sys_file(name: str) -> Optional[str]:
        p1 = os.path.join(work_dir, "sys", name)
        if os.path.isfile(p1):
            return p1
        p2 = os.path.join(work_dir, name)
        if os.path.isfile(p2):
            return p2
        return None

    try:
        import ndspy.rom
    except ImportError:
        rom = NDSRom.from_file(rom_in)
        if os.path.isdir(datafolder):
            for root, _, files in os.walk(datafolder):
                for fname in files:
                    abs_p = os.path.join(root, fname)
                    rel_p = os.path.relpath(abs_p, datafolder).replace("\\", "/")
                    with open(abs_p, "rb") as f:
                        content = f.read()
                    try:
                        rom.replace_file(rel_p, content)
                    except FileNotFoundError:
                        pass
        rom.save(rom_out)
        _post_fix_checksum(rom_out)
        return

    rom = ndspy.rom.NintendoDSRom.fromFile(rom_in)
    if os.path.isdir(datafolder):
        for i, _ in enumerate(rom.files):
            filepath = rom.filenames.filenameOf(i)
            if filepath is not None:
                disk_path = os.path.join(datafolder, filepath)
                if os.path.isfile(disk_path):
                    with open(disk_path, "rb") as f:
                        rom.files[i] = f.read()

    # System binaries
    banner_p = _find_sys_file("banner.bin")
    if banner_p:
        with open(banner_p, "rb") as f:
            rom.iconBanner = f.read()

    arm7_p = _find_sys_file("arm7.bin")
    if arm7_p:
        with open(arm7_p, "rb") as f:
            rom.arm7 = f.read()

    arm9_p = _find_sys_file("arm9.bin")
    if arm9_p:
        with open(arm9_p, "rb") as f:
            rom.arm9 = f.read()

    y7_p = _find_sys_file("y7.bin")
    if y7_p:
        with open(y7_p, "rb") as f:
            rom.arm7OverlayTable = f.read()

    y9_p = _find_sys_file("y9.bin")
    if y9_p:
        with open(y9_p, "rb") as f:
            rom.arm9OverlayTable = f.read()
        num_overlays = len(rom.arm9OverlayTable) // 0x20
        overlay_dir = os.path.join(work_dir, "sys", "overlay") if os.path.isdir(os.path.join(work_dir, "sys", "overlay")) else os.path.join(work_dir, "overlay")
        for i in range(num_overlays):
            file_id = NDSOverlayEntryStruct.from_bytes(
                rom.arm9OverlayTable,
                offset=i * NDSOverlayEntryStruct.sizeof(),
            ).id
            ov_name = os.path.join(overlay_dir, f"overlay_{i:04d}.bin")
            if os.path.isfile(ov_name):
                with open(ov_name, "rb") as f_ov:
                    rom.files[file_id] = f_ov.read()

    os.makedirs(os.path.dirname(os.path.abspath(rom_out)), exist_ok=True)
    rom.saveToFile(rom_out)
    _post_fix_checksum(rom_out)
    if patch_file:
        from miorom.patch.xdelta import XdeltaPatcher
        XdeltaPatcher.create_patch(rom_in, rom_out, patch_file)


def _post_fix_checksum(rom_out: str) -> None:
    with open(rom_out, "rb") as f_chk:
        rom_chk_bytes = f_chk.read()
    if not verify_nds_checksum(rom_chk_bytes):
        fixed = fix_nds_checksum(rom_chk_bytes)
        with open(rom_out, "wb") as f_fix:
            f_fix.write(fixed)


# Descriptive aliases
extract_nds_rom = extract_rom
repack_nds_rom = repack_rom
