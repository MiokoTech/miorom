"""
miorom.asm.vwf_hook_engine
~~~~~~~~~~~~~~~~~~~~~~~~~~
End-to-End Variable-Width Font (VWF) Hook Engine & Trampoline Synthesizer.

Orchestrates automatic code cave allocation, glyph width table serialization,
architecture-specific width-lookup routine generation, and trampoline hook injection
for fan translation reverse engineering across ARM, Thumb, MIPS, SNES (65816), and NES (6502).
"""

from dataclasses import dataclass, field
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from miorom.asm.codecave import CodeCaveFinder
from miorom.asm.trampoline import HookRecord, TrampolineHook
from miorom.errors import RelocationError, UnsupportedFormatError
from miorom.result import MioRomResult
from miorom.text.vwf import GlyphWidthTable
from miorom.text.vwf_injector import DynamicVWFInjector


@dataclass
class VWFHookConfig(MioRomResult):
    """
    Configuration for deploying a Variable Width Font hook into a ROM image.
    """
    arch: str  # "arm", "thumb", "mips", "snes", "6502"
    hook_rom_offset: int
    hook_ram_addr: int
    original_instr_bytes: bytes
    width_table: Union[GlyphWidthTable, Dict[int, int], bytes]
    cave_rom_offset: Optional[int] = None
    cave_ram_addr: Optional[int] = None
    fallback_width: int = 8
    mode: str = "width_lookup"  # "width_lookup" or "custom_payload"
    custom_payload: Optional[bytes] = None
    endian: str = "<"
    min_char_code: int = 0x20
    char_count: int = 96
    filler_byte: int = 0x00


