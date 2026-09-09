from miorom.result import MioRomResult
import os
from miorom.errors import ParseError
from dataclasses import dataclass, field
from miorom.core.schema import BinaryStruct, FixedString, RawBytes, U32, U8
from typing import Dict, List, Optional, Tuple


class GCHeaderStruct(BinaryStruct):
    _endian = ">"
    game_id = FixedString(4)
    maker_code = FixedString(2)
    disc_number = U8()
    version = U8()
    audio_streaming = U8()
    stream_buf_size = U8()
    _reserved_0x0A = RawBytes(0x12)
    magic = U32()
    game_title = FixedString(64, encoding="shift-jis")
    _reserved_0x60 = RawBytes(0x3C0)
    dol_offset = U32()
    fst_offset = U32()
    fst_size = U32()
    fst_max_size = U32()
    user_pos = U32()
    user_length = U32()
    _reserved_0x438 = RawBytes(8)


class GCFstEntryStruct(BinaryStruct):
    _endian = ">"
    flags = U8()
    name_offset_raw = RawBytes(3)
    first_value = U32()
    second_value = U32()


@dataclass
class GCHeader(MioRomResult):
    """GameCube / Wii Disc Header (0x0000..0x0440)."""
    game_id: str
    maker_code: str
    disc_number: int
    version: int
    audio_streaming: bool
    stream_buf_size: int
    magic: int
    game_title: str
    dol_offset: int
    fst_offset: int
    fst_size: int
    fst_max_size: int
    user_pos: int
    user_length: int

    @classmethod
    def parse(cls, data: bytes) -> "GCHeader":
        if len(data) < GCHeaderStruct.sizeof():
            raise ParseError("Disc buffer too small for GameCube header (requires at least 0x440 bytes).")

        parsed = GCHeaderStruct.from_bytes(data, offset=0)
        game_id = parsed.game_id.strip("\x00")
        maker_code = parsed.maker_code.strip("\x00")
        disc_num = parsed.disc_number
        version = parsed.version
        audio_stream = parsed.audio_streaming != 0
        stream_buf = parsed.stream_buf_size
        magic = parsed.magic
        title = parsed.game_title.strip("\x00").strip()

        return cls(
            game_id=game_id,
            maker_code=maker_code,
            disc_number=disc_num,
            version=version,
            audio_streaming=audio_stream,
            stream_buf_size=stream_buf,
            magic=magic,
            game_title=title,
            dol_offset=parsed.dol_offset,
            fst_offset=parsed.fst_offset,
            fst_size=parsed.fst_size,
            fst_max_size=parsed.fst_max_size,
            user_pos=parsed.user_pos,
            user_length=parsed.user_length,
        )

    def pack(self) -> bytes:
        struct_data = GCHeaderStruct(
            game_id=self.game_id,
            maker_code=self.maker_code,
            disc_number=self.disc_number,
            version=self.version,
            audio_streaming=1 if self.audio_streaming else 0,
            stream_buf_size=self.stream_buf_size,
            magic=self.magic,
            game_title=self.game_title,
            dol_offset=self.dol_offset,
            fst_offset=self.fst_offset,
            fst_size=self.fst_size,
            fst_max_size=self.fst_max_size,
            user_pos=self.user_pos,
            user_length=self.user_length,
        )
        return struct_data.to_bytes()


@dataclass
class FSTEntry(MioRomResult):
    """Represents a file or directory node within the GameCube FST."""
    index: int
    is_directory: bool
    name: str
    path: str
    file_offset: int
    file_size: int
    parent_index: int = 0
    next_entry_index: int = 0


