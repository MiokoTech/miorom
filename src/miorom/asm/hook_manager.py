"""
miorom.asm.hook_manager
~~~~~~~~~~~~~~~~~~~~~~~
ARM/Thumb inline hook builder and code cave manager for ROM patching.
"""

import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

from miorom.result import MioRomResult


@dataclass
class CodeCave(MioRomResult):
    """Represents a contiguous region of free/unused space in a ROM buffer."""

    start: int
    size: int
    used: int = 0
    label: str = ""

    @property
    def free(self) -> int:
        return self.size - self.used

    @property
    def end(self) -> int:
        return self.start + self.size


@dataclass
class HookRecord(MioRomResult):
    """Record of a successfully installed hook."""

    hook_offset: int
    cave_offset: int
    arch: str
    hook_bytes: bytes
    original_bytes: bytes
    hook_size: int


class CodeCaveManager:
    """Discovers and manages code caves (free space regions) within a ROM buffer."""

    def __init__(self, fill_byte: int = 0x00) -> None:
        self.fill_byte = fill_byte
        self._caves: List[CodeCave] = []

    def scan(
        self,
        rom: Union[bytes, bytearray],
        min_size: int = 32,
        search_start: int = 0,
        search_end: Optional[int] = None,
    ) -> List[CodeCave]:
        """Find contiguous runs of fill_byte >= min_size bytes and register them as caves."""
        from miorom.core.slicer import find_free_blocks

        if search_end is None:
            search_end = len(rom)

        sub_slice = memoryview(rom)[search_start:search_end]
        raw_blocks = find_free_blocks(sub_slice, fill_byte=self.fill_byte, min_size=min_size)

        found: List[CodeCave] = []
        for rel_offset, block_len in raw_blocks:
            cave = CodeCave(start=search_start + rel_offset, size=block_len, used=0, label="")
            self._caves.append(cave)
            found.append(cave)

        return found

    def register(self, offset: int, size: int, label: str = "") -> CodeCave:
        """Manually register a known free space region as a cave."""
        cave = CodeCave(start=offset, size=size, used=0, label=label)
        self._caves.append(cave)
        return cave

    def allocate(self, size: int, label: str = "") -> Tuple[CodeCave, int]:
        """Find the first cave with enough free space and return (cave, offset_within_cave)."""
        for cave in self._caves:
            if cave.free >= size:
                offset_within = cave.used
                return cave, offset_within
        raise ValueError(f"No registered code cave has {size} bytes of free space.")

    def write_to_cave(self, buf: bytearray, cave: CodeCave, code: bytes) -> int:
        """Write code bytes into the cave at cave.start + cave.used; advance cave.used."""
        if len(code) > cave.free:
            raise ValueError(
                f"Code ({len(code)} bytes) exceeds remaining cave space ({cave.free} bytes)."
            )
        abs_offset = cave.start + cave.used
        buf[abs_offset : abs_offset + len(code)] = code
        cave.used += len(code)
        return abs_offset

    @property
    def caves(self) -> List[CodeCave]:
        return list(self._caves)


class ArmHookBuilder:
    """Static helpers for encoding ARM and Thumb branch instructions."""

    @staticmethod
    def build_arm_bl(from_addr: int, to_addr: int) -> bytes:
        """Encode a 4-byte ARM BL instruction."""
        offset = (to_addr - from_addr - 8) >> 2
        word = 0xEB000000 | (offset & 0xFFFFFF)
        return struct.pack("<I", word)

    @staticmethod
    def build_arm_b(from_addr: int, to_addr: int) -> bytes:
        """Encode a 4-byte ARM B instruction."""
        offset = (to_addr - from_addr - 8) >> 2
        word = 0xEA000000 | (offset & 0xFFFFFF)
        return struct.pack("<I", word)

    @staticmethod
    def build_thumb_bl(from_addr: int, to_addr: int) -> bytes:
        """Encode a 4-byte Thumb BL (two 16-bit halfwords, long-range branch with link)."""
        offset = to_addr - (from_addr + 4)
        hw1 = 0xF000 | ((offset >> 12) & 0x7FF)
        hw2 = 0xF800 | ((offset >> 1) & 0x7FF)
        return struct.pack("<HH", hw1, hw2)

    @staticmethod
    def build_thumb_b(from_addr: int, to_addr: int) -> bytes:
        """Encode a 2-byte Thumb B with 11-bit offset (short-range unconditional branch)."""
        offset = to_addr - (from_addr + 4)
        imm11 = (offset >> 1) & 0x7FF
        hw = 0xE000 | imm11
        return struct.pack("<H", hw)

    @staticmethod
    def build_arm_trampoline_return(displaced: bytes, return_addr: int) -> bytes:
        """Build cave epilogue: displaced instruction(s) followed by B back to return_addr."""
        displaced_len = len(displaced)
        epilogue_pc = return_addr - displaced_len - 4
        branch_offset = (return_addr - (epilogue_pc + displaced_len + 8)) >> 2
        b_word = 0xEA000000 | (branch_offset & 0xFFFFFF)
        return displaced + struct.pack("<I", b_word)


