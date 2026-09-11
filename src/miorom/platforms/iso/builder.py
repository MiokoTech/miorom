"""
miorom.platforms.iso.builder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pure-Python ISO 9660 (ECMA-119) Disc Image Synthesizer and Rebuilder.

Constructs standards-compliant ISO 9660 disc images (CD/DVD) with Primary Volume
Descriptors (PVD), Type L & M Path Tables, hierarchical Directory Records,
and sector-aligned file extents.
"""

import os
import struct
import datetime
from typing import Dict, List, Optional, Tuple, Union

from miorom.errors import ParseError
from miorom.result import MioRomResult


SECTOR_SIZE = 2048


def pack_both_u16(val: int) -> bytes:
    """Packs 16-bit unsigned integer as both little-endian and big-endian (4 bytes)."""
    return struct.pack("<HH", val, val)


def pack_both_u32(val: int) -> bytes:
    """Packs 32-bit unsigned integer as both little-endian and big-endian (8 bytes)."""
    return struct.pack("<II", val, val)


def format_iso_datetime(dt: Optional[datetime.datetime] = None) -> bytes:
    """Formats 7-byte binary recording date and time for Directory Records."""
    if dt is None:
        dt = datetime.datetime.now(datetime.timezone.utc)
    year = max(0, min(255, dt.year - 1900))
    month = dt.month
    day = dt.day
    hour = dt.hour
    minute = dt.minute
    second = dt.second
    # Timezone offset in 15-minute intervals (-48 to +52)
    tz_offset = 0
    return struct.pack("BBBBBBb", year, month, day, hour, minute, second, tz_offset)


def format_pvd_datetime(dt: Optional[datetime.datetime] = None) -> bytes:
    """Formats 17-byte ASCII date and time string for Volume Descriptors (YYYYMMDDHHMMSScc + tz)."""
    if dt is None:
        dt = datetime.datetime.now(datetime.timezone.utc)
    s = dt.strftime("%Y%m%d%H%M%S00")
    return s.encode("ascii") + b"\x00"


def normalize_iso_name(name: str, is_dir: bool = False) -> str:
    """Normalizes string into uppercase ASCII ISO 9660 identifier."""
    clean = name.upper().strip()
    if is_dir:
        # Directory names do not have extensions or version suffixes
        return clean.replace("/", "").replace("\\", "")
    if ";" not in clean:
        clean += ";1"
    return clean


class _IsoNode:
    def __init__(self, name: str, is_directory: bool = False, parent: Optional["_IsoNode"] = None):
        self.name = name
        self.is_directory = is_directory
        self.parent = parent
        self.children: Dict[str, _IsoNode] = {}
        self.data: bytes = b""
        self.lba: int = 0
        self.size: int = 0
        self.dir_index: int = 0  # 1-based index in path tables

    @property
    def sector_count(self) -> int:
        if self.size == 0:
            return 0
        return (self.size + SECTOR_SIZE - 1) // SECTOR_SIZE


