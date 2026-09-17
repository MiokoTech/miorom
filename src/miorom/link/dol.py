"""
miorom.link.dol
~~~~~~~~~~~~~~~
Nintendo GameCube & Wii Executable (DOL) and Relocatable Module (REL) Engine.
Provides bidirectional address translation, code cave discovery, section injection,
and complete analytical parsing, surgical relocation mutation, and disassembly resolution
for GameCube/Wii dynamic modules (.rel) and main executables (.dol).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from miorom.asm.codecave import CodeCave, CodeCaveFinder
from miorom.core import schema
from miorom.errors import ParseError
from miorom.result import MioRomResult

# ============================================================================
# PowerPC & Nintendo RVL/REL Relocation Constants
# ============================================================================

R_PPC_NONE = 0
R_PPC_ADDR32 = 1
R_PPC_ADDR24 = 2
R_PPC_ADDR16 = 3
R_PPC_ADDR16_LO = 4
R_PPC_ADDR16_HI = 5
R_PPC_ADDR16_HA = 6
R_PPC_ADDR14 = 7
R_PPC_ADDR14_BRTAKEN = 8
R_PPC_ADDR14_BRNTAKEN = 9
R_PPC_REL24 = 10
R_PPC_REL14 = 11

R_RVL_NONE = 201  # Advance offset delta without patching (padding for deltas > 65535)
R_RVL_SECT = 202  # Change current target section
R_RVL_STOP = 203  # Stop processing relocations for current module


# ============================================================================
# DOL (Static Executable) Structures
# ============================================================================

@dataclass
class DolSection(MioRomResult):
    index: int
    is_text: bool
    file_offset: int
    ram_address: int
    size: int

    @property
    def end_ram(self) -> int:
        return self.ram_address + self.size

    @property
    def end_offset(self) -> int:
        return self.file_offset + self.size


class DolBinary:
    """
    Parser and modifier for Nintendo GameCube and Wii DOL executables (.dol).
    Supports:
    - Parsing header with 7 text and 11 data sections.
    - Bidirectional RAM address <-> File offset resolution.
    - Adding new text/data sections (for expanding code space).
    - Scanning existing sections for code caves.
    - Linking and resolving RelFile modules in-memory.
    """

    HEADER_SIZE = 0x100  # 256 bytes

    def __init__(self, data: Union[bytes, bytearray]):
        self.data = bytearray(data)
        self.text_sections: List[DolSection] = []
        self.data_sections: List[DolSection] = []
        self.bss_address: int = 0
        self.bss_size: int = 0
        self.entry_point: int = 0
        self._parse_header()

    @classmethod
    def is_dol(cls, data: bytes) -> bool:
        """Check if data has a valid DOL executable header."""
        if len(data) < cls.HEADER_SIZE:
            return False

        first_text_offset = schema.unpack_from(">I", data, 0)[0]
        first_text_address = schema.unpack_from(">I", data, 0x48)[0]

        is_ram_valid = (
            (0x80000000 <= first_text_address <= 0x81800000)
            or (0x90000000 <= first_text_address <= 0x94000000)
        )
        return first_text_offset == 0x100 and is_ram_valid

    def _parse_header(self):
        text_offsets = schema.unpack_from(">7I", self.data, 0x00)
        data_offsets = schema.unpack_from(">11I", self.data, 0x1C)
        text_addrs = schema.unpack_from(">7I", self.data, 0x48)
        data_addrs = schema.unpack_from(">11I", self.data, 0x64)
        text_sizes = schema.unpack_from(">7I", self.data, 0x90)
        data_sizes = schema.unpack_from(">11I", self.data, 0xAC)

        self.bss_address, self.bss_size, self.entry_point = schema.unpack_from(
            ">III", self.data, 0xD8
        )

        self.text_sections.clear()
        for i in range(7):
            if text_offsets[i] != 0 and text_sizes[i] != 0:
                self.text_sections.append(
                    DolSection(
                        index=i,
                        is_text=True,
                        file_offset=text_offsets[i],
                        ram_address=text_addrs[i],
                        size=text_sizes[i],
                    )
                )

        self.data_sections.clear()
        for i in range(11):
            if data_offsets[i] != 0 and data_sizes[i] != 0:
                self.data_sections.append(
                    DolSection(
                        index=i,
                        is_text=False,
                        file_offset=data_offsets[i],
                        ram_address=data_addrs[i],
                        size=data_sizes[i],
                    )
                )

    def ram_to_offset(self, ram_addr: int) -> Optional[int]:
        """Convert a GameCube/Wii RAM address to its corresponding file offset in the DOL."""
        for sec in self.text_sections + self.data_sections:
            if sec.ram_address <= ram_addr < sec.end_ram:
                return sec.file_offset + (ram_addr - sec.ram_address)
        return None

    def offset_to_ram(self, file_offset: int) -> Optional[int]:
        """Convert a DOL file offset to its corresponding GameCube/Wii RAM address."""
        for sec in self.text_sections + self.data_sections:
            if sec.file_offset <= file_offset < sec.end_offset:
                return sec.ram_address + (file_offset - sec.file_offset)
        return None

    def find_free_section_slot(self, is_text: bool = True) -> Optional[int]:
        """Find an unused section slot index (0..6 for text, 0..10 for data)."""
        used_indices = {s.index for s in (self.text_sections if is_text else self.data_sections)}
        max_slots = 7 if is_text else 11
        for idx in range(max_slots):
            if idx not in used_indices:
                return idx
        return None

    def add_section(
        self,
        payload: bytes,
        ram_address: int,
        is_text: bool = True,
        alignment: int = 32,
    ) -> DolSection:
        """
        Appends a new section containing payload to the DOL, updates the header,
        and returns the created DolSection.
        """
        slot = self.find_free_section_slot(is_text=is_text)
        if slot is None:
            raise RuntimeError(
                f"No free {'text' if is_text else 'data'} section slots in DOL header."
            )

        current_len = len(self.data)
        rem = current_len % alignment
        if rem != 0:
            pad = alignment - rem
            self.data.extend(b"\x00" * pad)
            current_len += pad

        file_offset = current_len
        self.data.extend(payload)
        size = len(payload)

        rem = size % alignment
        if rem != 0:
            pad = alignment - rem
            self.data.extend(b"\x00" * pad)
            size += pad

        if is_text:
            schema.pack_into(">I", self.data, 0x00 + slot * 4, file_offset)
            schema.pack_into(">I", self.data, 0x48 + slot * 4, ram_address)
            schema.pack_into(">I", self.data, 0x90 + slot * 4, size)
        else:
            schema.pack_into(">I", self.data, 0x1C + slot * 4, file_offset)
            schema.pack_into(">I", self.data, 0x64 + slot * 4, ram_address)
            schema.pack_into(">I", self.data, 0xAC + slot * 4, size)

        new_sec = DolSection(
            index=slot,
            is_text=is_text,
            file_offset=file_offset,
            ram_address=ram_address,
            size=size,
        )
        if is_text:
            self.text_sections.append(new_sec)
        else:
            self.data_sections.append(new_sec)

        return new_sec

    def find_caves(
        self,
        min_size: int = 16,
        filler_byte: int = 0x00,
        alignment: int = 4,
    ) -> List[Tuple[DolSection, CodeCave]]:
        """
        Scan all text sections in the DOL for code caves.
        Returns a list of tuples (DolSection, CodeCave).
        """
        results: List[Tuple[DolSection, CodeCave]] = []
        for sec in self.text_sections:
            sec_bytes = bytes(self.data[sec.file_offset : sec.end_offset])
            caves = CodeCaveFinder.find_caves(
                sec_bytes, min_size=min_size, filler_byte=filler_byte, alignment=alignment
            )
            for c in caves:
                cave_abs = CodeCave(
                    offset=sec.file_offset + c.offset,
                    size=c.size,
                    filler_byte=c.filler_byte,
                )
                results.append((sec, cave_abs))
        return results

    def resolve_rel(self, rel: RelFile, rel_base_address: int, section_id: int = 1) -> bytes:
        """
        Convenience method: simulates linking a RelFile against this DOL executable
        at rel_base_address and returns the resolved bytes of the specified REL section.
        """
        return rel.link_against_dol(self, base_address=rel_base_address, section_id=section_id)


# ============================================================================
# REL (Relocatable Module) Structures
# ============================================================================

@dataclass
class RelHeader(MioRomResult):
    """
    Fixed header structure for Nintendo GameCube and Wii REL modules.
    Supports format versions 1, 2, and 3.
    """
    id: int = 0
    prev: int = 0
    next: int = 0
    num_sections: int = 0
    section_info_offset: int = 0
    name_offset: int = 0
    name_size: int = 0
    version: int = 3
    bss_size: int = 0
    rel_offset: int = 0
    imp_offset: int = 0
    imp_size: int = 0
    prolog_section: int = 0
    epilog_section: int = 0
    unresolved_section: int = 0
    bss_section: int = 0
    prolog_offset: int = 0
    epilog_offset: int = 0
    unresolved_offset: int = 0
    align: int = 32
    bss_align: int = 32
    fix_size: int = 0


@dataclass
class RelSection(MioRomResult):
    """
    Represents an individual code, data, or BSS section in a REL module.
    Section index 0 is always reserved/null in Nintendo's REL specification.
    """
    index: int
    is_executable: bool
    is_bss: bool
    data: bytearray
    size: int
    offset: int = 0

    @property
    def is_null(self) -> bool:
        """Returns True if this is an unused or null section (such as section 0)."""
        return self.offset == 0 and self.size == 0


@dataclass
class RelocationEntry(MioRomResult):
    """
    Canonical in-memory representation of a single PowerPC relocation point.
    """
    section_id: int
    offset: int
    type: int
    target_module_id: int
    target_section: int
    addend: int


class RelFile:
    """
    Parser, serializer, analytical inspector, and surgical patcher
    for Nintendo GameCube & Wii Relocatable Modules (.rel).
    """

    def __init__(
        self,
        header: RelHeader,
        sections: List[RelSection],
        relocations: List[RelocationEntry],
        name: str = "",
    ):
        self.header = header
        self.sections = sections
        self.relocations = relocations
        self.name = name

    @classmethod
    def is_rel(cls, data: bytes) -> bool:
        """Basic sanity check if binary data appears to be a Nintendo REL module."""
        if len(data) < 0x40:
            return False
        num_sections = schema.unpack_from(">I", data, 0x0C)[0]
        sec_info_offset = schema.unpack_from(">I", data, 0x10)[0]
        version = schema.unpack_from(">I", data, 0x1C)[0]
        return 1 <= version <= 3 and sec_info_offset >= 0x40 and num_sections < 1024

    @classmethod
    def from_bytes(cls, data: Union[bytes, bytearray]) -> RelFile:
        """
        Parses a Nintendo GameCube/Wii REL binary into a structured RelFile.
        Decodes section table, import table, and variable-length delta relocation stream.
        """
        if len(data) < 0x40:
            raise ParseError("Data too small to be a valid REL module (minimum 64 bytes)")

        raw = memoryview(data)

        # Unpack Version 1 base header (64 bytes)
        (
            mod_id,
            prev,
            nxt,
            num_sections,
            sec_info_off,
            name_off,
            name_sz,
            version,
            bss_sz,
            rel_off,
            imp_off,
            imp_sz,
            prolog_sec,
            epilog_sec,
            unres_sec,
            bss_sec,
            prolog_off,
            epilog_off,
            unres_off,
        ) = schema.unpack_from(">12IBBBB3I", raw, 0)

        align = 32
        bss_align = 32
        fix_sz = 0

        if version >= 2 and len(data) >= 0x48:
            align, bss_align = schema.unpack_from(">II", raw, 0x40)
        if version >= 3 and len(data) >= 0x4C:
            fix_sz = schema.unpack_from(">I", raw, 0x48)[0]

        header = RelHeader(
            id=mod_id,
            prev=prev,
            next=nxt,
            num_sections=num_sections,
            section_info_offset=sec_info_off,
            name_offset=name_off,
            name_size=name_sz,
            version=version,
            bss_size=bss_sz,
            rel_offset=rel_off,
            imp_offset=imp_off,
            imp_size=imp_sz,
            prolog_section=prolog_sec,
            epilog_section=epilog_sec,
            unresolved_section=unres_sec,
            bss_section=bss_sec,
            prolog_offset=prolog_off,
            epilog_offset=epilog_off,
            unresolved_offset=unres_off,
            align=align,
            bss_align=bss_align,
            fix_size=fix_sz,
        )

        # Parse Section Info Table
        sections: List[RelSection] = []
        for i in range(num_sections):
            entry_pos = sec_info_off + (i * 8)
            if entry_pos + 8 > len(data):
                raise ParseError(f"Corrupt section info table at section {i}")
            off_flags, sz = schema.unpack_from(">II", raw, entry_pos)
            is_exec = (off_flags & 1) != 0
            file_off = off_flags & ~1
            is_bss = (file_off == 0 and sz > 0)

            if file_off > 0 and sz > 0:
                if file_off + sz > len(data):
                    raise ParseError(f"Section {i} payload exceeds file length")
                sec_data = bytearray(data[file_off : file_off + sz])
            else:
                sec_data = bytearray()

            sections.append(
                RelSection(
                    index=i,
                    is_executable=is_exec,
                    is_bss=is_bss,
                    data=sec_data,
                    size=sz,
                    offset=file_off,
                )
            )

        # Parse Import Table & Relocation Stream
        num_imports = imp_sz // 8
        relocations: List[RelocationEntry] = []

        for i in range(num_imports):
            imp_pos = imp_off + (i * 8)
            if imp_pos + 8 > len(data):
                break
            target_mod_id, r_off = schema.unpack_from(">II", raw, imp_pos)

            curr_section = 0
            curr_offset = 0
            pos = r_off

            while pos + 8 <= len(data):
                delta, r_type, r_sec, r_addend = schema.unpack_from(">HBB I", raw, pos)
                pos += 8

                if r_type == R_RVL_STOP:
                    break
                elif r_type == R_RVL_SECT:
                    curr_section = r_sec
                    curr_offset = 0
                elif r_type == R_RVL_NONE:
                    curr_offset += delta
                else:
                    curr_offset += delta
                    relocations.append(
                        RelocationEntry(
                            section_id=curr_section,
                            offset=curr_offset,
                            type=r_type,
                            target_module_id=target_mod_id,
                            target_section=r_sec,
                            addend=r_addend,
                        )
                    )

        # Extract Module Name if present
        mod_name = ""
        if name_off > 0 and name_sz > 0 and name_off + name_sz <= len(data):
            mod_name = data[name_off : name_off + name_sz].rstrip(b"\x00").decode("utf-8", errors="replace")

        return cls(header=header, sections=sections, relocations=relocations, name=mod_name)

    def to_bytes(self, alignment: int = 32) -> bytes:
        """
        Serializes the RelFile into binary format matching Nintendo's specifications.
        Encodes relocation entries into standard delta-compressed bytecode with automatic
        R_RVL_NONE pagination when delta > 65535.
        """
        hdr = self.header
        v = hdr.version
        hdr_size = 0x4C if v >= 3 else (0x48 if v == 2 else 0x40)

        out = bytearray()
        # Reserve header space
        out.extend(b"\x00" * hdr_size)

        # Reserve Section Info Table space
        sec_info_offset = len(out)
        num_sections = len(self.sections)
        out.extend(b"\x00" * (num_sections * 8))

        # Write Section Data
        section_placements: List[Tuple[int, int, bool]] = []
        for sec in self.sections:
            if sec.index == 0 or sec.is_bss or len(sec.data) == 0:
                section_placements.append((0, sec.size, sec.is_executable))
            else:
                align_req = alignment if sec.is_executable else 4
                rem = len(out) % align_req
                if rem != 0:
                    out.extend(b"\x00" * (align_req - rem))

                file_off = len(out)
                out.extend(sec.data)
                section_placements.append((file_off, len(sec.data), sec.is_executable))

        # Align before relocation stream
        rem = len(out) % 4
        if rem != 0:
            out.extend(b"\x00" * (4 - rem))

        # Group relocations by target_module_id
        module_groups: Dict[int, List[RelocationEntry]] = {}
        for r in self.relocations:
            module_groups.setdefault(r.target_module_id, []).append(r)

        # Sort module IDs deterministically (self module first if present, then DOL=0, then others)
        sorted_mods = sorted(
            module_groups.keys(),
            key=lambda m: (0 if m == hdr.id else (1 if m == 0 else 2), m),
        )

        rel_start_offset = len(out)
        import_entries: List[Tuple[int, int]] = []

        for mod_id in sorted_mods:
            mod_rel_offset = len(out)
            import_entries.append((mod_id, mod_rel_offset))
            rel_list = module_groups[mod_id]

            # Group relocations for this module by section_id
            sec_groups: Dict[int, List[RelocationEntry]] = {}
            for r in rel_list:
                sec_groups.setdefault(r.section_id, []).append(r)

            for sec_id in sorted(sec_groups.keys()):
                sec_rels = sorted(sec_groups[sec_id], key=lambda r: r.offset)
                # Emit R_RVL_SECT (202)
                out.extend(schema.pack(">HBBI", 0, R_RVL_SECT, sec_id, 0))
                prev_off = 0

                for r in sec_rels:
                    delta = r.offset - prev_off
                    # Handle large offset gap (> 65535) via R_RVL_NONE (201)
                    while delta > 65535:
                        out.extend(schema.pack(">HBBI", 65535, R_RVL_NONE, 0, 0))
                        delta -= 65535

                    out.extend(schema.pack(">HBBI", delta, r.type, r.target_section, r.addend))
                    prev_off = r.offset

            # Emit R_RVL_STOP (203) for this module
            out.extend(schema.pack(">HBBI", 0, R_RVL_STOP, 0, 0))

        # Write Import Table
        rem = len(out) % 4
        if rem != 0:
            out.extend(b"\x00" * (4 - rem))
        imp_offset = len(out)
        imp_size = len(import_entries) * 8

        for mod_id, r_off in import_entries:
            out.extend(schema.pack(">II", mod_id, r_off))

        # Optional Module Name
        name_offset = 0
        name_size = 0
        if self.name:
            rem = len(out) % 4
            if rem != 0:
                out.extend(b"\x00" * (4 - rem))
            name_offset = len(out)
            name_bytes = self.name.encode("utf-8") + b"\x00"
            out.extend(name_bytes)
            name_size = len(name_bytes)

        # Write Section Info Table
        for idx, (f_off, sz, is_exec) in enumerate(section_placements):
            flag_bit = 1 if is_exec else 0
            off_and_flags = (f_off & ~1) | flag_bit
            schema.pack_into(">II", out, sec_info_offset + (idx * 8), off_and_flags, sz)

        # Finalize Header
        header_data = schema.pack(
            ">12IBBBB3I",
            hdr.id,
            hdr.prev,
            hdr.next,
            num_sections,
            sec_info_offset,
            name_offset,
            name_size,
            v,
            hdr.bss_size,
            rel_start_offset,
            imp_offset,
            imp_size,
            hdr.prolog_section,
            hdr.epilog_section,
            hdr.unresolved_section,
            hdr.bss_section,
            hdr.prolog_offset,
            hdr.epilog_offset,
            hdr.unresolved_offset,
        )
        out[0:64] = header_data

        if v >= 2:
            schema.pack_into(">II", out, 0x40, hdr.align, hdr.bss_align)
        if v >= 3:
            schema.pack_into(">I", out, 0x48, hdr.fix_size)

        return bytes(out)

    # ========================================================================
    # Analytical Queries (Inspection & Tracing)
    # ========================================================================

    def get_section(self, index: int) -> Optional[RelSection]:
        """Returns the section at index or None if out of range."""
        if 0 <= index < len(self.sections):
            return self.sections[index]
        return None

    def find_relocations(
        self,
        section_id: Optional[int] = None,
        target_module_id: Optional[int] = None,
        target_section: Optional[int] = None,
    ) -> List[RelocationEntry]:
        """Filters relocation entries by local section, target module, or target section."""
        results: List[RelocationEntry] = []
        for r in self.relocations:
            if section_id is not None and r.section_id != section_id:
                continue
            if target_module_id is not None and r.target_module_id != target_module_id:
                continue
            if target_section is not None and r.target_section != target_section:
                continue
            results.append(r)
        return results

    def find_relocations_in_range(
        self,
        section_id: int,
        start_offset: int,
        end_offset: int,
    ) -> List[RelocationEntry]:
        """Finds all relocations applied within a specific byte range in section_id."""
        return [
            r for r in self.relocations
            if r.section_id == section_id and start_offset <= r.offset < end_offset
        ]

    def find_references_to_symbol(
        self,
        target_module_id: int,
        target_section: int,
        target_offset: int,
        tolerance: int = 0,
    ) -> List[RelocationEntry]:
        """
        Traces relocations that reference a specific symbol address (module, section, offset).
        Useful for tracking which functions call a specific runtime function or string.
        """
        return [
            r for r in self.relocations
            if r.target_module_id == target_module_id
            and r.target_section == target_section
            and abs(r.addend - target_offset) <= tolerance
        ]

    def summary(self) -> Dict[str, Any]:
        """Returns a comprehensive diagnostic summary of the REL module."""
        exec_sections = [s for s in self.sections if s.is_executable]
        data_sections = [s for s in self.sections if not s.is_executable and not s.is_bss and s.index > 0]
        total_code = sum(len(s.data) for s in exec_sections)
        total_data = sum(len(s.data) for s in data_sections)

        mod_counts: Dict[int, int] = {}
        for r in self.relocations:
            mod_counts[r.target_module_id] = mod_counts.get(r.target_module_id, 0) + 1

        return {
            "module_id": self.header.id,
            "name": self.name,
            "version": self.header.version,
            "num_sections": len(self.sections),
            "code_size": total_code,
            "data_size": total_data,
            "bss_size": self.header.bss_size,
            "total_relocations": len(self.relocations),
            "relocations_by_module": mod_counts,
            "prolog": f"sec {self.header.prolog_section} + 0x{self.header.prolog_offset:X}",
            "epilog": f"sec {self.header.epilog_section} + 0x{self.header.epilog_offset:X}",
        }

    # ========================================================================
    # Surgical Mutations (String Expansion & Code Injections)
    # ========================================================================

    def shift_relocations(self, section_id: int, after_offset: int, delta: int) -> int:
        """
        Surgically shifts relocation offsets and addends when text or data is inserted.
        - Relocations inside section_id with offset > after_offset have their offset += delta.
        - Relocations pointing to (self.id, section_id) with addend > after_offset have addend += delta.
        Returns the total number of adjusted relocations.
        """
        adjusted = 0
        my_id = self.header.id

        for r in self.relocations:
            # Shift local application offset
            if r.section_id == section_id and r.offset > after_offset:
                r.offset += delta
                adjusted += 1

            # Shift target symbol addend
            if r.target_module_id == my_id and r.target_section == section_id and r.addend > after_offset:
                r.addend += delta
                adjusted += 1

        return adjusted

    def add_relocation(self, entry: RelocationEntry) -> None:
        """Adds a single relocation entry."""
        self.relocations.append(entry)

    def remove_relocations_in_range(
        self,
        section_id: int,
        start_offset: int,
        end_offset: int,
    ) -> int:
        """Removes relocations applied inside the specified range. Returns number removed."""
        initial_len = len(self.relocations)
        self.relocations = [
            r for r in self.relocations
            if not (r.section_id == section_id and start_offset <= r.offset < end_offset)
        ]
        return initial_len - len(self.relocations)

    # ========================================================================
    # Simulated Relocation Resolution (Disassembly & Emulation Helper)
    # ========================================================================

    def simulate_resolve_section(
        self,
        section_id: int,
        target_mappings: Dict[Tuple[int, int], int],
        base_address: int = 0,
    ) -> bytes:
        """
        Simulates PowerPC relocation resolution on a copy of section_id's data.
        Does NOT alter the internal section data or relocations.

        Parameters
        ----------
        section_id : int
            Section to resolve.
        target_mappings : Dict[Tuple[int, int], int]
            Mapping of (module_id, section_id) -> simulated_base_ram_address.
        base_address : int
            Simulated RAM address of this section (used for R_PPC_REL24 / R_PPC_REL14).
        """
        sec = self.get_section(section_id)
        if not sec or not sec.data:
            return b""

        resolved = bytearray(sec.data)
        sec_rels = [r for r in self.relocations if r.section_id == section_id]

        for rel in sec_rels:
            if rel.offset + 4 > len(resolved):
                continue

            target_base = target_mappings.get((rel.target_module_id, rel.target_section), 0)
            target_symbol = target_base + rel.addend
            src_addr = base_address + rel.offset

            if rel.type == R_PPC_ADDR32:
                schema.pack_into(">I", resolved, rel.offset, target_symbol & 0xFFFFFFFF)
            elif rel.type == R_PPC_ADDR16_LO:
                schema.pack_into(">H", resolved, rel.offset, target_symbol & 0xFFFF)
            elif rel.type == R_PPC_ADDR16_HI:
                schema.pack_into(">H", resolved, rel.offset, (target_symbol >> 16) & 0xFFFF)
            elif rel.type == R_PPC_ADDR16_HA:
                hi = (target_symbol >> 16) & 0xFFFF
                if target_symbol & 0x8000:
                    hi = (hi + 1) & 0xFFFF
                schema.pack_into(">H", resolved, rel.offset, hi)
            elif rel.type == R_PPC_REL24:
                delta = target_symbol - src_addr
                inst = schema.unpack_from(">I", resolved, rel.offset)[0]
                inst = (inst & ~0x03FFFFFC) | (delta & 0x03FFFFFC)
                schema.pack_into(">I", resolved, rel.offset, inst)
            elif rel.type == R_PPC_REL14:
                delta = target_symbol - src_addr
                inst = schema.unpack_from(">I", resolved, rel.offset)[0]
                inst = (inst & ~0x0000FFFC) | (delta & 0x0000FFFC)
                schema.pack_into(">I", resolved, rel.offset, inst)

        return bytes(resolved)

    def link_against_dol(
        self,
        dol: DolBinary,
        base_address: int = 0,
        section_id: int = 1,
    ) -> bytes:
        """
        Resolves relocations against a DolBinary executable.
        Module ID 0 sections 0..6 map to DOL text sections 0..6.
        Module ID 0 sections 7..17 map to DOL data sections 0..10.
        """
        target_mappings: Dict[Tuple[int, int], int] = {}

        # Map DOL text sections
        for s in dol.text_sections:
            target_mappings[(0, s.index)] = s.ram_address

        # Map DOL data sections (offset by 7)
        for s in dol.data_sections:
            target_mappings[(0, 7 + s.index)] = s.ram_address

        # Map local REL sections starting at base_address
        curr_addr = base_address
        for s in self.sections:
            target_mappings[(self.header.id, s.index)] = curr_addr
            curr_addr += s.size

        return self.simulate_resolve_section(
            section_id=section_id,
            target_mappings=target_mappings,
            base_address=target_mappings.get((self.header.id, section_id), base_address),
        )
