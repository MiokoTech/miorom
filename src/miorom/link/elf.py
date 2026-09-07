import struct
from dataclasses import dataclass
from typing import Dict, List, Optional


# Section types
SHT_NULL = 0
SHT_PROGBITS = 1
SHT_SYMTAB = 2
SHT_STRTAB = 3
SHT_RELA = 4
SHT_NOBITS = 8
SHT_REL = 9

# Machine architectures
EM_386 = 3
EM_MIPS = 8
EM_PPC = 20
EM_ARM = 40


@dataclass
class ElfSection:
    name: str
    sh_type: int
    sh_flags: int
    sh_addr: int
    sh_offset: int
    sh_size: int
    sh_link: int
    sh_info: int
    sh_addralign: int
    sh_entsize: int
    data: bytes = b""


@dataclass
class ElfSymbol:
    name: str
    st_value: int
    st_size: int
    st_info: int
    st_other: int
    st_shndx: int
    section_name: Optional[str] = None

    @property
    def is_undefined(self) -> bool:
        return self.st_shndx == 0


@dataclass
class ElfRelocation:
    r_offset: int
    r_info: int
    r_addend: int = 0
    section_name: str = ""
    symbol_name: str = ""
    rel_type: int = 0
    sym_idx: int = 0


class Elf32File:
    """
    Parser for 32-bit Executable and Linkable Format (ELF32) object files (.o / .elf).
    Extracts headers, sections, symbol tables, and relocations for ARM, MIPS, and x86.
    """

    def __init__(self, data: bytes):
        self.raw_data = data
        if len(data) < 52 or data[:4] != b"\x7fELF":
            raise ValueError("Invalid ELF32 file: missing magic header '\\x7fELF'")

        self.ei_class = data[4]  # 1 = 32-bit, 2 = 64-bit
        if self.ei_class != 1:
            raise ValueError("Only 32-bit ELF files (ELF32) are supported.")

        self.ei_data = data[5]   # 1 = Little-endian, 2 = Big-endian
        self.endian = "<" if self.ei_data == 1 else ">"

        (
            self.e_type,
            self.e_machine,
            self.e_version,
            self.e_entry,
            self.e_phoff,
            self.e_shoff,
            self.e_flags,
            self.e_ehsize,
            self.e_phentsize,
            self.e_phnum,
            self.e_shentsize,
            self.e_shnum,
            self.e_shstrndx,
        ) = struct.unpack_from(f"{self.endian}HHIIIIIHHHHHH", data, 16)

        self.sections: List[ElfSection] = []
        self.section_map: Dict[str, ElfSection] = {}
        self.symbols: Dict[str, ElfSymbol] = {}
        self.symbol_list: List[ElfSymbol] = []
        self.relocations: List[ElfRelocation] = []

        self._parse_sections()
        self._parse_symbols()
        self._parse_relocations()

    def _get_string(self, strtab_data: bytes, offset: int) -> str:
        if offset >= len(strtab_data):
            return ""
        end = strtab_data.find(b"\x00", offset)
        if end == -1:
            end = len(strtab_data)
        return strtab_data[offset:end].decode("ascii", errors="replace")

    def _parse_sections(self):
        raw_sh = []
        for i in range(self.e_shnum):
            sh_offset = self.e_shoff + i * self.e_shentsize
            (
                sh_name_idx,
                sh_type,
                sh_flags,
                sh_addr,
                sh_offset_val,
                sh_size,
                sh_link,
                sh_info,
                sh_addralign,
                sh_entsize,
            ) = struct.unpack_from(f"{self.endian}IIIIIIIIII", self.raw_data, sh_offset)

            sec_data = b""
            if sh_type != SHT_NOBITS and sh_offset_val + sh_size <= len(self.raw_data):
                sec_data = self.raw_data[sh_offset_val:sh_offset_val + sh_size]

            raw_sh.append({
                "name_idx": sh_name_idx,
                "type": sh_type,
                "flags": sh_flags,
                "addr": sh_addr,
                "offset": sh_offset_val,
                "size": sh_size,
                "link": sh_link,
                "info": sh_info,
                "align": sh_addralign,
                "entsize": sh_entsize,
                "data": sec_data,
            })

        shstrtab_data = b""
        if self.e_shstrndx < len(raw_sh):
            shstrtab_data = raw_sh[self.e_shstrndx]["data"]

        for s in raw_sh:
            name = self._get_string(shstrtab_data, s["name_idx"])
            sec = ElfSection(
                name=name,
                sh_type=s["type"],
                sh_flags=s["flags"],
                sh_addr=s["addr"],
                sh_offset=s["offset"],
                sh_size=s["size"],
                sh_link=s["link"],
                sh_info=s["info"],
                sh_addralign=s["align"],
                sh_entsize=s["entsize"],
                data=s["data"],
            )
            self.sections.append(sec)
            self.section_map[name] = sec

    def _parse_symbols(self):
        symtab_sec = None
        for sec in self.sections:
            if sec.sh_type == SHT_SYMTAB:
                symtab_sec = sec
                break

        if not symtab_sec:
            return

        strtab_sec = self.sections[symtab_sec.sh_link] if symtab_sec.sh_link < len(self.sections) else None
        strtab_data = strtab_sec.data if strtab_sec else b""

        num_symbols = len(symtab_sec.data) // 16
        for i in range(num_symbols):
            offset = i * 16
            st_name, st_value, st_size, st_info, st_other, st_shndx = struct.unpack_from(
                f"{self.endian}IIIBBH", symtab_sec.data, offset
            )
            name = self._get_string(strtab_data, st_name)
            sec_name = None
            if st_shndx < len(self.sections):
                sec_name = self.sections[st_shndx].name

            sym = ElfSymbol(
                name=name,
                st_value=st_value,
                st_size=st_size,
                st_info=st_info,
                st_other=st_other,
                st_shndx=st_shndx,
                section_name=sec_name,
            )
            self.symbol_list.append(sym)
            if name:
                self.symbols[name] = sym

    def _parse_relocations(self):
        for sec in self.sections:
            if sec.sh_type in (SHT_REL, SHT_RELA):
                target_sec_idx = sec.sh_info
                target_sec_name = (
                    self.sections[target_sec_idx].name
                    if target_sec_idx < len(self.sections)
                    else ""
                )

                is_rela = (sec.sh_type == SHT_RELA)
                ent_size = 12 if is_rela else 8
                count = len(sec.data) // ent_size

                for i in range(count):
                    offset = i * ent_size
                    if is_rela:
                        r_offset, r_info, r_addend = struct.unpack_from(
                            f"{self.endian}III", sec.data, offset
                        )
                    else:
                        r_offset, r_info = struct.unpack_from(
                            f"{self.endian}II", sec.data, offset
                        )
                        r_addend = 0

                    rel_type = r_info & 0xFF
                    sym_idx = r_info >> 8
                    sym_name = (
                        self.symbol_list[sym_idx].name
                        if sym_idx < len(self.symbol_list)
                        else ""
                    )

                    self.relocations.append(
                        ElfRelocation(
                            r_offset=r_offset,
                            r_info=r_info,
                            r_addend=r_addend,
                            section_name=target_sec_name,
                            symbol_name=sym_name,
                            rel_type=rel_type,
                            sym_idx=sym_idx,
                        )
                    )