class GameCubeDisc:
    """
    Pure-Python GameCube & Wii Optical Disc Image (.iso / .gcm) Engine.
    Parses Disc Header, File System Table (FST), extracts and replaces files,
    recalculates FST tree offsets, and re-packs disc images bitwise accurately.
    """

    GC_MAGIC = 0xC2339F3D

    def __init__(self, data: bytes):
        self.raw_data = bytearray(data)
        self.header = GCHeader.parse(self.raw_data[:0x440])
        self.entries: List[FSTEntry] = []
        self.files: Dict[str, bytes] = {}
        self._parse_fst()

    @classmethod
    def from_file(cls, path: str) -> "GameCubeDisc":
        with open(path, "rb") as f:
            return cls(f.read())

    def _parse_fst(self):
        fst_off = self.header.fst_offset
        fst_sz = self.header.fst_size
        if fst_off == 0 or fst_sz < 12 or fst_off + fst_sz > len(self.raw_data):
            return

        fst_data = self.raw_data[fst_off:fst_off + fst_sz]

        # Root entry (12 bytes)
        root_entry = GCFstEntryStruct.from_bytes(fst_data, offset=0)
        root_num_entries = root_entry.second_value
        string_table_offset = root_num_entries * 12

        str_table = fst_data[string_table_offset:]

        def get_string(offset: int) -> str:
            if offset >= len(str_table):
                return ""
            end = str_table.find(b"\x00", offset)
            if end == -1:
                end = len(str_table)
            return str_table[offset:end].decode("ascii", errors="replace")

        # Parse all entries
        dir_stack = [("", 0, root_num_entries)]  # (path, entry_idx, next_idx)

        for i in range(root_num_entries):
            off = i * 12
            entry_raw = GCFstEntryStruct.from_bytes(fst_data, offset=off)
            flags = entry_raw.flags
            name_offset = int.from_bytes(entry_raw.name_offset_raw, "big")

            if flags & 1:  # Directory
                parent_idx = entry_raw.first_value
                next_idx = entry_raw.second_value

                if i == 0:
                    entry_name = ""
                    current_path = ""
                else:
                    entry_name = get_string(name_offset)
                    # Pop stack if passed parent scope
                    while dir_stack and i >= dir_stack[-1][2]:
                        dir_stack.pop()
                    parent_path = dir_stack[-1][0] if dir_stack else ""
                    current_path = f"{parent_path}/{entry_name}".strip("/")

                dir_stack.append((current_path, i, next_idx))

                entry = FSTEntry(
                    index=i,
                    is_directory=True,
                    name=entry_name,
                    path=current_path,
                    file_offset=0,
                    file_size=0,
                    parent_index=parent_idx,
                    next_entry_index=next_idx,
                )
                self.entries.append(entry)

            else:  # File
                f_offset = entry_raw.first_value
                f_size = entry_raw.second_value
                entry_name = get_string(name_offset)

                while dir_stack and i >= dir_stack[-1][2]:
                    dir_stack.pop()
                parent_path = dir_stack[-1][0] if dir_stack else ""
                current_path = f"{parent_path}/{entry_name}".strip("/")

                entry = FSTEntry(
                    index=i,
                    is_directory=False,
                    name=entry_name,
                    path=current_path,
                    file_offset=f_offset,
                    file_size=f_size,
                    parent_index=dir_stack[-1][1] if dir_stack else 0,
                    next_entry_index=0,
                )
                self.entries.append(entry)

                if f_offset + f_size <= len(self.raw_data):
                    self.files[current_path] = bytes(self.raw_data[f_offset:f_offset + f_size])
                else:
                    self.files[current_path] = b""

    def read_file(self, path: str) -> bytes:
        """Read full contents of a file inside the disc."""
        clean = path.strip("/")
        if clean in self.files:
            return self.files[clean]
        raise FileNotFoundError(f"File '{path}' not found in GameCube FST.")

    def replace_file(self, path: str, new_data: bytes):
        """Replace file payload in memory."""
        clean = path.strip("/")
        if clean not in self.files:
            raise FileNotFoundError(f"Cannot replace: file '{path}' does not exist in disc.")
        self.files[clean] = bytes(new_data)

    def add_file(self, path: str, data: bytes):
        """Add or overwrite a file in the disc."""
        clean = path.strip("/")
        self.files[clean] = bytes(data)

    def to_bytes(self, alignment: int = 32) -> bytes:
        """
        Reconstruct and rebuild the complete GameCube disc image with updated FST.
        """
        # 1. Build sorted hierarchical file tree
        # Paths: list of files
        file_paths = sorted(self.files.keys())

        # Collect directories
        dirs_set = set()
        for p in file_paths:
            parts = p.split("/")
            for i in range(1, len(parts)):
                dirs_set.add("/".join(parts[:i]))

        # Organize into tree nodes
        # We assign indices in DFS order
        fst_entries_meta = []  # list of dicts

        # Root entry (index 0)
        fst_entries_meta.append({
            "is_dir": True,
            "name": "",
            "path": "",
            "parent": 0,
            "next_idx": 0,
            "offset": 0,
            "size": 0,
        })

        # Collect files by directory
        # Flatten tree in DFS order
        def build_subtree(current_dir_path: str, parent_idx: int):
            # Children dirs
            subdirs = sorted([
                d for d in dirs_set
                if (os.path.dirname(d) == current_dir_path if current_dir_path else "/" not in d)
            ])
            # Direct files
            subfiles = sorted([
                f for f in file_paths
                if (os.path.dirname(f) == current_dir_path if current_dir_path else "/" not in f)
            ])

            for sd in subdirs:
                my_idx = len(fst_entries_meta)
                dname = os.path.basename(sd)
                entry_dict = {
                    "is_dir": True,
                    "name": dname,
                    "path": sd,
                    "parent": parent_idx,
                    "next_idx": 0,  # will update after recursion
                    "offset": 0,
                    "size": 0,
                }
                fst_entries_meta.append(entry_dict)
                build_subtree(sd, my_idx)
                entry_dict["next_idx"] = len(fst_entries_meta)

            for sf in subfiles:
                fname = os.path.basename(sf)
                fdata = self.files[sf]
                fst_entries_meta.append({
                    "is_dir": False,
                    "name": fname,
                    "path": sf,
                    "parent": parent_idx,
                    "next_idx": 0,
                    "offset": 0,  # will assign during layout
                    "size": len(fdata),
                    "data": fdata,
                })

        build_subtree("", 0)
        fst_entries_meta[0]["next_idx"] = len(fst_entries_meta)

        # 2. Build string table
        str_table = bytearray()
        str_offsets = {}
        for entry in fst_entries_meta:
            name = entry["name"]
            if name:
                if name not in str_offsets:
                    str_offsets[name] = len(str_table)
                    str_table.extend(name.encode("ascii") + b"\x00")
                entry["name_offset"] = str_offsets[name]
            else:
                entry["name_offset"] = 0

        # 3. Calculate FST size
        num_entries = len(fst_entries_meta)
        entries_size = num_entries * 12
        total_fst_size = entries_size + len(str_table)
        # Pad FST to 32 bytes
        pad = (32 - (total_fst_size % 32)) % 32
        total_fst_size += pad

        fst_offset = self.header.fst_offset or 0x450000
        file_data_start = fst_offset + total_fst_size

        # Align file_data_start
        rem = file_data_start % alignment
        if rem != 0:
            file_data_start += alignment - rem

        # 4. Lay out file offsets
        cur_file_offset = file_data_start
        file_buffers = []

        for entry in fst_entries_meta:
            if not entry["is_dir"]:
                rem = cur_file_offset % alignment
                if rem != 0:
                    cur_file_offset += alignment - rem
                entry["offset"] = cur_file_offset
                file_buffers.append((cur_file_offset, entry["data"]))
                cur_file_offset += entry["size"]

        # 5. Pack FST binary
        fst_bin = bytearray()
        for entry in fst_entries_meta:
            flags = 1 if entry["is_dir"] else 0
            name_off = entry.get("name_offset", 0) & 0x00FFFFFF

            if entry["is_dir"]:
                first_value, second_value = entry["parent"], entry["next_idx"]
            else:
                first_value, second_value = entry["offset"], entry["size"]

            fst_bin.extend(GCFstEntryStruct(
                flags=flags,
                name_offset_raw=name_off.to_bytes(3, "big"),
                first_value=first_value,
                second_value=second_value,
            ).to_bytes())

        fst_bin.extend(str_table)
        fst_bin.extend(b"\x00" * pad)

        # 6. Update disc header
        self.header.fst_offset = fst_offset
        self.header.fst_size = len(fst_bin)
        self.header.fst_max_size = max(self.header.fst_max_size, len(fst_bin))
        self.header.user_pos = file_data_start
        self.header.user_length = cur_file_offset - file_data_start

        # 7. Assemble full disc
        total_disc_len = max(len(self.raw_data), cur_file_offset)
        out_disc = bytearray(self.raw_data)
        if len(out_disc) < total_disc_len:
            out_disc.extend(b"\x00" * (total_disc_len - len(out_disc)))

        # Write header
        out_disc[:0x440] = self.header.pack()

        # Write FST
        out_disc[fst_offset:fst_offset + len(fst_bin)] = fst_bin

        # Write files
        for f_off, f_data in file_buffers:
            out_disc[f_off:f_off + len(f_data)] = f_data

        return bytes(out_disc)

    def save(self, path: str, alignment: int = 32):
        """Save modified disc image to disk."""
        data = self.to_bytes(alignment=alignment)
        with open(path, "wb") as f:
            f.write(data)