class HookManager:
    """High-level manager that installs ARM/Thumb inline hooks into a ROM buffer."""

    def __init__(self, cave_manager: Optional[CodeCaveManager] = None) -> None:
        self.cave_manager = cave_manager or CodeCaveManager()
        self._hooks: List[HookRecord] = []

    def install_arm_hook(
        self,
        buf: bytearray,
        hook_rom_offset: int,
        hook_ram_addr: int,
        cave_ram_addr: int,
        cave_rom_offset: int,
        cave_code: bytes,
        mode: str = "bl",
    ) -> HookRecord:
        """Write a BL or B at hook_rom_offset pointing to cave_ram_addr, then write cave code."""
        original_bytes = bytes(buf[hook_rom_offset : hook_rom_offset + 4])

        if mode == "bl":
            hook_bytes = ArmHookBuilder.build_arm_bl(hook_ram_addr, cave_ram_addr)
        else:
            hook_bytes = ArmHookBuilder.build_arm_b(hook_ram_addr, cave_ram_addr)

        return_addr = hook_ram_addr + 4
        trampoline = cave_code + ArmHookBuilder.build_arm_b(
            cave_ram_addr + len(cave_code), return_addr
        )

        buf[hook_rom_offset : hook_rom_offset + 4] = hook_bytes
        buf[cave_rom_offset : cave_rom_offset + len(trampoline)] = trampoline

        record = HookRecord(
            hook_offset=hook_rom_offset,
            cave_offset=cave_rom_offset,
            arch="arm",
            hook_bytes=hook_bytes,
            original_bytes=original_bytes,
            hook_size=4,
        )
        self._hooks.append(record)
        return record

    def install_thumb_hook(
        self,
        buf: bytearray,
        hook_rom_offset: int,
        hook_ram_addr: int,
        cave_ram_addr: int,
        cave_rom_offset: int,
        cave_code: bytes,
        mode: str = "bl",
    ) -> HookRecord:
        """Write a Thumb BL or B at hook_rom_offset pointing to cave_ram_addr, then write cave code."""
        original_bytes = bytes(buf[hook_rom_offset : hook_rom_offset + 4])

        if mode == "bl":
            hook_bytes = ArmHookBuilder.build_thumb_bl(hook_ram_addr, cave_ram_addr)
        else:
            hook_bytes = ArmHookBuilder.build_thumb_b(hook_ram_addr, cave_ram_addr)

        return_addr = hook_ram_addr + 4
        cave_end_addr = cave_ram_addr + len(cave_code)
        ret_branch = ArmHookBuilder.build_thumb_bl(cave_end_addr, return_addr)
        trampoline = cave_code + ret_branch

        buf[hook_rom_offset : hook_rom_offset + len(hook_bytes)] = hook_bytes
        buf[cave_rom_offset : cave_rom_offset + len(trampoline)] = trampoline

        record = HookRecord(
            hook_offset=hook_rom_offset,
            cave_offset=cave_rom_offset,
            arch="thumb",
            hook_bytes=hook_bytes,
            original_bytes=original_bytes,
            hook_size=len(hook_bytes),
        )
        self._hooks.append(record)
        return record

    @property
    def hooks(self) -> List[HookRecord]:
        return list(self._hooks)
