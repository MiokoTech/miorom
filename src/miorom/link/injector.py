from miorom.result import MioRomResult
import json
from miorom.errors import ParseError
import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from miorom.asm.branch import ARMBranch, MIPSBranch, PowerPCBranch, ThumbBranch
from miorom.asm.codecave import CodeCave, CodeCaveFinder
from miorom.asm.trampoline import HookRecord, TrampolineHook
from miorom.link.dol import DolBinary, DolSection
from miorom.link.elf import (
    Elf32File,
    EM_ARM,
    EM_MIPS,
    EM_PPC,
)
from miorom.link.relocator import ElfLinkResult, ElfRelocator


@dataclass
class InjectionReport(MioRomResult):
    """
    Detailed diagnostic report for an ELF payload injection.
    """
    arch: str
    target_type: str  # "dol" or "raw"
    hook_ram_addr: Optional[int]
    hook_file_offset: Optional[int]
    cave_ram_addr: int
    cave_file_offset: int
    payload_size: int
    cave_capacity: Optional[int]
    entry_point_ram: int
    hook_installed: bool
    symbols: Dict[str, int] = field(default_factory=dict)
    unresolved_symbols: List[str] = field(default_factory=list)
    section_offsets: Dict[str, int] = field(default_factory=dict)
    section_sizes: Dict[str, int] = field(default_factory=dict)
    trampoline_record: Optional[HookRecord] = None

    def summary(self) -> str:
        hook_str = (
            f"0x{self.hook_ram_addr:08X} (Offset: 0x{self.hook_file_offset:08X})"
            if self.hook_ram_addr is not None
            else "None (Payload Only)"
        )
        cap_str = f"{self.cave_capacity} bytes" if self.cave_capacity else "Unbounded / Appended"
        unres_str = ", ".join(self.unresolved_symbols) if self.unresolved_symbols else "None (All Resolved)"

        lines = [
            "==================================================",
            "        MioROM ELF C-Code Injection Report        ",
            "==================================================",
            f"  Target Type        : {self.target_type.upper()}",
            f"  Target Arch        : {self.arch.upper()}",
            f"  Hook Site (RAM)    : {hook_str}",
            f"  Code Cave (RAM)    : 0x{self.cave_ram_addr:08X} (Offset: 0x{self.cave_file_offset:08X})",
            f"  Payload Size       : {self.payload_size} bytes (Capacity: {cap_str})",
            f"  Entry Point (RAM)  : 0x{self.entry_point_ram:08X}",
            f"  Hook Installed     : {'YES' if self.hook_installed else 'NO'}",
            f"  Unresolved Symbols : {unres_str}",
            f"  Relocated Sections :",
        ]
        for sname, soff in self.section_offsets.items():
            ssz = self.section_sizes.get(sname, 0)
            lines.append(f"    - {sname:<12} : Offset +0x{soff:04X} ({ssz} bytes)")
        lines.append("==================================================")
        return "\n".join(lines)


