import struct
import pytest
from pathlib import Path
from miorom.link import (
    Elf32File,
    ElfRelocator,
    ElfLinkResult,
    ElfInjector,
    InjectionReport,
    DolBinary,
    DolSection,
    EM_ARM,
    EM_MIPS,
    EM_PPC,
    SHT_NOBITS,
)
from miorom.asm.branch import PowerPCBranch, ARMBranch, MIPSBranch


def build_synthetic_elf32(
    machine=EM_PPC,
    endian=">",
    text_data=b"\x60\x00\x00\x00",
    symbols=None,  # list of (name, value, size, info, other, shndx)
    relocations=None,  # list of (offset, rel_type, sym_idx, addend)
    has_bss=False,
    bss_size=0,
):
    """
    Build a minimal valid ELF32 relocatable (.o) file in memory for testing.
    Sections:
    0: SHT_NULL
    1: .text (PROGBITS, ALLOC|EXEC, flags=6)
    2: .shstrtab (STRTAB)
    3: .strtab (STRTAB)
    4: .symtab (SYMTAB)
    5: .rel.text or .rela.text (RELA if PPC, REL otherwise)
    6: .bss (NOBITS, ALLOC|WRITE, flags=3) (optional)
    """
    if symbols is None:
        symbols = []
    if relocations is None:
        relocations = []

    has_rel = len(relocations) > 0
    is_rela = (machine == EM_PPC)

    # Section names
    shstrtab = b"\x00.text\x00.shstrtab\x00.strtab\x00.symtab\x00"
    rel_sec_name = b".rela.text\x00" if is_rela else b".rel.text\x00"
    if has_rel:
        shstrtab += rel_sec_name
    if has_bss:
        shstrtab += b".bss\x00"

    text_shname = 1
    shstrtab_shname = 7
    strtab_shname = 17
    symtab_shname = 25
    rel_shname = 33 if has_rel else 0
    bss_shname = (33 + len(rel_sec_name)) if (has_bss and has_rel) else (33 if has_bss else 0)

    # Symbol strings
    strtab = b"\x00"
    sym_str_offsets = {}
    for name, _, _, _, _, _ in symbols:
        if name and name not in sym_str_offsets:
            sym_str_offsets[name] = len(strtab)
            strtab += name.encode("ascii") + b"\x00"

    # Symtab
    symtab = bytearray(16)
    for name, val, sz, info, other, shndx in symbols:
        st_name = sym_str_offsets.get(name, 0)
        symtab += struct.pack(f"{endian}IIIBBH", st_name, val, sz, info, other, shndx)

    # Relocations
    rel_data = bytearray()
    for item in relocations:
        if len(item) == 4:
            r_offset, rel_type, sym_idx, r_addend = item
        else:
            r_offset, rel_type, sym_idx = item
            r_addend = 0

        r_info = (sym_idx << 8) | (rel_type & 0xFF)
        if is_rela:
            rel_data += struct.pack(f"{endian}III", r_offset, r_info, r_addend)
        else:
            rel_data += struct.pack(f"{endian}II", r_offset, r_info)

    # Layout
    num_sections = 5
    if has_rel:
        num_sections += 1
    if has_bss:
        num_sections += 1

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
        2,   # e_shstrndx
    )

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
    # 5: relocations (SHT_RELA = 4 or SHT_REL = 9)
    if has_rel:
        sht = 4 if is_rela else 9
        entsz = 12 if is_rela else 8
        shdrs += struct.pack(f"{endian}10I", rel_shname, sht, 0, 0, rel_offset, len(rel_data), 4, 1, 4, entsz)
    # 6: .bss (SHT_NOBITS = 8, SHF_ALLOC|WRITE = 3)
    if has_bss:
        shdrs += struct.pack(f"{endian}10I", bss_shname, 8, 3, 0, 0, bss_size, 0, 0, 4, 0)

    full_elf = ehdr + shdrs + text_data + shstrtab + strtab + symtab
    if has_rel:
        full_elf += rel_data

    return bytes(full_elf)


