import struct
import pytest
from miorom.link import Elf32File, ElfRelocator, EM_ARM, EM_MIPS


def build_synthetic_elf32(
    machine=EM_ARM,
    endian="<",
    text_data=b"\x00\x00\x00\x00",
    symbols=None,  # list of (name, value, size, info, other, shndx)
    relocations=None,  # list of (offset, rel_type, sym_idx)
):
    """
    Build a minimal valid ELF32 relocatable (.o) file in memory for testing.
    Sections:
    0: SHT_NULL
    1: .text (PROGBITS, ALLOC|EXEC, flags=6)
    2: .shstrtab (STRTAB)
    3: .strtab (STRTAB)
    4: .symtab (SYMTAB)
    5: .rel.text (REL) (optional)
    """
    if symbols is None:
        symbols = []
    if relocations is None:
        relocations = []

    has_rel = len(relocations) > 0

    # Build section names (.shstrtab)
    shstrtab = b"\x00.text\x00.shstrtab\x00.strtab\x00.symtab\x00"
    if has_rel:
        shstrtab += b".rel.text\x00"

    text_shname = 1
    shstrtab_shname = 7
    strtab_shname = 17
    symtab_shname = 25
    rel_shname = 33 if has_rel else 0

    # Build symbol strings (.strtab)
    strtab = b"\x00"
    sym_str_offsets = {}
    for name, _, _, _, _, _ in symbols:
        if name and name not in sym_str_offsets:
            sym_str_offsets[name] = len(strtab)
            strtab += name.encode("ascii") + b"\x00"

    # Build symtab
    # Symbol 0 is always null
    symtab = bytearray(16)
    for name, val, sz, info, other, shndx in symbols:
        st_name = sym_str_offsets.get(name, 0)
        symtab += struct.pack(f"{endian}IIIBBH", st_name, val, sz, info, other, shndx)

    # Build relocations
    rel_data = bytearray()
    for r_offset, rel_type, sym_idx in relocations:
        r_info = (sym_idx << 8) | (rel_type & 0xFF)
        rel_data += struct.pack(f"{endian}II", r_offset, r_info)

    # Layout:
    # 0x00: ELF Header (52 bytes)
    # 0x34: Section Headers
    num_sections = 6 if has_rel else 5
    sh_offset = 52
    sec_headers_len = num_sections * 40
    data_start = sh_offset + sec_headers_len

    text_offset = data_start
    shstrtab_offset = text_offset + len(text_data)
    strtab_offset = shstrtab_offset + len(shstrtab)
    symtab_offset = strtab_offset + len(strtab)
    rel_offset = symtab_offset + len(symtab) if has_rel else 0

    # Header
    ei_data = 1 if endian == "<" else 2
    e_ident = b"\x7fELF\x01" + bytes([ei_data]) + b"\x01" + b"\x00" * 9
    ehdr = e_ident + struct.pack(
        f"{endian}HHIIIIIHHHHHH",
        1,  # ET_REL
        machine,
        1,  # EV_CURRENT
        0,  # e_entry
        0,  # e_phoff
        sh_offset,
        0,  # e_flags
        52,  # e_ehsize
        0,   # e_phentsize
        0,   # e_phnum
        40,  # e_shentsize
        num_sections,
        2,   # e_shstrndx (.shstrtab index)
    )

    # Section headers:
    # (sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info, sh_addralign, sh_entsize)
    shdrs = bytearray()
    # 0: NULL
    shdrs += struct.pack(f"{endian}10I", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    # 1: .text (SHT_PROGBITS = 1, SHF_ALLOC|EXEC = 6)
    shdrs += struct.pack(f"{endian}10I", text_shname, 1, 6, 0, text_offset, len(text_data), 0, 0, 4, 0)
    # 2: .shstrtab (SHT_STRTAB = 3)
    shdrs += struct.pack(f"{endian}10I", shstrtab_shname, 3, 0, 0, shstrtab_offset, len(shstrtab), 0, 0, 1, 0)
    # 3: .strtab (SHT_STRTAB = 3)
    shdrs += struct.pack(f"{endian}10I", strtab_shname, 3, 0, 0, strtab_offset, len(strtab), 0, 0, 1, 0)
    # 4: .symtab (SHT_SYMTAB = 2, link=.strtab(3), info=1, entsize=16)
    shdrs += struct.pack(f"{endian}10I", symtab_shname, 2, 0, 0, symtab_offset, len(symtab), 3, 1, 4, 16)
    # 5: .rel.text (SHT_REL = 9, link=.symtab(4), info=.text(1), entsize=8)
    if has_rel:
        shdrs += struct.pack(f"{endian}10I", rel_shname, 9, 0, 0, rel_offset, len(rel_data), 4, 1, 4, 8)

    full_elf = ehdr + shdrs + text_data + shstrtab + strtab + symtab
    if has_rel:
        full_elf += rel_data

    return bytes(full_elf)


def test_elf32_invalid():
    with pytest.raises(ValueError, match="missing magic"):
        Elf32File(b"INVALID_HEADER_DATA")

    # 64-bit ELF (ei_class = 2)
    fake_64 = b"\x7fELF\x02\x01" + b"\x00" * 46
    with pytest.raises(ValueError, match="Only 32-bit ELF"):
        Elf32File(fake_64)


def test_elf32_parse_sections_and_symbols():
    text = b"\x01\x02\x03\x04"
    symbols = [
        ("my_func", 0x00, 4, 0x12, 0, 1),  # in section 1 (.text)
    ]
    elf_bytes = build_synthetic_elf32(EM_ARM, "<", text, symbols)
    elf = Elf32File(elf_bytes)

    assert ".text" in elf.section_map
    assert elf.section_map[".text"].data == text
    assert "my_func" in elf.symbols
    assert elf.symbols["my_func"].st_value == 0
    assert elf.symbols["my_func"].section_name == ".text"


def test_elf_arm_relocations():
    # .text contains 8 bytes:
    # 0x00: target of ABS32 (offset 0)
    # 0x04: BL instruction 0xEB000000 (R_ARM_CALL) (offset 4)
    text = bytearray(8)
    struct.pack_into("<I", text, 4, 0xEB000000)

    symbols = [
        ("hook_target", 0x00, 0, 0x10, 0, 0),  # Undefined external symbol
    ]
    relocs = [
        (0x00, 2, 1),  # R_ARM_ABS32 on symbol 1 ("hook_target")
        (0x04, 28, 1), # R_ARM_CALL on symbol 1 ("hook_target")
    ]

    elf_bytes = build_synthetic_elf32(EM_ARM, "<", bytes(text), symbols, relocs)
    elf = Elf32File(elf_bytes)
    relocator = ElfRelocator(elf)

    # Relocate to base RAM 0x08001000, hook_target at 0x08002000
    base_ram = 0x08001000
    externs = {"hook_target": 0x08002000}
    linked = relocator.relocate(base_ram, external_symbols=externs)

    # Check ABS32 at offset 0: should be 0x08002000
    abs32_val = struct.unpack_from("<I", linked, 0)[0]
    assert abs32_val == 0x08002000

    # Check ARM CALL at offset 4:
    # Target = 0x08002000, PC = base_ram + 4 + 8 = 0x0800100C
    # Diff = 0x08002000 - 0x0800100C = 0xFF4
    # branch_offset = 0xFF4 >> 2 = 0x3FD
    # Expected instruction = 0xEB0003FD
    call_val = struct.unpack_from("<I", linked, 4)[0]
    assert call_val == 0xEB0003FD


def test_elf_mips_relocations():
    # MIPS Big-Endian test (e.g. PS1 / N64)
    # 12 bytes of code:
    # 0x00: LUI $v0, 0 (R_MIPS_HI16)
    # 0x04: ADDIU $v0, $v0, 0 (R_MIPS_LO16)
    # 0x08: JAL target (R_MIPS_26)
    text = bytearray(12)
    struct.pack_into(">I", text, 0, 0x3C020000)  # lui $v0, 0
    struct.pack_into(">I", text, 4, 0x24420000)  # addiu $v0, $v0, 0
    struct.pack_into(">I", text, 8, 0x0C000000)  # jal 0

    symbols = [
        ("render_frame", 0x00, 0, 0x10, 0, 0),  # Undefined external symbol
    ]
    relocs = [
        (0x00, 5, 1),  # R_MIPS_HI16
        (0x04, 6, 1),  # R_MIPS_LO16
        (0x08, 4, 1),  # R_MIPS_26
    ]

    elf_bytes = build_synthetic_elf32(EM_MIPS, ">", bytes(text), symbols, relocs)
    elf = Elf32File(elf_bytes)
    relocator = ElfRelocator(elf)

    # Address = 0x80108040
    externs = {"render_frame": 0x80108040}
    linked = relocator.relocate(0x80000000, external_symbols=externs)

    lui_val = struct.unpack_from(">I", linked, 0)[0]
    addiu_val = struct.unpack_from(">I", linked, 4)[0]
    jal_val = struct.unpack_from(">I", linked, 8)[0]

    # Target 0x80108040:
    # hi = (0x80108040 + 0x8000) >> 16 = 0x8011
    assert lui_val == (0x3C020000 | 0x8011)
    # lo = 0x80108040 & 0xFFFF = 0x8040 -> signed 16-bit is negative (0x8040 is -32704), so +0x8000 in HI compensates for sign-extension in ADDIU!
    assert addiu_val == (0x24420000 | 0x8040)
    # JAL target >> 2: 0x80108040 >> 2 = 0x20042010
    assert jal_val == (0x0C000000 | 0x00042010)


def test_elf_inject_rom():
    text = b"\x12\x34\x56\x78"
    elf_bytes = build_synthetic_elf32(EM_ARM, "<", text)
    elf = Elf32File(elf_bytes)
    relocator = ElfRelocator(elf)

    rom = bytearray(b"\xFF" * 16)
    bytes_injected = relocator.inject(rom, rom_offset=4, ram_address=0x02000000)

    assert bytes_injected == 4
    assert rom[:4] == b"\xFF\xFF\xFF\xFF"
    assert rom[4:8] == b"\x12\x34\x56\x78"
    assert rom[8:16] == b"\xFF" * 8