class ElfInjector:
    """
    High-level ELF C-Code Linker and Payload Injector.
    Integrates ELF parsing, in-RAM relocation, symbol resolution,
    automatic code cave allocation, and multi-architecture trampoline hooking.
    """

    @classmethod
    def load_symbol_map(cls, source: Union[Dict[str, int], str, Path, bytes]) -> Dict[str, int]:
        """
        Loads external symbol mappings from:
        - Python dict: {"OSReport": 0x80045000}
        - JSON string or file: {"OSReport": "0x80045000"}
        - Dolphin / CodeWarrior .map file
        - GNU nm / .sym file
        - CSV file: symbol_name,address
        """
        if isinstance(source, dict):
            return {str(k): (int(v, 0) if isinstance(v, str) else int(v)) for k, v in source.items()}

        raw_text = ""
        if isinstance(source, (str, Path)):
            p = Path(source)
            if p.exists() and p.is_file():
                raw_text = p.read_text(encoding="utf-8", errors="replace")
            else:
                raw_text = str(source)
        elif isinstance(source, bytes):
            raw_text = source.decode("utf-8", errors="replace")

        # Try JSON first
        trimmed = raw_text.strip()
        if trimmed.startswith("{") and trimmed.endswith("}"):
            try:
                data = json.loads(trimmed)
                if isinstance(data, dict):
                    return {str(k): (int(v, 0) if isinstance(v, str) else int(v)) for k, v in data.items()}
            except Exception:
                pass

        symbols: Dict[str, int] = {}
        for line in raw_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            # CSV format: name,address
            if "," in line:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    try:
                        addr = int(parts[1], 0)
                        symbols[parts[0]] = addr
                        continue
                    except ValueError:
                        pass

            # Dolphin / CodeWarrior map line:
            # 80045000 00000040 80045000 0 OSReport
            # or 80045000: OSReport
            # or 80045000 T OSReport
            match_dolphin = re.match(r"([0-9a-fA-F]{8})\s+[0-9a-fA-F]+\s+[0-9a-fA-F]+\s+\d+\s+(\S+)", line)
            if match_dolphin:
                addr_str, sym_name = match_dolphin.groups()
                symbols[sym_name] = int(addr_str, 16)
                continue

            match_colon = re.match(r"([0-9a-fA-F]{8}):\s*(\S+)", line)
            if match_colon:
                addr_str, sym_name = match_colon.groups()
                symbols[sym_name] = int(addr_str, 16)
                continue

            match_nm = re.match(r"([0-9a-fA-F]{8})\s+[a-zA-Z]\s+(\S+)", line)
            if match_nm:
                addr_str, sym_name = match_nm.groups()
                symbols[sym_name] = int(addr_str, 16)
                continue

            match_simple = re.match(r"([0-9a-fA-F]{8})\s+(\S+)", line)
            if match_simple:
                addr_str, sym_name = match_simple.groups()
                symbols[sym_name] = int(addr_str, 16)
                continue

        return symbols

    @classmethod
    def inject(
        cls,
        target: Union[bytearray, bytes, str, Path],
        elf: Union[Elf32File, bytes, str, Path],
        hook_ram_addr: Optional[int] = None,
        hook_file_offset: Optional[int] = None,
        cave_ram_addr: Optional[int] = None,
        cave_file_offset: Optional[int] = None,
        ram_base: int = 0,
        external_symbols: Optional[Union[Dict[str, int], str, Path]] = None,
        entry_symbol: Optional[str] = None,
        arch: Optional[str] = None,
        hook_mode: str = "trampoline",
        original_instr_bytes: Optional[bytes] = None,
        filler_byte: int = 0x00,
        append_dol_section: bool = True,
        output_file: Optional[Union[str, Path]] = None,
    ) -> Tuple[bytearray, InjectionReport]:
        """
        Links an ELF32 payload and injects it into a target game binary (DOL or raw ROM),
        installing a trampoline hook at hook_ram_addr.
        """
        # 1. Load target binary
        if isinstance(target, (str, Path)):
            target_path = Path(target)
            target_buf = bytearray(target_path.read_bytes())
        elif isinstance(target, bytes):
            target_buf = bytearray(target)
        elif isinstance(target, bytearray):
            target_buf = target
        else:
            raise TypeError(f"Invalid target binary type: {type(target)}")

        # 2. Load ELF file
        if isinstance(elf, Elf32File):
            elf_file = elf
        elif isinstance(elf, (str, Path)):
            elf_file = Elf32File(Path(elf).read_bytes())
        elif isinstance(elf, bytes):
            elf_file = Elf32File(elf)
        else:
            raise TypeError(f"Invalid ELF payload type: {type(elf)}")

        # 3. Detect architecture
        if arch is None:
            if elf_file.e_machine == EM_PPC:
                arch = "ppc"
            elif elf_file.e_machine == EM_ARM:
                arch = "arm"
            elif elf_file.e_machine == EM_MIPS:
                arch = "mips_be" if elf_file.endian == ">" else "mips_le"
            else:
                arch = "arm"
        arch_norm = arch.lower()

        # 4. Check if target is DOL
        is_dol = DolBinary.is_dol(bytes(target_buf))
        dol: Optional[DolBinary] = DolBinary(target_buf) if is_dol else None
        target_type = "dol" if is_dol else "raw"

        # 5. Load external symbols
        externs: Dict[str, int] = {}
        if external_symbols:
            externs = cls.load_symbol_map(external_symbols)

        # 6. Helper for address conversion
        def ram_to_offset(ram: int) -> Optional[int]:
            if dol:
                return dol.ram_to_offset(ram)
            if ram_base != 0:
                return ram - ram_base
            return ram

        def offset_to_ram(off: int) -> int:
            if dol:
                converted = dol.offset_to_ram(off)
                if converted is not None:
                    return converted
            if ram_base != 0:
                return off + ram_base
            return off

        # 7. Resolve hook file offset
        if hook_ram_addr is not None and hook_file_offset is None:
            hook_file_offset = ram_to_offset(hook_ram_addr)
            if hook_file_offset is None:
                raise ParseError(
                    f"Could not translate hook RAM address 0x{hook_ram_addr:08X} to file offset. "
                    "Specify hook_file_offset or ram_base."
                )

        # 8. Hook size requirement
        is_mips = "mips" in arch_norm or arch_norm in ("psx", "n64", "psp")
        is_thumb = "thumb" in arch_norm
        instr_size = 8 if is_mips else (2 if is_thumb else 4)

        if hook_file_offset is not None and original_instr_bytes is None:
            if hook_file_offset + instr_size > len(target_buf):
                raise ParseError(f"Hook file offset 0x{hook_file_offset:08X} is out of bounds.")
            original_instr_bytes = bytes(target_buf[hook_file_offset : hook_file_offset + instr_size])

        # 9. Perform initial link to determine payload size
        dummy_base = cave_ram_addr if cave_ram_addr is not None else 0x80000000
        relocator = ElfRelocator(elf_file)
        probe_link = relocator.link(dummy_base, external_symbols=externs, entry_symbol=entry_symbol)
        raw_payload_len = probe_link.total_size

        # Extra buffer for trampoline return stub if trampoline hook mode is used
        trampoline_extra_size = (instr_size + 8) if (hook_ram_addr is not None and hook_mode == "trampoline") else 0
        total_required_size = raw_payload_len + trampoline_extra_size

        # 10. Locate or allocate code cave
        cave_capacity: Optional[int] = None
        if cave_file_offset is not None:
            if cave_ram_addr is None:
                cave_ram_addr = offset_to_ram(cave_file_offset)
        elif cave_ram_addr is not None:
            cave_file_offset = ram_to_offset(cave_ram_addr)
            if cave_file_offset is None:
                # If DOL and RAM address not in existing sections, add new section
                if dol and append_dol_section:
                    pass  # Handled below
                else:
                    raise ParseError(f"Could not translate cave RAM 0x{cave_ram_addr:08X} to file offset.")

        # If cave is still not located, auto-discover
        if cave_file_offset is None:
            if dol:
                # Try finding cave in existing text sections
                caves = dol.find_caves(min_size=total_required_size, filler_byte=filler_byte)
                if caves:
                    sec, cave = caves[0]
                    cave_file_offset = cave.offset
                    cave_ram_addr = offset_to_ram(cave_file_offset)
                    cave_capacity = cave.size
                elif append_dol_section:
                    # Append new text section
                    if cave_ram_addr is None:
                        # Use high RAM address typical for GC/Wii custom code
                        cave_ram_addr = 0x80500000
                    dummy_payload = b"\x00" * total_required_size
                    new_sec = dol.add_section(dummy_payload, ram_address=cave_ram_addr, is_text=True)
                    cave_file_offset = new_sec.file_offset
                    cave_capacity = new_sec.size
                else:
                    raise RuntimeError(f"No code cave >= {total_required_size} bytes found in DOL.")
            else:
                # Flat binary cave finder
                caves = CodeCaveFinder.find_caves(bytes(target_buf), min_size=total_required_size, filler_byte=filler_byte)
                if not caves:
                    raise RuntimeError(f"No code cave >= {total_required_size} bytes found in target binary.")
                target_cave = caves[0]
                cave_file_offset = target_cave.offset
                cave_ram_addr = offset_to_ram(cave_file_offset)
                cave_capacity = target_cave.size

        # 11. Final link with actual cave RAM address
        link_result = relocator.link(
            base_address=cave_ram_addr,
            external_symbols=externs,
            entry_symbol=entry_symbol,
        )

        final_payload = bytearray(link_result.binary)
        hook_record: Optional[HookRecord] = None

        # 12. Hook installation
        if hook_ram_addr is not None and hook_file_offset is not None:
            entry_point_ram = link_result.entry_point or cave_ram_addr

            if hook_mode == "trampoline":
                # Create trampoline hook: hook_bytes jumps to cave_ram_addr,
                # then cave executes payload + displaced original instruction + return branch
                hook_bytes, cave_bytes = TrampolineHook.create_hook(
                    arch=arch_norm,
                    hook_ram_addr=hook_ram_addr,
                    original_instr_bytes=original_instr_bytes or b"",
                    custom_payload_bytes=bytes(final_payload),
                    cave_ram_addr=cave_ram_addr,
                    endian=elf_file.endian,
                )
                final_payload = bytearray(cave_bytes)
                target_buf[hook_file_offset : hook_file_offset + len(hook_bytes)] = hook_bytes

                hook_record = HookRecord(
                    arch=arch_norm,
                    hook_ram_addr=hook_ram_addr,
                    cave_ram_addr=cave_ram_addr,
                    hook_bytes=hook_bytes,
                    cave_bytes=cave_bytes,
                    hook_file_offset=hook_file_offset,
                    cave_file_offset=cave_file_offset,
                )
            elif hook_mode in ("replace", "call", "branch"):
                # Direct branch or call from hook_ram_addr to entry_point_ram
                is_call = (hook_mode == "call")
                if arch_norm in ("ppc", "powerpc", "wii", "gc"):
                    hook_bytes = PowerPCBranch.encode_b(hook_ram_addr, entry_point_ram, link=is_call)
                elif arch_norm in ("arm", "arm32", "gba", "nds"):
                    hook_bytes = ARMBranch.encode_b(hook_ram_addr, entry_point_ram, link=is_call)
                elif arch_norm == "thumb":
                    hook_bytes = ThumbBranch.encode_b(hook_ram_addr, entry_point_ram)
                elif is_mips:
                    j_instr = MIPSBranch.encode_j(hook_ram_addr, entry_point_ram, link=is_call, endian=elf_file.endian)
                    hook_bytes = j_instr + MIPSBranch.nop(endian=elf_file.endian)
                else:
                    raise ParseError(f"Unsupported arch for branch hook: {arch_norm}")

                target_buf[hook_file_offset : hook_file_offset + len(hook_bytes)] = hook_bytes
                hook_record = HookRecord(
                    arch=arch_norm,
                    hook_ram_addr=hook_ram_addr,
                    cave_ram_addr=cave_ram_addr,
                    hook_bytes=hook_bytes,
                    cave_bytes=bytes(final_payload),
                    hook_file_offset=hook_file_offset,
                    cave_file_offset=cave_file_offset,
                )

        # 13. Write final payload into cave
        end_offset = cave_file_offset + len(final_payload)
        if end_offset > len(target_buf):
            target_buf.extend(b"\x00" * (end_offset - len(target_buf)))
        target_buf[cave_file_offset:end_offset] = final_payload

        # 14. Save output file if requested
        if output_file:
            out_p = Path(output_file)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_bytes(bytes(target_buf))

        report = InjectionReport(
            arch=arch_norm,
            target_type=target_type,
            hook_ram_addr=hook_ram_addr,
            hook_file_offset=hook_file_offset,
            cave_ram_addr=cave_ram_addr,
            cave_file_offset=cave_file_offset,
            payload_size=len(final_payload),
            cave_capacity=cave_capacity,
            entry_point_ram=link_result.entry_point or cave_ram_addr,
            hook_installed=(hook_ram_addr is not None),
            symbols=link_result.symbol_table,
            unresolved_symbols=link_result.unresolved_symbols,
            section_offsets=link_result.section_offsets,
            section_sizes=link_result.section_sizes,
            trampoline_record=hook_record,
        )

        return target_buf, report