def test_powerpc_elf_relocations():
    # PowerPC instructions:
    # 0x00: lis r3, 0 (R_PPC_ADDR16_HA)
    # 0x04: addi r3, r3, 0 (R_PPC_ADDR16_LO)
    # 0x08: bl target (R_PPC_REL24)
    # 0x0C: 0x00000000 (R_PPC_ADDR32)
    text = bytearray(16)
    struct.pack_into(">I", text, 0, 0x3C600000)  # lis r3, 0
    struct.pack_into(">I", text, 4, 0x38630000)  # addi r3, r3, 0
    struct.pack_into(">I", text, 8, 0x48000001)  # bl 0 (link=1)
    struct.pack_into(">I", text, 12, 0x00000000) # word

    symbols = [
        ("game_state", 0x00, 0, 0x10, 0, 0),  # Undefined external symbol
        ("OSReport", 0x00, 0, 0x12, 0, 0),    # Undefined external function
    ]
    # Relocations with explicit addends (RELA)
    relocs = [
        (0x00, 6, 1, 0),  # R_PPC_ADDR16_HA on game_state
        (0x04, 4, 1, 0),  # R_PPC_ADDR16_LO on game_state
        (0x08, 10, 2, 0), # R_PPC_REL24 on OSReport
        (0x0C, 1, 1, 0x10), # R_PPC_ADDR32 on game_state + 0x10 addend
    ]

    elf_bytes = build_synthetic_elf32(EM_PPC, ">", bytes(text), symbols, relocs)
    elf = Elf32File(elf_bytes)
    assert elf.e_machine == EM_PPC

    relocator = ElfRelocator(elf)
    base_ram = 0x80001000
    externs = {
        "game_state": 0x80258120,  # Note: low 16 bits is 0x8120 (bit 15 is 1!)
        "OSReport": 0x80045000,
    }

    result = relocator.link(base_ram, external_symbols=externs)
    linked = result.binary

    # Check lis r3:
    # ha = (0x80258120 + 0x8000) >> 16 = 0x8026
    lis_val = struct.unpack_from(">I", linked, 0)[0]
    assert lis_val == (0x3C600000 | 0x8026)

    # Check addi r3:
    # lo = 0x80258120 & 0xFFFF = 0x8120
    addi_val = struct.unpack_from(">I", linked, 4)[0]
    assert addi_val == (0x38630000 | 0x8120)

    # Check bl OSReport:
    # target = 0x80045000, source_pc = 0x80001000 + 8 = 0x80001008
    # diff = 0x80045000 - 0x80001008 = 0x00043FF8
    bl_val = struct.unpack_from(">I", linked, 8)[0]
    dec_target, link, _ = PowerPCBranch.decode_b(0x80001008, struct.pack(">I", bl_val))
    assert dec_target == 0x80045000
    assert link is True

    # Check ADDR32 with addend:
    # 0x80258120 + 0x10 = 0x80258130
    addr32_val = struct.unpack_from(">I", linked, 12)[0]
    assert addr32_val == 0x80258130


def test_elf_bss_section_support():
    text = b"\x38\x60\x00\x01"  # li r3, 1
    symbols = [
        ("payload_main", 0x00, 4, 0x12, 0, 1), # .text
        ("counter_var", 0x00, 4, 0x11, 0, 5),  # in .bss (section 5)
    ]
    elf_bytes = build_synthetic_elf32(
        machine=EM_PPC,
        endian=">",
        text_data=text,
        symbols=symbols,
        has_bss=True,
        bss_size=16,
    )
    elf = Elf32File(elf_bytes)
    assert ".bss" in elf.section_map

    relocator = ElfRelocator(elf)
    res = relocator.link(base_address=0x80100000)

    assert ".bss" in res.section_offsets
    assert res.section_sizes[".bss"] == 16
    assert res.symbol_table["counter_var"] == 0x80100000 + res.section_offsets[".bss"]
    assert res.entry_point == 0x80100000  # payload_main at offset 0
    # Binary should contain text + bss zero bytes
    assert len(res.binary) >= 20