class Iso9660Builder(MioRomResult):
    """
    Pure-Python builder for creating ISO 9660 disc images from files and folders.
    """

    def __init__(self, volume_id: str = "MIOROM_DISC", system_id: str = ""):
        self.volume_id = volume_id[:32].upper()
        self.system_id = system_id[:32].upper()
        self.system_area: bytearray = bytearray(16 * SECTOR_SIZE)
        self.root = _IsoNode(name="", is_directory=True)

    def set_system_area(self, data: bytes):
        """Sets custom data in the first 16 sectors (32 KB system / boot area)."""
        if len(data) > 16 * SECTOR_SIZE:
            raise ValueError(f"System area data cannot exceed {16 * SECTOR_SIZE} bytes.")
        self.system_area[:len(data)] = data

    def add_directory(self, dir_path: str) -> _IsoNode:
        """Creates a directory hierarchy and returns the leaf directory node."""
        parts = [p for p in dir_path.replace("\\", "/").strip("/").split("/") if p]
        curr = self.root
        for p in parts:
            clean_name = normalize_iso_name(p, is_dir=True)
            if clean_name not in curr.children:
                node = _IsoNode(name=clean_name, is_directory=True, parent=curr)
                curr.children[clean_name] = node
            curr = curr.children[clean_name]
        return curr

    def add_file(self, file_path: str, data: bytes):
        """Adds a file with payload bytes to the ISO directory tree."""
        parts = [p for p in file_path.replace("\\", "/").strip("/").split("/") if p]
        if not parts:
            raise ValueError("File path cannot be empty.")

        dir_parts = parts[:-1]
        filename = normalize_iso_name(parts[-1], is_dir=False)

        parent_node = self.root
        if dir_parts:
            parent_node = self.add_directory("/".join(dir_parts))

        node = _IsoNode(name=filename, is_directory=False, parent=parent_node)
        node.data = bytes(data)
        node.size = len(node.data)
        parent_node.children[filename] = node

    def add_from_fs(self, source_dir: str):
        """Recursively adds files and subdirectories from a filesystem folder."""
        if not os.path.isdir(source_dir):
            raise FileNotFoundError(f"Source directory not found: {source_dir}")

        for root, dirs, files in os.walk(source_dir):
            rel_dir = os.path.relpath(root, source_dir)
            if rel_dir != ".":
                self.add_directory(rel_dir)

            for f in files:
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, source_dir)
                with open(full_path, "rb") as fp:
                    self.add_file(rel_path, fp.read())

    def _collect_directories(self) -> List[_IsoNode]:
        """Collects all directories in breadth-first order (parent before children)."""
        dirs: List[_IsoNode] = [self.root]
        idx = 0
        while idx < len(dirs):
            curr = dirs[idx]
            for child in sorted(curr.children.values(), key=lambda c: c.name):
                if child.is_directory:
                    dirs.append(child)
            idx += 1

        for i, d in enumerate(dirs, 1):
            d.dir_index = i
        return dirs

    def _collect_files(self) -> List[_IsoNode]:
        """Collects all regular files across all directories."""
        files: List[_IsoNode] = []
        queue = [self.root]
        while queue:
            curr = queue.pop(0)
            for child in sorted(curr.children.values(), key=lambda c: c.name):
                if child.is_directory:
                    queue.append(child)
                else:
                    files.append(child)
        return files

    def _build_directory_record(
        self,
        node: _IsoNode,
        is_self: bool = False,
        is_parent: bool = False,
    ) -> bytes:
        """Constructs a single ISO 9660 Directory Record entry."""
        if is_self:
            file_id = b"\x00"
            flags = 0x02
        elif is_parent:
            file_id = b"\x01"
            flags = 0x02
        else:
            file_id = node.name.encode("ascii")
            flags = 0x02 if node.is_directory else 0x00

        len_fi = len(file_id)
        # Directory record length (33-byte header + id + padding)
        total_len = 33 + len_fi
        padding = 1 if (total_len % 2 != 0) else 0
        record_len = total_len + padding

        rec = bytearray()
        rec.append(record_len)                      # Length of Directory Record
        rec.append(0)                               # Extended Attribute Record Length
        rec.extend(pack_both_u32(node.lba))         # Location of Extent (LBA)
        rec.extend(pack_both_u32(node.size))        # Data Length
        rec.extend(format_iso_datetime())           # Recording Date and Time (7 bytes)
        rec.append(flags)                           # File Flags
        rec.append(0)                               # File Unit Size
        rec.append(0)                               # Interleave Gap Size
        rec.extend(pack_both_u16(1))                # Volume Sequence Number
        rec.append(len_fi)                          # Length of File Identifier
        rec.extend(file_id)
        if padding:
            rec.append(0)

        return bytes(rec)

    def _build_directory_sectors(self, dir_node: _IsoNode) -> bytes:
        """Serializes a directory into sector bytes, handling sector boundaries."""
        records: List[bytes] = []

        # Current directory record (.)
        records.append(self._build_directory_record(dir_node, is_self=True))
        # Parent directory record (..)
        parent = dir_node.parent if dir_node.parent else dir_node
        records.append(self._build_directory_record(parent, is_parent=True))

        # Children records
        for child in sorted(dir_node.children.values(), key=lambda c: c.name):
            records.append(self._build_directory_record(child))

        sectors = bytearray()
        curr_sector = bytearray()

        for r in records:
            if len(curr_sector) + len(r) > SECTOR_SIZE:
                # Pad remaining sector with zeros and start fresh sector
                curr_sector.extend(b"\x00" * (SECTOR_SIZE - len(curr_sector)))
                sectors.extend(curr_sector)
                curr_sector = bytearray()
            curr_sector.extend(r)

        if curr_sector:
            curr_sector.extend(b"\x00" * (SECTOR_SIZE - len(curr_sector)))
            sectors.extend(curr_sector)

        return bytes(sectors)

    def _build_path_table(self, dirs: List[_IsoNode], is_type_m: bool = False) -> bytes:
        """Builds Type L (little-endian) or Type M (big-endian) Path Table."""
        out = bytearray()
        for d in dirs:
            if d.dir_index == 1:
                dir_id = b"\x00"
            else:
                dir_id = d.name.encode("ascii")

            len_di = len(dir_id)
            parent_no = d.parent.dir_index if d.parent else 1

            rec = bytearray()
            rec.append(len_di)
            rec.append(0)  # Extended attribute length
            if is_type_m:
                rec.extend(struct.pack(">I", d.lba))
                rec.extend(struct.pack(">H", parent_no))
            else:
                rec.extend(struct.pack("<I", d.lba))
                rec.extend(struct.pack("<H", parent_no))
            rec.extend(dir_id)
            if len_di % 2 != 0:
                rec.append(0)  # Pad byte
            out.extend(rec)

        # Pad path table to sector multiple
        rem = len(out) % SECTOR_SIZE
        if rem != 0:
            out.extend(b"\x00" * (SECTOR_SIZE - rem))
        return bytes(out)

    def build(self) -> bytes:
        """
        Compiles the directory hierarchy and files into a complete ISO 9660 image.
        """
        dirs = self._collect_directories()
        files = self._collect_files()

        # Layout Allocation
        # Sector 0..15: System area (16 sectors)
        # Sector 16: Primary Volume Descriptor (1 sector)
        # Sector 17: Volume Descriptor Set Terminator (1 sector)
        # Sector 18..X: Type L Path Table
        # Sector X+1..Y: Type M Path Table
        # Sector Y+1..: Directory Sectors
        # Sector ..: File Extents

        path_table_raw_len = 0
        for d in dirs:
            name_len = 1 if d.dir_index == 1 else len(d.name)
            path_table_raw_len += 8 + name_len + (1 if name_len % 2 != 0 else 0)
        path_table_sectors = max(1, (path_table_raw_len + SECTOR_SIZE - 1) // SECTOR_SIZE)

        l_path_lba = 18
        m_path_lba = l_path_lba + path_table_sectors

        curr_lba = m_path_lba + path_table_sectors

        # Pre-assign directory LBAs and estimate sizes
        # Directory sizes depend on LBAs of children, so we iterate
        for d in dirs:
            d.lba = curr_lba
            # Minimum 1 sector for each directory
            d.size = SECTOR_SIZE
            curr_lba += 1

        # Calculate exact directory sizes and adjust LBAs
        curr_lba = m_path_lba + path_table_sectors
        dir_bytes_map: Dict[_IsoNode, bytes] = {}
        for d in dirs:
            d.lba = curr_lba
            d_bytes = self._build_directory_sectors(d)
            d.size = len(d_bytes)
            dir_bytes_map[d] = d_bytes
            curr_lba += d.sector_count

        # Assign LBAs to files
        for f in files:
            f.lba = curr_lba
            curr_lba += max(1, f.sector_count) if f.size > 0 else 0

        total_sectors = curr_lba

        # Re-build directory sectors with final LBAs
        for d in dirs:
            d_bytes = self._build_directory_sectors(d)
            dir_bytes_map[d] = d_bytes

        # Generate Path Tables
        l_table = self._build_path_table(dirs, is_type_m=False)
        m_table = self._build_path_table(dirs, is_type_m=True)
        path_table_size = path_table_raw_len

        # Construct Primary Volume Descriptor (PVD) at Sector 16
        pvd = bytearray(SECTOR_SIZE)
        pvd[0] = 0x01                          # Volume Descriptor Type (1 = PVD)
        pvd[1:6] = b"CD001"                    # Standard Identifier
        pvd[6] = 0x01                          # Volume Descriptor Version
        # System Identifier (32 bytes space-padded)
        sys_id_bytes = self.system_id.ljust(32)[:32].encode("ascii")
        pvd[8:40] = sys_id_bytes
        # Volume Identifier (32 bytes space-padded)
        vol_id_bytes = self.volume_id.ljust(32)[:32].encode("ascii")
        pvd[40:72] = vol_id_bytes
        # Volume Space Size (dual-endian u32)
        pvd[80:88] = pack_both_u32(total_sectors)
        # Volume Set Size = 1 (dual-endian u16)
        pvd[120:124] = pack_both_u16(1)
        # Volume Sequence Number = 1 (dual-endian u16)
        pvd[124:128] = pack_both_u16(1)
        # Logical Block Size = 2048 (dual-endian u16)
        pvd[128:132] = pack_both_u16(SECTOR_SIZE)
        # Path Table Size (dual-endian u32)
        pvd[132:140] = pack_both_u32(path_table_size)
        # Location of Type-L Path Table (little-endian u32)
        struct.pack_into("<I", pvd, 140, l_path_lba)
        # Location of Optional Type-L Path Table
        struct.pack_into("<I", pvd, 144, 0)
        # Location of Type-M Path Table (big-endian u32)
        struct.pack_into(">I", pvd, 148, m_path_lba)
        # Location of Optional Type-M Path Table
        struct.pack_into(">I", pvd, 152, 0)

        # Root Directory Record (34 bytes)
        root_rec = self._build_directory_record(self.root, is_self=True)
        pvd[156 : 156 + len(root_rec)] = root_rec

        # Volume Set Identifier (128 bytes)
        pvd[190:318] = b" ".ljust(128)
        # Publisher Identifier (128 bytes)
        pvd[318:446] = b"MIOROM".ljust(128)
        # Data Preparer Identifier (128 bytes)
        pvd[446:574] = b"MIOROM".ljust(128)
        # Application Identifier (128 bytes)
        pvd[574:702] = b"MIOROM".ljust(128)

        # Dates (17 bytes each)
        now = datetime.datetime.now(datetime.timezone.utc)
        now_pvd = format_pvd_datetime(now)
        pvd[813:830] = now_pvd  # Creation date
        pvd[830:847] = now_pvd  # Modification date
        pvd[847:864] = b"0" * 16 + b"\x00"  # Expiration date (unspecified)
        pvd[864:881] = now_pvd  # Effective date
        pvd[881] = 0x01         # File Structure Version

        # Volume Descriptor Set Terminator (Sector 17)
        vdst = bytearray(SECTOR_SIZE)
        vdst[0] = 0xFF
        vdst[1:6] = b"CD001"
        vdst[6] = 0x01

        # Assemble Complete ISO
        iso = bytearray(total_sectors * SECTOR_SIZE)
        # Sectors 0..15: System area
        iso[: 16 * SECTOR_SIZE] = self.system_area
        # Sector 16: PVD
        iso[16 * SECTOR_SIZE : 17 * SECTOR_SIZE] = pvd
        # Sector 17: VDST
        iso[17 * SECTOR_SIZE : 18 * SECTOR_SIZE] = vdst
        # Path Tables
        iso[l_path_lba * SECTOR_SIZE : (l_path_lba + path_table_sectors) * SECTOR_SIZE] = l_table
        iso[m_path_lba * SECTOR_SIZE : (m_path_lba + path_table_sectors) * SECTOR_SIZE] = m_table

        # Directories
        for d in dirs:
            d_data = dir_bytes_map[d]
            off = d.lba * SECTOR_SIZE
            iso[off : off + len(d_data)] = d_data

        # Files
        for f in files:
            if f.size > 0:
                off = f.lba * SECTOR_SIZE
                iso[off : off + f.size] = f.data

        return bytes(iso)

    def build_to_file(self, output_path: str):
        """Builds the ISO image and writes it directly to disk."""
        iso_bytes = self.build()
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as fp:
            fp.write(iso_bytes)
