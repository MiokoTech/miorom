"""
miorom.platforms.psx.memory_card
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Sony PlayStation 1 (PSX) Memory Card manager and save file engine.
Supports standard 128 KB (.mcr, .mcd, .sav) memory card images and
individual save block (.mcs) files.

Format Specifications:
- Total capacity: 131,072 bytes (128 KB), divided into 16 blocks of 8,192 bytes.
- Block 0: Filesystem directory block (64 frames of 128 bytes):
  * Frame 0: Header frame ('MC' signature, XOR checksum).
  * Frames 1..15: Directory entries for data blocks 1..15 (allocation state, size, next block, filename, XOR checksum).
  * Frames 16..35: Broken frame replacement list / test frames.
  * Frames 36..63: Reserved.
- Blocks 1..15: Save data blocks:
  * Frame 0: Save header ('SC' signature, icon display flags, block count, Shift-JIS title, 16-color BGR555 palette).
  * Frames 1..N: 16x16 4bpp animated icon bitmaps (1 to 3 frames, 128 bytes each).
  * Remaining frames: Raw game save payload.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

from miorom.core.schema import BinaryStruct, RawBytes, U16, U32, U8
from miorom.errors import ParseError
from miorom.graphics.palette import Color, Palette

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


CARD_SIZE = 131072       # 128 KB
BLOCK_SIZE = 8192        # 8 KB per block
NUM_BLOCKS = 16          # 1 header/directory block + 15 data blocks
FRAME_SIZE = 128         # 128 bytes per frame (sector)
FRAMES_PER_BLOCK = 64


class PSXBlockState:
    IN_USE_INITIAL = 0x00000051  # First or only block of file
    IN_USE_MIDDLE  = 0x00000052  # Middle block of multi-block file
    IN_USE_LAST    = 0x00000053  # Last block of multi-block file
    FREE           = 0x000000A0  # Freshly formatted / available
    DELETED_FIRST  = 0x000000A1  # Deleted initial block
    DELETED_MID    = 0x000000A2  # Deleted middle block
    DELETED_LAST   = 0x000000A3  # Deleted last block


def calculate_frame_xor(frame_bytes: bytes) -> int:
    """Calculates the XOR checksum of a 128-byte frame (bytes 0 to 126)."""
    xor_val = 0
    for b in frame_bytes[:127]:
        xor_val ^= b
    return xor_val


class PSXMCHeaderStruct(BinaryStruct):
    """
    Block 0 Frame 0 (Header Frame, 128 bytes).
    """
    _endian = "<"
    magic = RawBytes(2)          # b"MC"
    _reserved = RawBytes(125)
    checksum = U8()


class PSXMCDirectoryEntryStruct(BinaryStruct):
    """
    Block 0 Frames 1..15 (Directory Entry, 128 bytes).
    """
    _endian = "<"
    alloc_state = U32()
    file_size = U32()
    next_block = U16()
    filename = RawBytes(22)
    _reserved = RawBytes(95)
    checksum = U8()


class PSXSaveHeaderStruct(BinaryStruct):
    """
    Save Data Block Frame 0 Header (64 bytes).
    """
    _endian = "<"
    magic = RawBytes(2)          # b"SC"
    icon_flags = U8()            # 0x11 (1 frame), 0x12 (2 frames), 0x13 (3 frames)
    block_count = U8()           # Total 8KB blocks used (1..15)
    title_raw = RawBytes(64)     # Shift-JIS encoded title


@dataclass
class PSXSaveFile:
    """
    High-level representation of an individual PS1 save game.
    """
    filename: str
    title: str
    payload: bytes
    palette: Palette
    icon_bitmaps: List[bytes] = field(default_factory=list)
    file_size: int = 0
    block_count: int = 1
    block_index: int = 1

    def __post_init__(self) -> None:
        num_icons = max(1, min(3, len(self.icon_bitmaps)))
        header_and_icons_size = 128 + num_icons * 128
        if self.file_size <= 0:
            self.file_size = header_and_icons_size + len(self.payload)
        needed_blocks = max(1, (self.file_size + BLOCK_SIZE - 1) // BLOCK_SIZE)
        if self.block_count < needed_blocks:
            self.block_count = needed_blocks

    @classmethod
    def from_mcs(cls, data: bytes) -> "PSXSaveFile":
        """
        Parses an individual .mcs single-save file (128-byte header + N * 8192 data).
        """
        if len(data) < FRAME_SIZE + BLOCK_SIZE:
            raise ParseError(
                f"Data too short for .mcs save file (expected at least {FRAME_SIZE + BLOCK_SIZE} bytes, got {len(data)})."
            )

        dir_entry = PSXMCDirectoryEntryStruct.from_bytes(data[:FRAME_SIZE])
        filename = dir_entry.filename.decode("ascii", errors="replace").rstrip("\x00")
        file_size = dir_entry.file_size

        block_data = data[FRAME_SIZE:]
        if len(block_data) < BLOCK_SIZE:
            raise ParseError("Insufficient block data in .mcs file.")

        return cls._parse_save_content(
            dir_entry_filename=filename,
            file_size=file_size,
            block_data=block_data,
            start_block=1,
        )

    @classmethod
    def _parse_save_content(
        cls,
        dir_entry_filename: str,
        file_size: int,
        block_data: bytes,
        start_block: int,
    ) -> "PSXSaveFile":
        if len(block_data) < 128:
            raise ParseError("Block data too small for PSX save header.")

        save_hdr = PSXSaveHeaderStruct.from_bytes(block_data[:68])
        if save_hdr.magic != b"SC":
            raise ParseError(f"Invalid PSX save header magic: {save_hdr.magic!r} (expected b'SC').")

        icon_flags = save_hdr.icon_flags
        block_count = max(1, save_hdr.block_count)
        num_icons = max(1, min(3, icon_flags & 0x0F))

        title = save_hdr.title_raw.decode("shift_jis", errors="replace").rstrip("\x00")

        # 16-color palette at offset 0x60..0x7F (32 bytes)
        pal_bytes = block_data[0x60:0x80]
        colors: List[Color] = []
        for i in range(16):
            if (i * 2 + 2) <= len(pal_bytes):
                val = struct.unpack_from("<H", pal_bytes, i * 2)[0]
                # Color 0 is transparent in BIOS icon display
                alpha = 0 if i == 0 else 255
                colors.append(Color.from_bgr555(val & 0x7FFF, alpha=alpha))
            else:
                colors.append(Color(0, 0, 0, 0))
        palette = Palette(colors)

        # Icon bitmaps (128 bytes each, starting at offset 0x80)
        icon_bitmaps: List[bytes] = []
        curr_off = 0x80
        for _ in range(num_icons):
            if curr_off + 128 <= len(block_data):
                icon_bitmaps.append(block_data[curr_off : curr_off + 128])
            else:
                icon_bitmaps.append(b"\x00" * 128)
            curr_off += 128

        # Save payload begins after icon frames
        payload_start = curr_off
        payload = block_data[payload_start:file_size] if file_size > payload_start else block_data[payload_start:]

        return cls(
            filename=dir_entry_filename,
            title=title,
            file_size=file_size,
            block_count=block_count,
            payload=payload,
            palette=palette,
            icon_bitmaps=icon_bitmaps,
            block_index=start_block,
        )

    def decode_icon_rgba(self, frame_idx: int = 0) -> bytes:
        """
        Decodes a 16x16 4bpp icon frame into 1024 raw RGBA bytes.
        """
        if not self.icon_bitmaps:
            return bytes(16 * 16 * 4)

        idx = max(0, min(frame_idx, len(self.icon_bitmaps) - 1))
        bmp = self.icon_bitmaps[idx]
        rgba = bytearray(16 * 16 * 4)

        for y in range(16):
            for x in range(16):
                byte_off = y * 8 + (x // 2)
                b = bmp[byte_off] if byte_off < len(bmp) else 0
                color_idx = (b & 0x0F) if (x % 2 == 0) else ((b >> 4) & 0x0F)
                c = self.palette[color_idx] if color_idx < len(self.palette) else Color(0, 0, 0, 0)

                out_off = (y * 16 + x) * 4
                rgba[out_off : out_off + 4] = bytes([c.r, c.g, c.b, c.a])

        return bytes(rgba)

    def get_icon_image(self, frame_idx: int = 0) -> Optional["Image.Image"]:
        """
        Renders an icon frame as a PIL RGBA Image.
        """
        if not HAS_PIL:
            return None

        rgba_bytes = self.decode_icon_rgba(frame_idx)
        img = Image.frombytes("RGBA", (16, 16), rgba_bytes)
        return img

    def get_icon_images(self) -> List["Image.Image"]:
        """
        Renders all animated icon frames as PIL RGBA Images.
        """
        if not HAS_PIL:
            return []
        return [self.get_icon_image(i) for i in range(len(self.icon_bitmaps)) if self.get_icon_image(i) is not None]

    def build_block_data(self) -> bytes:
        """
        Serializes this save file into (block_count * 8192) bytes.
        """
        total_size = self.block_count * BLOCK_SIZE
        buf = bytearray(total_size)

        # Header 68 bytes
        buf[0:2] = b"SC"
        num_icons = max(1, min(3, len(self.icon_bitmaps)))
        icon_flags = 0x10 | num_icons
        buf[2] = icon_flags
        buf[3] = self.block_count

        # Shift-JIS title (64 bytes)
        encoded_title = self.title.encode("shift_jis", errors="replace")[:64]
        buf[4 : 4 + len(encoded_title)] = encoded_title

        # Palette at 0x60..0x7F (32 bytes)
        pal_bytes = bytearray(32)
        for i in range(16):
            if i < len(self.palette):
                c = self.palette[i]
                val = c.to_bgr555()
            else:
                val = 0
            pal_bytes[i * 2 : i * 2 + 2] = struct.pack("<H", val)
        buf[0x60:0x80] = pal_bytes

        # Icon bitmaps
        curr_off = 0x80
        for i in range(num_icons):
            bmp = self.icon_bitmaps[i] if i < len(self.icon_bitmaps) else (b"\x00" * 128)
            buf[curr_off : curr_off + 128] = bmp[:128].ljust(128, b"\x00")
            curr_off += 128

        # Payload
        payload_end = min(total_size, curr_off + len(self.payload))
        buf[curr_off:payload_end] = self.payload[: payload_end - curr_off]

        return bytes(buf)

    def to_mcs(self) -> bytes:
        """
        Exports the save file into standard .mcs single save format.
        """
        dir_buf = bytearray(128)
        dir_buf[0:4] = struct.pack("<I", PSXBlockState.IN_USE_INITIAL)
        dir_buf[4:8] = struct.pack("<I", self.file_size)
        dir_buf[8:10] = struct.pack("<H", 0xFFFF)

        fname_bytes = self.filename.encode("ascii", errors="replace")[:21]
        dir_buf[10 : 10 + len(fname_bytes)] = fname_bytes

        dir_buf[127] = calculate_frame_xor(dir_buf)

        blocks = self.build_block_data()
        return bytes(dir_buf) + blocks


class PSXMemoryCard:
    """
    PlayStation 1 (PSX) Memory Card manager (128 KB image).
    """

    MAGIC = b"MC"

    def __init__(self, raw_data: bytearray):
        if len(raw_data) != CARD_SIZE:
            raise ParseError(
                f"Invalid PSX memory card size: {len(raw_data)} bytes (must be exactly {CARD_SIZE} bytes)."
            )
        if raw_data[:2] != self.MAGIC:
            raise ParseError(f"Invalid memory card header magic: {raw_data[:2]!r} (expected b'MC').")
        self._data = raw_data

    @classmethod
    def from_bytes(cls, data: bytes) -> "PSXMemoryCard":
        """
        Loads and verifies a 128 KB PSX memory card image.
        """
        return cls(bytearray(data))

    @classmethod
    def format_blank(cls) -> "PSXMemoryCard":
        """
        Creates a freshly formatted, blank 128 KB memory card image.
        """
        buf = bytearray(CARD_SIZE)

        # Frame 0: Header frame
        buf[0:2] = cls.MAGIC
        buf[127] = calculate_frame_xor(buf[:128])

        # Frames 1..15: Directory entries (all FREE)
        for i in range(1, 16):
            frame_off = i * FRAME_SIZE
            buf[frame_off : frame_off + 4] = struct.pack("<I", PSXBlockState.FREE)
            buf[frame_off + 4 : frame_off + 8] = struct.pack("<I", 0)
            buf[frame_off + 8 : frame_off + 10] = struct.pack("<H", 0xFFFF)
            buf[frame_off + 127] = calculate_frame_xor(buf[frame_off : frame_off + 128])

        # Frames 16..35: Broken frame list (clean entries)
        for i in range(16, 36):
            frame_off = i * FRAME_SIZE
            buf[frame_off : frame_off + 4] = struct.pack("<I", 0xFFFFFFFF)
            buf[frame_off + 4 : frame_off + 8] = struct.pack("<I", 0)
            buf[frame_off + 8 : frame_off + 10] = struct.pack("<H", 0xFFFF)
            buf[frame_off + 127] = calculate_frame_xor(buf[frame_off : frame_off + 128])

        return cls(buf)

    def to_bytes(self, fix_checksums: bool = True) -> bytes:
        """
        Serializes the memory card to 128 KB bytes, recalculating XOR checksums if requested.
        """
        if fix_checksums:
            self.repair_checksums()
        return bytes(self._data)

    def repair_checksums(self) -> None:
        """
        Recalculates XOR checksums for all Block 0 directory and system frames.
        """
        # Frame 0 to 63
        for i in range(64):
            frame_off = i * FRAME_SIZE
            self._data[frame_off + 127] = calculate_frame_xor(self._data[frame_off : frame_off + 128])

    def get_directory_entry(self, block_index: int) -> PSXMCDirectoryEntryStruct:
        """
        Returns the raw directory entry struct for the specified block index (1..15).
        """
        if not (1 <= block_index <= 15):
            raise IndexError(f"Block index out of range: {block_index} (must be 1..15).")
        frame_off = block_index * FRAME_SIZE
        return PSXMCDirectoryEntryStruct.from_bytes(self._data[frame_off : frame_off + FRAME_SIZE])

    def get_free_blocks(self) -> List[int]:
        """
        Returns a list of block indices (1..15) that are free or deleted.
        """
        free_blocks: List[int] = []
        for i in range(1, 16):
            entry = self.get_directory_entry(i)
            if entry.alloc_state in (
                PSXBlockState.FREE,
                PSXBlockState.DELETED_FIRST,
                PSXBlockState.DELETED_MID,
                PSXBlockState.DELETED_LAST,
            ):
                free_blocks.append(i)
        return free_blocks

    def get_files(self) -> List[PSXSaveFile]:
        """
        Parses and returns all active save files on the memory card.
        """
        files: List[PSXSaveFile] = []
        visited = set()

        for i in range(1, 16):
            if i in visited:
                continue

            entry = self.get_directory_entry(i)
            if entry.alloc_state == PSXBlockState.IN_USE_INITIAL:
                # Traverse block chain
                chain = [i]
                visited.add(i)
                curr = entry.next_block
                while curr != 0xFFFF and (1 <= curr <= 15) and curr not in visited:
                    chain.append(curr)
                    visited.add(curr)
                    next_ent = self.get_directory_entry(curr)
                    curr = next_ent.next_block

                # Assemble block data
                block_data = bytearray()
                for b_idx in chain:
                    b_off = b_idx * BLOCK_SIZE
                    block_data.extend(self._data[b_off : b_off + BLOCK_SIZE])

                filename = entry.filename.decode("ascii", errors="replace").rstrip("\x00")
                save_file = PSXSaveFile._parse_save_content(
                    dir_entry_filename=filename,
                    file_size=entry.file_size,
                    block_data=bytes(block_data),
                    start_block=i,
                )
                save_file.block_count = len(chain)
                files.append(save_file)

        return files

    def inject_file(self, save: PSXSaveFile, start_block: Optional[int] = None) -> int:
        """
        Injects a save file into the memory card.
        If start_block is None, allocates available free blocks automatically.
        Returns the initial block index.
        """
        req_blocks = max(1, save.block_count)
        free_blocks = self.get_free_blocks()

        if start_block is not None:
            if start_block not in free_blocks:
                raise ValueError(f"Target start block {start_block} is already in use or invalid.")
            # Allocate starting at start_block
            chain = [start_block]
            other_free = [b for b in free_blocks if b != start_block]
            if len(chain) + len(other_free) < req_blocks:
                raise ValueError(f"Not enough free space on card for {req_blocks} blocks.")
            chain.extend(other_free[: req_blocks - 1])
        else:
            if len(free_blocks) < req_blocks:
                raise ValueError(
                    f"Not enough free blocks: required {req_blocks}, available {len(free_blocks)}."
                )
            chain = free_blocks[:req_blocks]

        raw_blocks = save.build_block_data()

        # Write data blocks
        for idx, b_idx in enumerate(chain):
            b_off = b_idx * BLOCK_SIZE
            chunk = raw_blocks[idx * BLOCK_SIZE : (idx + 1) * BLOCK_SIZE]
            self._data[b_off : b_off + BLOCK_SIZE] = chunk.ljust(BLOCK_SIZE, b"\x00")

            # Update directory entry
            frame_off = b_idx * FRAME_SIZE
            dir_buf = bytearray(128)

            if idx == 0:
                alloc = PSXBlockState.IN_USE_INITIAL
            elif idx == len(chain) - 1:
                alloc = PSXBlockState.IN_USE_LAST
            else:
                alloc = PSXBlockState.IN_USE_MIDDLE

            next_b = chain[idx + 1] if idx + 1 < len(chain) else 0xFFFF

            dir_buf[0:4] = struct.pack("<I", alloc)
            dir_buf[4:8] = struct.pack("<I", save.file_size)
            dir_buf[8:10] = struct.pack("<H", next_b)

            fname_bytes = save.filename.encode("ascii", errors="replace")[:21]
            dir_buf[10 : 10 + len(fname_bytes)] = fname_bytes

            dir_buf[127] = calculate_frame_xor(dir_buf)
            self._data[frame_off : frame_off + FRAME_SIZE] = dir_buf

        return chain[0]

    def delete_file(self, start_block: int) -> None:
        """
        Deletes a save file starting at start_block by updating allocation flags.
        """
        curr = start_block
        is_first = True

        while curr != 0xFFFF and (1 <= curr <= 15):
            entry = self.get_directory_entry(curr)
            frame_off = curr * FRAME_SIZE

            if is_first:
                new_alloc = PSXBlockState.DELETED_FIRST
                is_first = False
            elif entry.next_block == 0xFFFF:
                new_alloc = PSXBlockState.DELETED_LAST
            else:
                new_alloc = PSXBlockState.DELETED_MID

            self._data[frame_off : frame_off + 4] = struct.pack("<I", new_alloc)
            self._data[frame_off + 127] = calculate_frame_xor(self._data[frame_off : frame_off + 128])
            curr = entry.next_block