def test_dol_binary_parsing_and_cave():
    # Construct a synthetic GameCube/Wii DOL executable
    # DOL Header: 0x100 bytes
    dol_data = bytearray(0x1000)  # 4096 bytes

    # Text section 0: file offset 0x100, RAM 0x80004000, size 0x400
    struct.pack_into(">I", dol_data, 0x00, 0x100)       # text0 offset
    struct.pack_into(">I", dol_data, 0x48, 0x80004000)  # text0 RAM
    struct.pack_into(">I", dol_data, 0x90, 0x400)       # text0 size

    # Fill text section 0 with NOPs (0x60000000) and a 64-byte padding cave (0x00)
    for i in range(0x100, 0x500, 4):
        struct.pack_into(">I", dol_data, i, 0x60000000)

    cave_offset = 0x200
    dol_data[cave_offset : cave_offset + 64] = b"\x00" * 64

    # Entry point
    struct.pack_into(">I", dol_data, 0xE0, 0x80004000)

    assert DolBinary.is_dol(bytes(dol_data)) is True

    dol = DolBinary(dol_data)
    assert len(dol.text_sections) == 1
    assert dol.text_sections[0].file_offset == 0x100
    assert dol.text_sections[0].ram_address == 0x80004000

    # Test address translation
    # RAM 0x80004050 -> offset 0x100 + 0x50 = 0x150
    assert dol.ram_to_offset(0x80004050) == 0x150
    assert dol.offset_to_ram(0x150) == 0x80004050

    # Test find_caves inside DOL
    caves = dol.find_caves(min_size=32)
    assert len(caves) >= 1
    sec, cave = caves[0]
    assert cave.offset == cave_offset
    assert cave.size >= 64

    # Test add_section to DOL
    new_payload = b"\x7C\x00\x00\x00" * 8  # 32 bytes
    new_ram = 0x80600000
    new_sec = dol.add_section(new_payload, ram_address=new_ram, is_text=True)

    assert new_sec.index == 1
    assert new_sec.ram_address == new_ram
    assert dol.ram_to_offset(new_ram) == new_sec.file_offset
    assert dol.offset_to_ram(new_sec.file_offset) == new_ram


def test_symbol_map_loader(tmp_path):
    # Test dictionary
    d = {"func_a": 0x80001000, "func_b": "0x80002000"}
    syms_d = ElfInjector.load_symbol_map(d)
    assert syms_d["func_a"] == 0x80001000
    assert syms_d["func_b"] == 0x80002000

    # Test Dolphin .map format
    map_content = """
    .text section layout
    80045000 00000040 80045000 0 OSReport
    80006000 00000120 80006000 0 memcpy
    """
    syms_map = ElfInjector.load_symbol_map(map_content)
    assert syms_map["OSReport"] == 0x80045000
    assert syms_map["memcpy"] == 0x80006000

    # Test CSV format file
    csv_file = tmp_path / "symbols.csv"
    csv_file.write_text("player_hp,0x80456780\ngame_mode,0x80456784\n")
    syms_csv = ElfInjector.load_symbol_map(csv_file)
    assert syms_csv["player_hp"] == 0x80456780
    assert syms_csv["game_mode"] == 0x80456784


def test_elf_injector_end_to_end_ppc():
    # Build target binary (raw buffer with code and code cave)
    # File layout:
    # 0x000..0x080: original code (all 0x60 NOPs)
    # 0x080..0x100: code cave (0x00)
    target = bytearray(b"\x60\x00\x00\x00" * 32 + b"\x00" * 128)
    hook_offset = 0x10
    hook_ram = 0x80001010
    orig_instr = b"\x7C\x63\x02\xA6"  # mflr r3
    target[hook_offset : hook_offset + 4] = orig_instr

    # Build ELF payload:
    # li r3, 42
    # bl external_fn
    payload_text = bytearray(8)
    struct.pack_into(">I", payload_text, 0, 0x3860002A)  # li r3, 42
    struct.pack_into(">I", payload_text, 4, 0x48000001)  # bl 0

    symbols = [
        ("my_hook", 0x00, 8, 0x12, 0, 1),
        ("external_fn", 0x00, 0, 0x12, 0, 0),
    ]
    relocs = [
        (0x04, 10, 2, 0),  # R_PPC_REL24 on external_fn
    ]
    elf_bytes = build_synthetic_elf32(EM_PPC, ">", bytes(payload_text), symbols, relocs)

    externs = {"external_fn": 0x80005000}

    patched_buf, report = ElfInjector.inject(
        target=target,
        elf=elf_bytes,
        hook_ram_addr=hook_ram,
        hook_file_offset=hook_offset,
        ram_base=0x80001000,
        external_symbols=externs,
        entry_symbol="my_hook",
        arch="ppc",
    )

    assert report.hook_installed is True
    assert report.hook_ram_addr == hook_ram
    assert report.cave_file_offset == 128  # First code cave
    assert report.unresolved_symbols == []

    # Verify hook site branches to cave
    hook_written = patched_buf[hook_offset : hook_offset + 4]
    target_addr, _, _ = PowerPCBranch.decode_b(hook_ram, hook_written)
    assert target_addr == report.cave_ram_addr

    # Verify cave content
    cave_written = patched_buf[report.cave_file_offset : report.cave_file_offset + report.payload_size]
    # Should start with li r3, 42 (0x3860002A)
    assert cave_written[:4] == b"\x38\x60\x00\x2A"
    # Should contain displaced instruction
    assert orig_instr in cave_written

    # Check summary string
    summary = report.summary()
    assert "MioROM ELF C-Code Injection Report" in summary
    assert "PPC" in summary


