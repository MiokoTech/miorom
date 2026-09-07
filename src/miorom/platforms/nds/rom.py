import os
import struct
from dataclasses import dataclass
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
class NDSFileEntry:
    id: int
    start_offset: int
    end_offset: int
    size: int


@dataclass
class NDSOverlayEntry:
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
class NDSHeader:
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


class NDSRom:
    """
    Nintendo DS ROM (.nds) header and filesystem inspector.
    Extracts internal binaries (ARM9, ARM7), FAT tables, and multilingual banner titles.
    """

    def __init__(self, data: bytes):
        self.data = bytearray(data) if isinstance(data, (bytearray, bytes)) else bytearray(data)
        if len(data) < 0x200:
            raise ValueError("Data too small to be an NDS ROM.")

        self._fnt_cache: Optional[Dict[str, int]] = None
        self._parse_header()

    @classmethod
    def from_file(cls, filepath: str) -> "NDSRom":
        with open(filepath, "rb") as f:
            return cls(f.read())

    def _parse_header(self):
        d = self.data
        title = d[0:12].rstrip(b"\x00").decode("ascii", errors="replace")
        game_code = d[12:16].decode("ascii", errors="replace")
        maker_code = d[16:18].decode("ascii", errors="replace")
        unit_code = d[18]

        arm9_offset = struct.unpack_from("<I", d, 0x20)[0]
        arm9_entry = struct.unpack_from("<I", d, 0x24)[0]
        arm9_ram_addr = struct.unpack_from("<I", d, 0x28)[0]
        arm9_size = struct.unpack_from("<I", d, 0x2C)[0]

        arm7_offset = struct.unpack_from("<I", d, 0x30)[0]
        arm7_entry = struct.unpack_from("<I", d, 0x34)[0]
        arm7_ram_addr = struct.unpack_from("<I", d, 0x38)[0]
        arm7_size = struct.unpack_from("<I", d, 0x3C)[0]

        fnt_offset = struct.unpack_from("<I", d, 0x40)[0]
        fnt_size = struct.unpack_from("<I", d, 0x44)[0]
        fat_offset = struct.unpack_from("<I", d, 0x48)[0]
        fat_size = struct.unpack_from("<I", d, 0x4C)[0]
        banner_offset = struct.unpack_from("<I", d, 0x68)[0]

        arm9_overlay_offset = struct.unpack_from("<I", d, 0x50)[0]
        arm9_overlay_size = struct.unpack_from("<I", d, 0x54)[0]
        arm7_overlay_offset = struct.unpack_from("<I", d, 0x58)[0]
        arm7_overlay_size = struct.unpack_from("<I", d, 0x5C)[0]
        header_crc = struct.unpack_from("<H", d, 0x15E)[0] if len(d) >= 0x160 else 0

        self.header = NDSHeader(
            game_title=title,
            game_code=game_code,
            maker_code=maker_code,
            unit_code=unit_code,
            arm9_offset=arm9_offset,
            arm9_entry_address=arm9_entry,
            arm9_ram_address=arm9_ram_addr,
            arm9_size=arm9_size,
            arm7_offset=arm7_offset,
            arm7_entry_address=arm7_entry,
            arm7_ram_address=arm7_ram_addr,
            arm7_size=arm7_size,
            fnt_offset=fnt_offset,
            fnt_size=fnt_size,
            fat_offset=fat_offset,
            fat_size=fat_size,
            banner_offset=banner_offset,
            arm9_overlay_offset=arm9_overlay_offset,
            arm9_overlay_size=arm9_overlay_size,
            arm7_overlay_offset=arm7_overlay_offset,
            arm7_overlay_size=arm7_overlay_size,
            header_crc=header_crc,
        )

        # Backwards-compatible aliases
        self.title = title
        self.game_code = game_code
        self.maker_code = maker_code
        self.unit_code = unit_code
        self.arm9_offset = arm9_offset
        self.arm9_entry = arm9_entry
        self.arm9_ram_addr = arm9_ram_addr
        self.arm9_size = arm9_size
        self.arm7_offset = arm7_offset
        self.arm7_entry = arm7_entry
        self.arm7_ram_addr = arm7_ram_addr
        self.arm7_size = arm7_size
        self.fnt_offset = fnt_offset
        self.fnt_size = fnt_size
        self.fat_offset = fat_offset
        self.fat_size = fat_size
        self.banner_offset = banner_offset
        self.arm9_overlay_offset = arm9_overlay_offset
        self.arm9_overlay_size = arm9_overlay_size
        self.arm7_overlay_offset = arm7_overlay_offset
        self.arm7_overlay_size = arm7_overlay_size

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
            start, end = struct.unpack_from("<II", self.data, off)
            entries.append(NDSFileEntry(
                id=i,
                start_offset=start,
                end_offset=end,
                size=max(0, end - start)
            ))
        return entries

    def get_file(self, file_id: int) -> bytes:
        """Extracts a file by its FAT ID."""
        off = self.fat_offset + (file_id * 8)
        if off + 8 > len(self.data):
            raise IndexError(f"File ID {file_id} out of FAT range.")

        start, end = struct.unpack_from("<II", self.data, off)
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
            sub_off, cur_file_id, _ = struct.unpack_from("<IHH", d, dir_entry_off)
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
                    sub_dir_id = struct.unpack_from("<H", d, pos)[0]
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

        cur_start, cur_end = struct.unpack_from("<II", self.data, off)
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
        struct.pack_into("<II", self.data, off, cur_start, cur_start + len(new_data))

        # Shift all downstream FAT entries
        file_count = self.fat_size // 8
        for i in range(file_count):
            if i == target_id:
                continue
            entry_off = self.fat_offset + (i * 8)
            s, e = struct.unpack_from("<II", self.data, entry_off)
            if s >= cur_end:
                struct.pack_into("<II", self.data, entry_off, s + delta, e + delta)

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

        # Pad after new_data to preserve alignment for any subsequent append
        rem_after = len(self.data) % alignment
        pad_after = (alignment - rem_after) % alignment if alignment > 1 else 0
        if pad_after > 0:
            self.data.extend(b"\x00" * pad_after)

        # Update FAT entry
        struct.pack_into("<II", self.data, fat_entry_off, new_start, new_end)

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

        raise ValueError(
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
        raise ValueError(
            f"File offset 0x{file_off:08X} is outside ARM9 "
            f"[0x{self.arm9_offset:08X}..0x{self.arm9_offset + self.arm9_size:08X}) and ARM7."
        )

    def read_arm9(self, ram_addr: int, length: int) -> bytes:
        """Reads length bytes from ARM9 memory at ram_addr directly from ROM."""
        file_off = self.ram_to_file_offset(ram_addr, processor="arm9")
        if file_off + length > self.arm9_offset + self.arm9_size:
            raise ValueError("Read exceeds ARM9 binary bounds.")
        return bytes(self.data[file_off : file_off + length])

    def patch_arm9(self, ram_addr: int, patch_data: Union[bytes, bytearray, int]) -> int:
        """
        Patches ARM9 binary at runtime RAM address ram_addr and updates the header checksum.
        If patch_data is an integer, it is packed as a little-endian 32-bit uint.
        Returns the physical file offset that was modified.
        """
        if isinstance(patch_data, int):
            raw = struct.pack("<I", patch_data)
        else:
            raw = bytes(patch_data)

        file_off = self.ram_to_file_offset(ram_addr, processor="arm9")
        if file_off + len(raw) > self.arm9_offset + self.arm9_size:
            raise ValueError(f"Patch at 0x{ram_addr:08X} exceeds ARM9 binary bounds.")

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
            raise ValueError("Processor must be 'arm9' or 'arm7'")

        if table_off == 0 or table_size == 0 or table_off + table_size > len(self.data):
            return []

        entry_size = 32
        count = table_size // entry_size
        entries: List[NDSOverlayEntry] = []

        for i in range(count):
            off = table_off + (i * entry_size)
            (
                ov_id,
                ram_addr,
                ram_sz,
                bss_sz,
                sinit_init,
                sinit_end,
                file_id,
                flags,
            ) = struct.unpack_from("<IIIIIIII", self.data, off)
            entries.append(NDSOverlayEntry(
                id=ov_id,
                ram_address=ram_addr,
                ram_size=ram_sz,
                bss_size=bss_sz,
                sinit_init=sinit_init,
                sinit_init_end=sinit_end,
                file_id=file_id,
                flags=flags,
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
            struct.pack_into("<H", self.data, 0x15E, crc)
        return crc

    def to_bytes(self) -> bytes:
        return bytes(self.data)

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            f.write(self.data)

    def __repr__(self) -> str:
        return f"<NDSRom '{self.title}' code={self.game_code} maker={self.maker_code}>"


def calculate_nds_checksum(header_bytes: bytes) -> int:
    """CRC-16/IBM checksum used by NDS header at 0x15E, covering bytes 0x000..0x15D."""
    crc = 0xFFFF
    for b in header_bytes[:0x15E]:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def verify_nds_checksum(rom_data: bytes) -> bool:
    if len(rom_data) < 0x160:
        return False
    expected = struct.unpack_from("<H", rom_data, 0x15E)[0]
    calc = calculate_nds_checksum(rom_data[:0x15E])
    return expected == calc


def fix_nds_checksum(rom_data: Union[bytes, bytearray]) -> bytearray:
    buf = bytearray(rom_data)
    if len(buf) < 0x160:
        raise ValueError("NDS ROM data too short for header checksum.")
    crc = calculate_nds_checksum(buf[:0x15E])
    struct.pack_into("<H", buf, 0x15E, crc)
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
            dest = os.path.join(data_dir, rel_path)
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
            full_p = os.path.join(datafolder, filepath)
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
            file_id = struct.unpack_from("<I", rom.arm9OverlayTable, i * 0x20)[0]
            ov_path = os.path.join(ov_dir, f"overlay_{i:04d}.bin")
            with open(ov_path, "wb") as f:
                f.write(rom.files[file_id])

    if work_dir:
        import shutil
        shutil.copytree(extract_dir, work_dir, dirs_exist_ok=True)


def repack_rom(rom_in: str, rom_out: str, work_dir: str, patch_file: str = "") -> None:
    """
    Repacks a Nintendo DS ROM, replacing files found in the work directory.
    Updates files in data/, ARM7/ARM9 binaries, banner, and overlay tables.
    """
    try:
        import ndspy.rom
    except ImportError:
        rom = NDSRom.from_file(rom_in)
        datafolder = os.path.join(work_dir, "data")
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
        return

    rom = ndspy.rom.NintendoDSRom.fromFile(rom_in)
    datafolder = os.path.join(work_dir, "data")
    if os.path.isdir(datafolder):
        for i, _ in enumerate(rom.files):
            filepath = rom.filenames.filenameOf(i)
            if filepath is not None:
                disk_path = os.path.join(datafolder, filepath)
                if os.path.isfile(disk_path):
                    with open(disk_path, "rb") as f:
                        rom.files[i] = f.read()

    # System binaries
    banner_p = os.path.join(work_dir, "banner.bin")
    if os.path.isfile(banner_p):
        with open(banner_p, "rb") as f:
            rom.iconBanner = f.read()

    arm7_p = os.path.join(work_dir, "arm7.bin")
    if os.path.isfile(arm7_p):
        with open(arm7_p, "rb") as f:
            rom.arm7 = f.read()

    arm9_p = os.path.join(work_dir, "arm9.bin")
    if os.path.isfile(arm9_p):
        with open(arm9_p, "rb") as f:
            rom.arm9 = f.read()

    y7_p = os.path.join(work_dir, "y7.bin")
    if os.path.isfile(y7_p):
        with open(y7_p, "rb") as f:
            rom.arm7OverlayTable = f.read()

    y9_p = os.path.join(work_dir, "y9.bin")
    if os.path.isfile(y9_p):
        with open(y9_p, "rb") as f:
            rom.arm9OverlayTable = f.read()
        num_overlays = len(rom.arm9OverlayTable) // 0x20
        overlay_dir = os.path.join(work_dir, "overlay")
        for i in range(num_overlays):
            file_id = struct.unpack_from("<I", rom.arm9OverlayTable, i * 0x20)[0]
            ov_name = os.path.join(overlay_dir, f"overlay_{i:04d}.bin")
            if os.path.isfile(ov_name):
                with open(ov_name, "rb") as f_ov:
                    rom.files[file_id] = f_ov.read()

    os.makedirs(os.path.dirname(os.path.abspath(rom_out)), exist_ok=True)
    rom.saveToFile(rom_out)

    if patch_file:
        from miorom.patch.xdelta import XdeltaPatcher
        XdeltaPatcher.create_patch(rom_in, rom_out, patch_file)


# Descriptive aliases
extract_nds_rom = extract_rom
repack_nds_rom = repack_rom