@dataclass
class VWFDeploymentReport(MioRomResult):
    """
    Comprehensive report of deployed VWF components and memory layout.
    """
    arch: str
    hook_record: HookRecord
    table_rom_offset: int
    table_ram_addr: int
    table_size: int
    routine_rom_offset: int
    routine_ram_addr: int
    routine_size: int
    cave_total_used: int
    verified: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Serializes deployment report to dictionary."""
        return {
            "arch": self.arch,
            "hook_rom_offset": f"0x{self.hook_record.hook_file_offset:X}" if self.hook_record.hook_file_offset is not None else None,
            "hook_ram_addr": f"0x{self.hook_record.hook_ram_addr:X}",
            "hook_size": self.hook_record.hook_size,
            "table_rom_offset": f"0x{self.table_rom_offset:X}",
            "table_ram_addr": f"0x{self.table_ram_addr:X}",
            "table_size": self.table_size,
            "routine_rom_offset": f"0x{self.routine_rom_offset:X}",
            "routine_ram_addr": f"0x{self.routine_ram_addr:X}",
            "routine_size": self.routine_size,
            "cave_total_used": self.cave_total_used,
            "verified": self.verified,
        }


class VWFHookEngine:
    """
    High-level engine for deploying VWF width-lookup tables and trampoline hooks into ROM binaries.
    """

    @classmethod
    def verify_hook_site(
        cls,
        rom_buffer: Union[bytes, bytearray],
        hook_rom_offset: int,
        expected_bytes: bytes,
    ) -> bool:
        """
        Verifies that the ROM buffer at hook_rom_offset matches expected_bytes exactly.
        """
        actual = rom_buffer[hook_rom_offset : hook_rom_offset + len(expected_bytes)]
        return bytes(actual) == expected_bytes

    @classmethod
    def synthesize_width_routine(
        cls,
        arch: str,
        table_vaddr: int,
        fallback_width: int = 8,
        endian: str = "<",
    ) -> bytes:
        """
        Synthesizes architecture-specific machine code for glyph width lookup.
        """
        arch_l = arch.lower()

        # 1. ARM 32-bit (GBA / NDS)
        if arch_l in ("arm", "arm32", "gba_arm", "nds_arm"):
            return DynamicVWFInjector.generate_arm_vwf_hook(
                table_vaddr=table_vaddr,
                fallback_width=fallback_width,
                endian=endian,
            )

        # 2. Thumb 16-bit (GBA / NDS)
        elif arch_l in ("thumb", "arm_thumb", "gba_thumb"):
            # Input: r0 = char code, r1 = cursor_x
            # Output: r1 = cursor_x + width[r0 - 0x20]
            # 0x00: CMP r0, #0x20       (0x2820)
            # 0x02: BLO .fallback       (0xD304 -> +4 halfwords to 0x0E)
            # 0x04: SUB r0, r0, #0x20   (0x3820)
            # 0x06: LDR r2, [PC, #8]    (0x4A02 -> load literal at 0x10)
            # 0x08: LDRB r3, [r2, r0]   (0x5C13)
            # 0x0A: ADD r1, r1, r3      (0x18C9)
            # 0x0C: B .done             (0xE001 -> branch over fallback to 0x10)
            # .fallback (0x0E):
            # 0x0E: ADD r1, #fallback   (0x3100 | fallback_width)
            # .done (0x10):
            # 0x10: table_vaddr (32-bit uint)
            buf = bytearray()
            buf.extend(struct.pack("<H", 0x2820))
            buf.extend(struct.pack("<H", 0xD304))
            buf.extend(struct.pack("<H", 0x3820))
            buf.extend(struct.pack("<H", 0x4A02))
            buf.extend(struct.pack("<H", 0x5C13))
            buf.extend(struct.pack("<H", 0x18C9))
            buf.extend(struct.pack("<H", 0xE001))
            buf.extend(struct.pack("<H", 0x3100 | (fallback_width & 0xFF)))
            buf.extend(struct.pack("<I", table_vaddr))
            return bytes(buf)

        # 3. MIPS 32-bit (PS1 / N64 / PSP)
        elif arch_l in ("mips", "mips_le", "mips_be", "psx", "n64", "psp"):
            return DynamicVWFInjector.generate_mips_vwf_hook(
                table_vaddr=table_vaddr,
                fallback_width=fallback_width,
                endian=endian,
            )

        # 4. SNES / W65C816 16-bit
        elif arch_l in ("snes", "65816", "w65c816"):
            table_bank = (table_vaddr >> 16) & 0xFF
            table_offset = table_vaddr & 0xFFFF
            return DynamicVWFInjector.generate_snes_vwf_hook(
                table_bank=table_bank,
                table_offset=table_offset,
            )

        # 5. MOS 6502 8-bit (NES)
        elif arch_l in ("6502", "nes"):
            # Input: A = char code -> lookup width in table -> A = width
            # SEC (0x38), SBC #$20 (0xE9 0x20), TAX (0xAA), LDA table, X (0xBD lo hi)
            lo = table_vaddr & 0xFF
            hi = (table_vaddr >> 8) & 0xFF
            return bytes([0x38, 0xE9, 0x20, 0xAA, 0xBD, lo, hi])

        else:
            raise UnsupportedFormatError(f"Unsupported architecture for VWF synthesis: '{arch}'.")

    @classmethod
    def deploy(
        cls,
        rom_buffer: bytearray,
        config: VWFHookConfig,
        simulate: bool = False,
    ) -> VWFDeploymentReport:
        """
        Orchestrates full VWF deployment into a ROM buffer:
        1. Validates original instructions at hook site.
        2. Builds and serializes width table binary.
        3. Allocates or validates code cave region.
        4. Synthesizes architecture-specific width lookup machine code.
        5. Generates trampoline hook with displaced instruction execution and clean return.
        6. Atomically patches rom_buffer (unless simulate=True).
        """
        # Step 1: Verify hook site instructions
        if not cls.verify_hook_site(rom_buffer, config.hook_rom_offset, config.original_instr_bytes):
            actual = bytes(rom_buffer[config.hook_rom_offset : config.hook_rom_offset + len(config.original_instr_bytes)])
            raise RelocationError(
                f"Hook site byte mismatch at ROM offset 0x{config.hook_rom_offset:X}: "
                f"expected {config.original_instr_bytes.hex()}, found {actual.hex()}."
            )

        # Step 2: Build width table binary
        if isinstance(config.width_table, bytes):
            table_bytes = config.width_table
        elif isinstance(config.width_table, (GlyphWidthTable, dict)):
            table_bytes = DynamicVWFInjector.build_width_table_binary(
                glyph_widths=config.width_table,
                default_width=config.fallback_width,
                start_char=config.min_char_code,
                count=config.char_count,
            )
        else:
            raise ValueError(f"Unsupported width_table type: {type(config.width_table)}.")

        table_size = len(table_bytes)
        aligned_table_size = (table_size + 3) & ~3

        # Step 3: Determine code cave location
        ram_base_offset = config.hook_ram_addr - config.hook_rom_offset
        est_routine_size = 48
        est_trampoline_size = len(config.original_instr_bytes) + 16
        total_est_needed = aligned_table_size + est_routine_size + est_trampoline_size

        if config.cave_rom_offset is None:
            caves = CodeCaveFinder.find_caves(
                bytes(rom_buffer),
                min_size=total_est_needed,
                filler_byte=config.filler_byte,
                alignment=4,
            )
            if not caves:
                raise RelocationError(
                    f"Could not locate an unused code cave with at least {total_est_needed} bytes."
                )
            cave_rom_offset = caves[0].offset
        else:
            cave_rom_offset = config.cave_rom_offset

        if config.cave_ram_addr is None:
            cave_ram_addr = cave_rom_offset + ram_base_offset
        else:
            cave_ram_addr = config.cave_ram_addr

        # Step 4: Layout inside code cave
        table_rom_offset = cave_rom_offset
        table_ram_addr = cave_ram_addr
        routine_rom_offset = cave_rom_offset + aligned_table_size
        routine_ram_addr = cave_ram_addr + aligned_table_size

        # Step 5: Synthesize lookup routine with accurate table_ram_addr
        if config.custom_payload is not None:
            routine_bytes = config.custom_payload
        else:
            routine_bytes = cls.synthesize_width_routine(
                arch=config.arch,
                table_vaddr=table_ram_addr,
                fallback_width=config.fallback_width,
                endian=config.endian,
            )

        routine_size = len(routine_bytes)

        # Step 6: Generate trampoline hook
        hook_bytes, cave_bytes = TrampolineHook.create_hook(
            arch=config.arch,
            hook_ram_addr=config.hook_ram_addr,
            original_instr_bytes=config.original_instr_bytes,
            custom_payload_bytes=routine_bytes,
            cave_ram_addr=routine_ram_addr,
            endian=config.endian,
        )

        total_cave_used = aligned_table_size + len(cave_bytes)

        # Step 7: Apply patches if not simulate
        if not simulate:
            # Write width table into cave
            rom_buffer[table_rom_offset : table_rom_offset + table_size] = table_bytes
            # Fill alignment padding with filler_byte
            for p in range(table_rom_offset + table_size, routine_rom_offset):
                rom_buffer[p] = config.filler_byte

            # Write routine + trampoline into cave
            rom_buffer[routine_rom_offset : routine_rom_offset + len(cave_bytes)] = cave_bytes

            # Write hook branch at hook site
            rom_buffer[config.hook_rom_offset : config.hook_rom_offset + len(hook_bytes)] = hook_bytes

        record = HookRecord(
            arch=config.arch,
            hook_ram_addr=config.hook_ram_addr,
            cave_ram_addr=routine_ram_addr,
            hook_bytes=hook_bytes,
            cave_bytes=cave_bytes,
            hook_file_offset=config.hook_rom_offset,
            cave_file_offset=routine_rom_offset,
        )

        return VWFDeploymentReport(
            arch=config.arch,
            hook_record=record,
            table_rom_offset=table_rom_offset,
            table_ram_addr=table_ram_addr,
            table_size=table_size,
            routine_rom_offset=routine_rom_offset,
            routine_ram_addr=routine_ram_addr,
            routine_size=routine_size,
            cave_total_used=total_cave_used,
            verified=True,
        )