def test_elf_injector_dol_binary():
    # Construct DOL with a hook site in Text0 and a code cave
    dol_data = bytearray(0x800)
    struct.pack_into(">I", dol_data, 0x00, 0x100)       # text0 offset
    struct.pack_into(">I", dol_data, 0x48, 0x80003000)  # text0 RAM
    struct.pack_into(">I", dol_data, 0x90, 0x600)       # text0 size
    # Fill text0 with NOPs
    for i in range(0x100, 0x700, 4):
        struct.pack_into(">I", dol_data, i, 0x60000000)

    hook_ram = 0x80003040
    hook_off = 0x140
    orig_instr = b"\x38\x00\x00\x05"  # li r0, 5
    dol_data[hook_off : hook_off + 4] = orig_instr

    # Put a code cave at 0x300
    dol_data[0x300 : 0x380] = b"\x00" * 128

    payload_text = b"\x38\x60\x00\x01"  # li r3, 1
    symbols = [("hook_main", 0x00, 4, 0x12, 0, 1)]
    elf_bytes = build_synthetic_elf32(EM_PPC, ">", payload_text, symbols)

    patched_dol, report = ElfInjector.inject(
        target=dol_data,
        elf=elf_bytes,
        hook_ram_addr=hook_ram,
        entry_symbol="hook_main",
    )

    assert report.target_type == "dol"
    assert report.hook_file_offset == hook_off
    assert report.cave_file_offset == 0x300
    assert report.hook_installed is True


def test_cli_inject_elf(tmp_path):
    from miorom.cli.main import cmd_inject_elf
    import argparse

    # Create target binary
    bin_file = tmp_path / "game.bin"
    bin_data = bytearray(b"\x60\x00\x00\x00" * 32 + b"\x00" * 64)
    orig_instr = b"\x7C\x63\x02\xA6"
    bin_data[0x10 : 0x14] = orig_instr
    bin_file.write_bytes(bytes(bin_data))

    # Create ELF payload
    payload_text = b"\x38\x60\x00\x63"  # li r3, 99
    symbols = [("entry", 0x00, 4, 0x12, 0, 1)]
    elf_bytes = build_synthetic_elf32(EM_PPC, ">", payload_text, symbols)
    elf_file = tmp_path / "payload.o"
    elf_file.write_bytes(elf_bytes)

    out_file = tmp_path / "patched.bin"

    args = argparse.Namespace(
        target_bin=str(bin_file),
        payload_elf=str(elf_file),
        output=str(out_file),
        hook="0x80001010",
        hook_offset="0x10",
        cave=None,
        cave_offset=None,
        base="0x80001000",
        symbols=None,
        entry="entry",
        arch="ppc",
        hook_mode="trampoline",
    )

    cmd_inject_elf(args)
    assert out_file.exists()
    patched = out_file.read_bytes()
    assert len(patched) >= len(bin_data)
    # Hook should be written at 0x10
    assert patched[0x10 : 0x14] != orig_instr
