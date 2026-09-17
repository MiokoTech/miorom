"""
miorom.core.overlay_mapper
~~~~~~~~~~~~~~~~~~~~~~~~~~
RAM-to-ROM Overlay and Virtual Memory Mapping Engine.
Translates runtime RAM addresses (from GDB, save states, or emulator traces)
to physical ROM file offsets across systems with dynamic overlays, bank switching,
and DMA load routines (Nintendo DS, Game Boy Advance, PlayStation 1, N64).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

from miorom.core import schema
from miorom.errors import CompressedOverlayError
from miorom.result import MioRomResult


@dataclass
class OverlayRegion(MioRomResult):
    """
    Represents a mapped memory segment or overlay.

    Precondition for linear address translation:
        Linear address translation (ram_to_rom and rom_to_ram) is only valid for
        UNCOMPRESSED overlays (flags bit 24 == 0). For compressed overlays (e.g.
        LZ10/BLZ compressed NDS overlays), physical ROM offsets cannot be mapped 1:1
        to execution RAM addresses via linear delta arithmetic.
    """
    region_id: Union[int, str]
    name: str
    ram_address: int
    ram_size: int
    rom_offset: int
    rom_size: int
    bss_size: int = 0
    flags: int = 0

    @property
    def is_compressed(self) -> bool:
        """Returns True if the overlay data in ROM is compressed (bit 24 of flags set)."""
        return bool(self.flags & 0x01000000)

    def contains_ram(self, ram_addr: int) -> bool:
        return self.ram_address <= ram_addr < (self.ram_address + self.ram_size)

    def contains_rom(self, rom_off: int) -> bool:
        return self.rom_offset <= rom_off < (self.rom_offset + self.rom_size)

    def ram_to_rom(self, ram_addr: int, raise_on_compressed: bool = False) -> Optional[int]:
        """
        Translates a virtual RAM address to its physical ROM file offset.

        Precondition:
            Linear address translation is only valid for uncompressed overlays. If the
            overlay is compressed (flags bit 24 set), this method returns None (or raises
            CompressedOverlayError if raise_on_compressed=True) because compressed stream
            offsets do not correspond 1:1 to RAM addresses. Callers should decompress the
            overlay first (e.g. via NDSOverlayCompressor.decompress()) before performing
            offset mapping on the decompressed data. Returning None by default prevents
            exceptions from interrupting multi-region iteration in MemoryOverlayMapper.
        """
        if not self.contains_ram(ram_addr):
            return None

        if self.is_compressed:
            if raise_on_compressed:
                raise CompressedOverlayError(
                    f"Overlay region '{self.name}' (id={self.region_id}) is compressed; "
                    "linear address translation is not valid for compressed overlays. "
                    "Decompress the overlay first (e.g. via NDSOverlayCompressor.decompress())."
                )
            return None

        delta = ram_addr - self.ram_address
        if delta < self.rom_size:
            return self.rom_offset + delta
        return None

    def rom_to_ram(self, rom_off: int, raise_on_compressed: bool = False) -> Optional[int]:
        """
        Translates a physical ROM file offset to its execution RAM address.

        Precondition:
            Linear address translation is only valid for uncompressed overlays. If the
            overlay is compressed (flags bit 24 set), this method returns None (or raises
            CompressedOverlayError if raise_on_compressed=True) because compressed stream
            offsets do not correspond 1:1 to RAM addresses. Callers should decompress the
            overlay first (e.g. via NDSOverlayCompressor.decompress()) before performing
            offset mapping on the decompressed data. Returning None by default prevents
            exceptions from interrupting multi-region iteration in MemoryOverlayMapper.
        """
        if not self.contains_rom(rom_off):
            return None

        if self.is_compressed:
            if raise_on_compressed:
                raise CompressedOverlayError(
                    f"Overlay region '{self.name}' (id={self.region_id}) is compressed; "
                    "linear address translation is not valid for compressed overlays. "
                    "Decompress the overlay first (e.g. via NDSOverlayCompressor.decompress())."
                )
            return None

        delta = rom_off - self.rom_offset
        return self.ram_address + delta


@dataclass
class DMACopyRecord(MioRomResult):
    """Represents a discovered DMA or memcpy routine transferring ROM to RAM."""
    pc_address: int
    source_address: int
    destination_address: int
    word_count: int


class MemoryOverlayMapper:
    """
    Bidirectional RAM <-> ROM address translator and overlay manager.

    Precondition for linear address translation:
        Linear address translation (ram_to_rom and rom_to_ram) is only valid for
        UNCOMPRESSED overlays (flags bit 24 == 0). Compressed overlays cannot be
        mapped linearly and will return None (or raise CompressedOverlayError if
        raise_on_compressed=True).
    """

    def __init__(self):
        self.regions: List[OverlayRegion] = []
        self.region_map: Dict[Union[int, str], OverlayRegion] = {}

    def add_region(self, region: OverlayRegion) -> None:
        """Registers a mapped memory region or overlay."""
        self.regions.append(region)
        self.region_map[region.region_id] = region
        self.region_map[region.name] = region

    def ram_to_rom(
        self,
        ram_address: int,
        preferred_region: Optional[Union[int, str]] = None,
        raise_on_compressed: bool = False,
    ) -> Optional[int]:
        """
        Translates a virtual RAM address to its underlying ROM file offset.
        Precondition: Only valid for uncompressed overlays. Returns None (or raises
        CompressedOverlayError if raise_on_compressed=True) if the address falls within
        a compressed overlay.
        """
        if preferred_region is not None and preferred_region in self.region_map:
            res = self.region_map[preferred_region].ram_to_rom(
                ram_address, raise_on_compressed=raise_on_compressed
            )
            if res is not None:
                return res

        for r in self.regions:
            res = r.ram_to_rom(ram_address, raise_on_compressed=raise_on_compressed)
            if res is not None:
                return res
        return None

    def rom_to_ram(
        self,
        rom_offset: int,
        preferred_region: Optional[Union[int, str]] = None,
        raise_on_compressed: bool = False,
    ) -> Optional[int]:
        """
        Translates a physical ROM offset to its execution RAM address.
        Precondition: Only valid for uncompressed overlays. Returns None (or raises
        CompressedOverlayError if raise_on_compressed=True) if the offset falls within
        a compressed overlay.
        """
        if preferred_region is not None and preferred_region in self.region_map:
            res = self.region_map[preferred_region].rom_to_ram(
                rom_offset, raise_on_compressed=raise_on_compressed
            )
            if res is not None:
                return res

        for r in self.regions:
            res = r.rom_to_ram(rom_offset, raise_on_compressed=raise_on_compressed)
            if res is not None:
                return res
        return None

    @classmethod
    def parse_nds_overlays(
        cls,
        y9_table_bytes: bytes,
        fat_entries: Optional[List[Tuple[int, int]]] = None,
    ) -> "MemoryOverlayMapper":
        """
        Parses Nintendo DS ARM9 overlay table (32 bytes per entry).
        If fat_entries is provided (list of (start, end) offsets), maps each overlay
        to its precise physical ROM file offset.
        """
        mapper = cls()
        entry_size = 32
        count = len(y9_table_bytes) // entry_size

        for i in range(count):
            off = i * entry_size
            (
                ov_id,
                ram_addr,
                ram_sz,
                bss_sz,
                _,
                _,
                file_id,
                flags,
            ) = schema.unpack_from("<8I", y9_table_bytes, off)

            rom_off = 0
            rom_sz = ram_sz
            if fat_entries and file_id < len(fat_entries):
                f_start, f_end = fat_entries[file_id]
                rom_off = f_start
                rom_sz = f_end - f_start

            region = OverlayRegion(
                region_id=ov_id,
                name=f"overlay9_{ov_id:04d}",
                ram_address=ram_addr,
                ram_size=ram_sz,
                rom_offset=rom_off,
                rom_size=rom_sz,
                bss_size=bss_sz,
                flags=flags,
            )
            mapper.add_region(region)

        return mapper

    @classmethod
    def parse_psx_exe(cls, exe_header: bytes) -> "MemoryOverlayMapper":
        """
        Parses standard Sony PlayStation 1 PS-X EXE header (first 2048 bytes).
        Text section starts at ROM offset 0x800 (sector 1).
        """
        mapper = cls()
        if len(exe_header) < 0x800:
            return mapper

        # PS-X EXE header:
        # 0x00: b"PS-X EXE"
        # 0x10: initial PC
        # 0x18: text RAM destination
        # 0x1C: text size in bytes
        if exe_header[:8] == b"PS-X EXE":
            ram_dest = schema.unpack_from("<I", exe_header, 0x18)[0]
            text_size = schema.unpack_from("<I", exe_header, 0x1C)[0]
            region = OverlayRegion(
                region_id="MAIN",
                name="PSX_MAIN_EXE",
                ram_address=ram_dest,
                ram_size=text_size,
                rom_offset=0x800,
                rom_size=text_size,
            )
            mapper.add_region(region)

        return mapper

    @classmethod
    def detect_dma_copies(
        cls,
        code: bytes,
        base_address: int,
    ) -> List[DMACopyRecord]:
        """
        Heuristic scanner for GBA DMA3 transfers (0x040000D4 source, 0x040000D8 dest, 0x040000DC control).
        """
        if len(code) < 12:
            return []

        # Find 32-bit literal references to DMA3SAD (0x040000D4)
        lit_offsets: List[int] = []
        n_words = len(code) // 4
        for i in range(n_words):
            word = schema.unpack_from("<I", code, i * 4)[0]
            if word == 0x040000D4:
                lit_offsets.append(i * 4)

        if not lit_offsets:
            return []

        from miorom.asm.disasm import UniversalDisassembler

        def _parse_ptr(ptr_str: str) -> Optional[Tuple[str, int]]:
            ptr_str = ptr_str.strip()
            if not (ptr_str.startswith("[") and ptr_str.endswith("]")):
                return None
            inner = ptr_str[1:-1].strip()
            parts = [p.strip() for p in inner.split(",")]
            base_reg = parts[0].lower()
            if base_reg == "pc":
                base_reg = "r15"
            offset = 0
            if len(parts) > 1:
                off_str = parts[1].strip()
                if off_str.startswith("#"):
                    off_str = off_str[1:]
                try:
                    offset = int(off_str, 0)
                except ValueError:
                    return None
            return base_reg, offset

        def _trace_register_value(
            instructions: List,
            current_idx: int,
            reg_name: str,
            arch: str,
        ) -> Optional[int]:
            for j in range(current_idx - 1, max(-1, current_idx - 25), -1):
                prev_ins = instructions[j]
                p_mnem = prev_ins.mnemonic.lower()
                p_ops = prev_ins.operands
                if prev_ins.is_return or (prev_ins.is_branch and not prev_ins.is_call and not prev_ins.is_conditional):
                    break

                if p_mnem == "ldr" and len(p_ops) >= 2 and p_ops[0].lower() == reg_name:
                    ptr = _parse_ptr(p_ops[1])
                    if ptr:
                        rb, off = ptr
                        if rb in ("r15", "pc"):
                            if arch == "arm":
                                target = (prev_ins.address + 8 + off) & 0xFFFFFFFF
                            else:
                                target = (((prev_ins.address + 4) & ~2) + off) & 0xFFFFFFFF
                            if base_address <= target <= base_address + len(code) - 4:
                                return schema.unpack_from("<I", code, target - base_address)[0]
                    break

                if p_mnem == "mov" and len(p_ops) >= 2 and p_ops[0].lower() == reg_name:
                    src_op = p_ops[1].strip()
                    if src_op.startswith("#"):
                        try:
                            return int(src_op.lstrip("#"), 0) & 0xFFFFFFFF
                        except ValueError:
                            pass
                    break

                if p_mnem == "mvn" and len(p_ops) >= 2 and p_ops[0].lower() == reg_name:
                    src_op = p_ops[1].strip()
                    if src_op.startswith("#"):
                        try:
                            return (~int(src_op.lstrip("#"), 0)) & 0xFFFFFFFF
                        except ValueError:
                            pass
                    break

            return None

        records: List[DMACopyRecord] = []
        seen: Set[Tuple[int, int, int, int]] = set()

        def _scan_with_arch(arch: str):
            for lit_off in lit_offsets:
                win_start = max(0, (lit_off - 1024) & ~3)
                win_end = min(len(code), (lit_off + 512 + 3) & ~3)
                win_data = code[win_start:win_end]
                win_base = base_address + win_start

                try:
                    instructions = UniversalDisassembler.disassemble(
                        win_data,
                        base_address=win_base,
                        arch=arch,
                    )
                except Exception:
                    continue

                reg_state: Dict[str, int] = {}
                sad_store: Optional[Tuple[int, int, int]] = None
                dad_store: Optional[Tuple[int, int, int]] = None

                for i, ins in enumerate(instructions):
                    mnem = ins.mnemonic.lower()
                    ops = ins.operands

                    if ins.is_return or (ins.is_branch and not ins.is_call and not ins.is_conditional):
                        reg_state.clear()
                        sad_store = None
                        dad_store = None
                        continue

                    if mnem == "ldr" and len(ops) >= 2:
                        dst = ops[0].lower()
                        ptr = _parse_ptr(ops[1])
                        if ptr:
                            rb, off = ptr
                            if rb in ("r15", "pc"):
                                if arch == "arm":
                                    target = (ins.address + 8 + off) & 0xFFFFFFFF
                                else:
                                    target = (((ins.address + 4) & ~2) + off) & 0xFFFFFFFF
                                if base_address <= target <= base_address + len(code) - 4:
                                    reg_state[dst] = schema.unpack_from("<I", code, target - base_address)[0]
                                else:
                                    reg_state.pop(dst, None)
                            elif rb in reg_state:
                                eff = (reg_state[rb] + off) & 0xFFFFFFFF
                                if base_address <= eff <= base_address + len(code) - 4:
                                    reg_state[dst] = schema.unpack_from("<I", code, eff - base_address)[0]
                                else:
                                    reg_state.pop(dst, None)
                            else:
                                reg_state.pop(dst, None)

                    elif mnem == "mov" and len(ops) >= 2:
                        dst = ops[0].lower()
                        src_op = ops[1].strip()
                        if src_op.startswith("#"):
                            try:
                                reg_state[dst] = int(src_op.lstrip("#"), 0) & 0xFFFFFFFF
                            except ValueError:
                                reg_state.pop(dst, None)
                        elif src_op.lower() in reg_state:
                            reg_state[dst] = reg_state[src_op.lower()]
                        else:
                            reg_state.pop(dst, None)

                    elif mnem == "mvn" and len(ops) >= 2:
                        dst = ops[0].lower()
                        src_op = ops[1].strip()
                        if src_op.startswith("#"):
                            try:
                                reg_state[dst] = (~int(src_op.lstrip("#"), 0)) & 0xFFFFFFFF
                            except ValueError:
                                reg_state.pop(dst, None)
                        else:
                            reg_state.pop(dst, None)

                    elif mnem in ("add", "orr", "sub") and len(ops) >= 3:
                        dst = ops[0].lower()
                        r_src = ops[1].lower()
                        op3 = ops[2].strip()
                        if r_src in reg_state and op3.startswith("#"):
                            try:
                                imm = int(op3.lstrip("#"), 0)
                                if mnem == "add":
                                    reg_state[dst] = (reg_state[r_src] + imm) & 0xFFFFFFFF
                                elif mnem == "sub":
                                    reg_state[dst] = (reg_state[r_src] - imm) & 0xFFFFFFFF
                                elif mnem == "orr":
                                    reg_state[dst] = (reg_state[r_src] | imm) & 0xFFFFFFFF
                            except ValueError:
                                reg_state.pop(dst, None)
                        else:
                            reg_state.pop(dst, None)

                    elif mnem in ("str", "strh") and len(ops) >= 2:
                        src_reg = ops[0].lower()
                        ptr = _parse_ptr(ops[1])
                        if ptr:
                            rb, off = ptr
                            target_reg_addr = None
                            if rb in reg_state:
                                target_reg_addr = (reg_state[rb] + off) & 0xFFFFFFFF

                            if target_reg_addr == 0x040000D4:
                                val = reg_state.get(src_reg)
                                if val is None:
                                    val = _trace_register_value(instructions, i, src_reg, arch)
                                if val is not None:
                                    sad_store = (ins.address, val, i)

                            elif target_reg_addr == 0x040000D8:
                                val = reg_state.get(src_reg)
                                if val is None:
                                    val = _trace_register_value(instructions, i, src_reg, arch)
                                if val is not None:
                                    dad_store = (ins.address, val, i)

                            elif target_reg_addr == 0x040000DC:
                                val = reg_state.get(src_reg)
                                if val is None:
                                    val = _trace_register_value(instructions, i, src_reg, arch)
                                if val is not None and sad_store is not None and dad_store is not None:
                                    sad_pc, sad_val, sad_idx = sad_store
                                    _, dad_val, dad_idx = dad_store
                                    if abs(i - sad_idx) <= 15 and abs(i - dad_idx) <= 15:
                                        word_count = val & 0xFFFF
                                        item = (sad_pc, sad_val, dad_val, word_count)
                                        if item not in seen:
                                            seen.add(item)
                                            records.append(DMACopyRecord(
                                                pc_address=sad_pc,
                                                source_address=sad_val,
                                                destination_address=dad_val,
                                                word_count=word_count,
                                            ))
                                        sad_store = None
                                        dad_store = None

        _scan_with_arch("arm")
        if not records:
            _scan_with_arch("thumb")

        return records
