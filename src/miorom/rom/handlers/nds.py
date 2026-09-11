import os
from typing import Dict, Any, Optional, List, Tuple

from miorom.rom.base import BaseRomHandler
from miorom.core.schema import U16, U32
from miorom.platforms.nds.rom import NDSFatEntryStruct, NDSFntDirectoryEntryStruct, NDSHeaderCrcStruct, NDSRom
from miorom.security import sanitize_extract_path


def calculate_nds_crc16(data: bytes, init: int = 0xFFFF) -> int:
    """Calculates NDS BIOS SWI 0x0E CRC-16 checksum (LSB-first, poly 0x8408)."""
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
    return crc & 0xFFFF


def parse_nds_fnt(fnt_data: bytes) -> Dict[int, str]:
    """
    Parses an NDS File Name Table (FNT) binary into a mapping of FAT ID -> relative file path.
    """
    if len(fnt_data) < 8:
        return {}

    root = NDSFntDirectoryEntryStruct.from_bytes(fnt_data, offset=0)
    root_start = root.first_entry_offset
    root_top_id = root.first_file_id
    num_dirs = root.parent_directory_id
    # Clamp num_dirs to prevent corrupted loop
    num_dirs = min(num_dirs & 0x0FFF, len(fnt_data) // 8)
    if num_dirs == 0:
        return {}

    dirs = []
    for i in range(num_dirs):
        off = i * 8
        if off + 8 > len(fnt_data):
            break
        entry = NDSFntDirectoryEntryStruct.from_bytes(fnt_data, offset=off)
        entry_start, top_file_id, parent_id = (
            entry.first_entry_offset,
            entry.first_file_id,
            entry.parent_directory_id,
        )
        dirs.append((entry_start, top_file_id, parent_id))

    file_map: Dict[int, str] = {}
    dir_paths: Dict[int, str] = {0xF000: ""}

    for i in range(len(dirs)):
        dir_id = 0xF000 + i
        cur_path = dir_paths.get(dir_id, "")
        entry_start, top_file_id, parent_id = dirs[i]

        pos = entry_start
        cur_file_id = top_file_id

        while pos < len(fnt_data):
            b = fnt_data[pos]
            pos += 1
            if b == 0:  # End of directory
                break

            is_subdir = bool(b & 0x80)
            name_len = b & 0x7F
            if pos + name_len > len(fnt_data):
                break

            name = fnt_data[pos : pos + name_len].decode("latin1", errors="replace")
            pos += name_len

            if is_subdir:
                if pos + 2 > len(fnt_data):
                    break
                subdir_id = U16().unpack(fnt_data, pos, "<")[0]
                pos += 2
                dir_paths[subdir_id] = f"{cur_path}/{name}".strip("/")
            else:
                file_rel = f"{cur_path}/{name}".strip("/")
                file_map[cur_file_id] = file_rel
                cur_file_id += 1

    return file_map


def build_nds_fnt(file_paths: List[str]) -> Tuple[bytes, List[Tuple[str, str]]]:
    """
    Constructs an NDS File Name Table (FNT) binary from a list of relative file paths.
    Returns (fnt_bytes, ordered_file_list), where ordered_file_list contains (filename, rel_path).
    """
    dirs = [""]
    dir_to_id = {"": 0xF000}

    # Collect unique subdirectories
    all_dirs = set()
    for p in file_paths:
        parts = p.replace("\\", "/").strip("/").split("/")
        for i in range(1, len(parts)):
            all_dirs.add("/".join(parts[:i]))

    for d in sorted(all_dirs):
        dir_to_id[d] = 0xF000 + len(dirs)
        dirs.append(d)

    num_dirs = len(dirs)

    dir_files: Dict[str, List[Tuple[str, str]]] = {d: [] for d in dirs}
    dir_subdirs: Dict[str, List[Tuple[str, str]]] = {d: [] for d in dirs}

    for p in sorted(file_paths):
        clean_p = p.replace("\\", "/").strip("/")
        parts = clean_p.split("/")
        parent = "/".join(parts[:-1])
        fname = parts[-1]
        if parent in dir_files:
            dir_files[parent].append((fname, clean_p))

    for d in dirs[1:]:
        parts = d.split("/")
        parent = "/".join(parts[:-1])
        dname = parts[-1]
        if parent in dir_subdirs:
            dir_subdirs[parent].append((dname, d))

    ordered_files: List[Tuple[str, str]] = []
    dir_top_file_id: Dict[str, int] = {}
    for d in dirs:
        dir_top_file_id[d] = len(ordered_files)
        for fname, p in dir_files[d]:
            ordered_files.append((fname, p))

    table_headers: List[Tuple[int, int, int]] = []
    subtables = bytearray()

    for i, d in enumerate(dirs):
        entry_start = num_dirs * 8 + len(subtables)
        top_id = dir_top_file_id[d]
        if i == 0:
            parent_id = num_dirs
        else:
            parts = d.split("/")
            parent_dir = "/".join(parts[:-1])
            parent_id = dir_to_id[parent_dir]
        table_headers.append((entry_start, top_id, parent_id))

        # Subdirectories entries
        for sd_name, sd_path in dir_subdirs[d]:
            sd_id = dir_to_id[sd_path]
            b = 0x80 | (len(sd_name) & 0x7F)
            subtables.append(b)
            subtables.extend(sd_name.encode("latin1", errors="replace"))
            subtables.extend(U16(sd_id).pack(sd_id, endian="<"))

        # File entries
        for fname, _ in dir_files[d]:
            b = len(fname) & 0x7F
            subtables.append(b)
            subtables.extend(fname.encode("latin1", errors="replace"))

        # End marker
        subtables.append(0x00)

    fnt = bytearray()
    for entry_start, top_id, parent_id in table_headers:
        fnt.extend(NDSFntDirectoryEntryStruct(
            first_entry_offset=entry_start,
            first_file_id=top_id,
            parent_directory_id=parent_id,
        ).to_bytes())
    fnt.extend(subtables)

    return bytes(fnt), ordered_files


class NDSRomHandler(BaseRomHandler):
    """
    Nintendo DS ROM (.nds) unpacker and repacker.
    Extracts system binaries (ARM9, ARM7, Header, Banner) and entire FNT/FAT directory hierarchy.
    Repacks files, rebuilds FNT and FAT, recalibrates header CRC16 and size offsets.
    """

    name = "nds"
    description = "Nintendo DS ROM"
    extensions = [".nds", ".srl"]

    def can_handle(self, data: bytes, filepath: Optional[str] = None) -> bool:
        if filepath:
            ext = os.path.splitext(filepath)[1].lower()
            if ext in self.extensions:
                return True

        if len(data) < 0x200:
            return False

        # Check NDS header characteristics
        unit_code = data[0x12]
        if unit_code not in (0x00, 0x01, 0x02, 0x03):
            return False

        arm9_off = U32().unpack(data, 0x20, "<")[0]
        arm7_off = U32().unpack(data, 0x30, "<")[0]

        # Valid NDS ROMs have ARM9/ARM7 offsets >= 0x200
        return (0x200 <= arm9_off < len(data)) and (0x200 <= arm7_off < len(data))

    def unpack(self, data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]:
        rom = NDSRom(data)
        sys_dir = os.path.join(output_dir, "sys")
        root_dir = os.path.join(output_dir, "root")
        os.makedirs(sys_dir, exist_ok=True)
        os.makedirs(root_dir, exist_ok=True)

        # Extract system files
        hdr_len = min(rom.arm9_offset, 0x4000) if rom.arm9_offset >= 0x200 else 0x200
        with open(os.path.join(sys_dir, "header.bin"), "wb") as f:
            f.write(data[:hdr_len])

        arm9 = rom.get_arm9_binary()
        if arm9:
            with open(os.path.join(sys_dir, "arm9.bin"), "wb") as f:
                f.write(arm9)

        arm7 = rom.get_arm7_binary()
        if arm7:
            with open(os.path.join(sys_dir, "arm7.bin"), "wb") as f:
                f.write(arm7)

        if rom.banner_offset > 0 and rom.banner_offset + 0x840 <= len(data):
            with open(os.path.join(sys_dir, "banner.bin"), "wb") as f:
                f.write(data[rom.banner_offset : rom.banner_offset + 0x840])

        # Extract filesystem entries
        file_map: Dict[int, str] = {}
        if rom.fnt_offset > 0 and rom.fnt_size >= 8 and rom.fnt_offset + rom.fnt_size <= len(data):
            fnt_data = data[rom.fnt_offset : rom.fnt_offset + rom.fnt_size]
            file_map = parse_nds_fnt(fnt_data)

        fat_entries = rom.list_files()
        extracted_count = 0
        for entry in fat_entries:
            rel_path = file_map.get(entry.id, f"file_{entry.id:04d}.bin")
            dest_path = sanitize_extract_path(root_dir, rel_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as f_out:
                f_out.write(rom.get_file(entry.id))
            extracted_count += 1

        banner_title = rom.get_banner_title()

        return {
            "format": self.name,
            "platform": "Nintendo DS",
            "title": rom.title,
            "banner_title": banner_title,
            "game_code": rom.game_code,
            "maker_code": rom.maker_code,
            "unit_code": rom.unit_code,
            "arm9_entry": f"0x{rom.arm9_entry:08X}",
            "arm9_ram_addr": f"0x{rom.arm9_ram_addr:08X}",
            "arm7_entry": f"0x{rom.arm7_entry:08X}",
            "arm7_ram_addr": f"0x{rom.arm7_ram_addr:08X}",
            "file_count": extracted_count,
            "header_length": hdr_len,
        }

    def repack(self, input_dir: str, **kwargs) -> bytes:
        sys_dir = os.path.join(input_dir, "sys")
        root_dir = os.path.join(input_dir, "root")
        if not os.path.isdir(root_dir):
            root_dir = os.path.join(input_dir, "data")
        if not os.path.isdir(root_dir):
            root_dir = input_dir

        # Load header
        header_path = os.path.join(sys_dir, "header.bin")
        if os.path.isfile(header_path):
            with open(header_path, "rb") as f:
                header_raw = bytearray(f.read())
        else:
            header_raw = bytearray(0x4000)

        if len(header_raw) < 0x4000:
            header_raw.extend(b"\x00" * (0x4000 - len(header_raw)))

        # Load ARM9 and ARM7 binaries
        arm9_path = os.path.join(sys_dir, "arm9.bin")
        arm9_data = b""
        if os.path.isfile(arm9_path):
            with open(arm9_path, "rb") as f:
                arm9_data = f.read()

        arm7_path = os.path.join(sys_dir, "arm7.bin")
        arm7_data = b""
        if os.path.isfile(arm7_path):
            with open(arm7_path, "rb") as f:
                arm7_data = f.read()

        banner_path = os.path.join(sys_dir, "banner.bin")
        banner_data = b""
        if os.path.isfile(banner_path):
            with open(banner_path, "rb") as f:
                banner_data = f.read()

        # Collect files in root_dir
        file_paths = []
        for root, _, files in os.walk(root_dir):
            for fname in files:
                rel = os.path.relpath(os.path.join(root, fname), root_dir).replace("\\", "/")
                file_paths.append(rel)

        file_payloads: Dict[str, bytes] = {}
        for rel in file_paths:
            with open(os.path.join(root_dir, rel), "rb") as f:
                file_payloads[rel] = f.read()

        # Build FNT
        if file_paths:
            fnt_bytes, ordered_files = build_nds_fnt(file_paths)
        else:
            fnt_bytes = NDSFntDirectoryEntryStruct(
                first_entry_offset=8,
                first_file_id=0,
                parent_directory_id=1,
            ).to_bytes() + b"\x00"
            ordered_files = []

        # ROM Assembly layout
        def align(val: int, boundary: int = 512) -> int:
            rem = val % boundary
            return val + (boundary - rem) if rem != 0 else val

        rom_out = bytearray(header_raw[:0x4000])

        # ARM9 binary
        arm9_off = 0x4000
        arm9_size = len(arm9_data)
        rom_out[arm9_off : arm9_off + arm9_size] = arm9_data

        # ARM7 binary
        cur_offset = align(arm9_off + arm9_size, 512)
        arm7_off = cur_offset
        arm7_size = len(arm7_data)
        rom_out.extend(b"\x00" * (arm7_off - len(rom_out)))
        rom_out.extend(arm7_data)

        # File Name Table (FNT)
        cur_offset = align(len(rom_out), 512)
        fnt_off = cur_offset
        fnt_size = len(fnt_bytes)
        rom_out.extend(b"\x00" * (fnt_off - len(rom_out)))
        rom_out.extend(fnt_bytes)

        # File Allocation Table (FAT)
        cur_offset = align(len(rom_out), 512)
        fat_off = cur_offset
        num_files = len(ordered_files)
        fat_size = num_files * 8
        fat_end = fat_off + fat_size
        rom_out.extend(b"\x00" * (fat_end - len(rom_out)))

        # Icon banner
        banner_off = 0
        if banner_data:
            cur_offset = align(len(rom_out), 512)
            banner_off = cur_offset
            rom_out.extend(b"\x00" * (banner_off - len(rom_out)))
            rom_out.extend(banner_data)

        # File payloads
        fat_entries = []
        for _, rel_path in ordered_files:
            data = file_payloads.get(rel_path, b"")
            cur_offset = align(len(rom_out), 512)
            f_start = cur_offset
            f_end = f_start + len(data)
            rom_out.extend(b"\x00" * (f_start - len(rom_out)))
            rom_out.extend(data)
            fat_entries.append((f_start, f_end))

        # Write FAT table
        fat_bin = bytearray()
        for f_start, f_end in fat_entries:
            fat_bin.extend(NDSFatEntryStruct(start_offset=f_start, end_offset=f_end).to_bytes())
        rom_out[fat_off : fat_off + len(fat_bin)] = fat_bin

        # Total ROM size
        total_size = align(len(rom_out), 512)
        if len(rom_out) < total_size:
            rom_out.extend(b"\x00" * (total_size - len(rom_out)))

        # Update Header fields
        header_fields = {
            0x20: arm9_off,
            0x2C: arm9_size,
            0x30: arm7_off,
            0x3C: arm7_size,
            0x40: fnt_off,
            0x44: fnt_size,
            0x48: fat_off,
            0x4C: fat_size,
            0x68: banner_off,
            0x80: total_size,
        }
        for offset, value in header_fields.items():
            rom_out[offset:offset + 4] = U32().pack(value, endian="<")

        # Recalculate Header CRC16 at 0x15E
        crc16 = calculate_nds_crc16(bytes(rom_out[:0x15E]))
        rom_out[0x15E:0x160] = NDSHeaderCrcStruct(checksum=crc16).to_bytes()

        return bytes(rom_out)
