import pytest

from miorom.core import schema
from miorom.errors import ParseError
from miorom.link.dol import (
    R_PPC_ADDR16_HA,
    R_PPC_ADDR16_LO,
    R_PPC_ADDR32,
    R_PPC_REL24,
    R_RVL_NONE,
    DolBinary,
    RelFile,
    RelHeader,
    RelocationEntry,
    RelSection,
)


def make_dummy_dol() -> DolBinary:
    """Constructs a minimal valid DolBinary with 1 text and 1 data section."""
    buf = bytearray(0x1000)
    # text 0 offset: 0x100, address: 0x80003000, size: 0x200
    schema.pack_into(">I", buf, 0x00, 0x100)
    schema.pack_into(">I", buf, 0x48, 0x80003000)
    schema.pack_into(">I", buf, 0x90, 0x200)

    # data 0 (section 7) offset: 0x300, address: 0x80008000, size: 0x100
    schema.pack_into(">I", buf, 0x1C, 0x300)
    schema.pack_into(">I", buf, 0x64, 0x80008000)
    schema.pack_into(">I", buf, 0xAC, 0x100)

    # bss address: 0x80009000, size: 0x100, entry: 0x80003000
    schema.pack_into(">III", buf, 0xD8, 0x80009000, 0x100, 0x80003000)
    return DolBinary(buf)


def test_rel_synthetic_roundtrip_fidelity():
    header = RelHeader(
        id=1,
        version=3,
        num_sections=4,
        bss_size=0x40,
        bss_section=3,
        prolog_section=1,
        prolog_offset=0x00,
        epilog_section=1,
        epilog_offset=0x20,
        unresolved_section=1,
        unresolved_offset=0x40,
        align=32,
        bss_align=32,
        fix_size=0,
    )

    # Section 0: Null
    sec0 = RelSection(index=0, is_executable=False, is_bss=False, data=bytearray(), size=0, offset=0)

    # Section 1: Text code (.text)
    text_data = bytearray(0x80)
    # Placeholder branch at 0x20: bl 0 (0x48000001)
    schema.pack_into(">I", text_data, 0x20, 0x48000001)
    sec1 = RelSection(index=1, is_executable=True, is_bss=False, data=text_data, size=len(text_data))

    # Section 2: Data (.rodata)
    data_bytes = bytearray(b"MIO_WII_MESSAGE_DATA\x00" * 4)
    sec2 = RelSection(index=2, is_executable=False, is_bss=False, data=data_bytes, size=len(data_bytes))

    # Section 3: BSS (.bss)
    sec3 = RelSection(index=3, is_executable=False, is_bss=True, data=bytearray(), size=0x40)

    relocations = [
        # In section 1 at offset 0x08: ADDR32 pointing to DOL text 0 (module 0, section 0) + 0x100
        RelocationEntry(section_id=1, offset=0x08, type=R_PPC_ADDR32, target_module_id=0, target_section=0, addend=0x100),
        # In section 1 at offset 0x10: ADDR16_HA pointing to self (module 1) data (section 2) + 0x14
        RelocationEntry(section_id=1, offset=0x10, type=R_PPC_ADDR16_HA, target_module_id=1, target_section=2, addend=0x14),
        # In section 1 at offset 0x14: ADDR16_LO pointing to self (module 1) data (section 2) + 0x14
        RelocationEntry(section_id=1, offset=0x14, type=R_PPC_ADDR16_LO, target_module_id=1, target_section=2, addend=0x14),
        # In section 1 at offset 0x20: REL24 branch to DOL text 0 + 0x40
        RelocationEntry(section_id=1, offset=0x20, type=R_PPC_REL24, target_module_id=0, target_section=0, addend=0x40),
    ]

    rel = RelFile(header=header, sections=[sec0, sec1, sec2, sec3], relocations=relocations, name="actor_test.rel")

    raw_bin = rel.to_bytes()
    assert len(raw_bin) > 0x100
    assert RelFile.is_rel(raw_bin) is True

    # Parse back
    parsed = RelFile.from_bytes(raw_bin)
    assert parsed.header.id == 1
    assert parsed.header.version == 3
    assert parsed.name == "actor_test.rel"
    assert len(parsed.sections) == 4
    assert parsed.sections[0].is_null is True
    assert parsed.sections[1].is_executable is True
    assert parsed.sections[2].is_executable is False
    assert parsed.sections[3].is_bss is True
    assert len(parsed.relocations) == 4

    # Verify second generation byte-for-byte identical
    raw_bin2 = parsed.to_bytes()
    assert raw_bin2 == raw_bin


def test_rel_large_delta_pagination_r_rvl_none():
    header = RelHeader(id=2, version=2, num_sections=2, align=32)
    sec0 = RelSection(index=0, is_executable=False, is_bss=False, data=bytearray(), size=0)

    # Large data section of 160,000 bytes
    big_data = bytearray(160000)
    sec1 = RelSection(index=1, is_executable=False, is_bss=False, data=big_data, size=len(big_data))

    # Two relocations spaced 140,000 bytes apart (delta > 65535)
    relocations = [
        RelocationEntry(section_id=1, offset=100, type=R_PPC_ADDR32, target_module_id=0, target_section=1, addend=0x500),
        RelocationEntry(section_id=1, offset=140100, type=R_PPC_ADDR32, target_module_id=0, target_section=1, addend=0x600),
    ]

    rel = RelFile(header=header, sections=[sec0, sec1], relocations=relocations, name="big_data.rel")
    raw = rel.to_bytes()

    # Verify R_RVL_NONE opcode (201) was emitted inside raw bytes
    # Relocation opcode is second byte of 8-byte entry: [offset:H, type:B, sec:B, addend:I]
    rel_stream = raw[rel.header.rel_offset :]
    types_found = [rel_stream[i + 2] for i in range(0, len(rel_stream) - 8, 8)]
    assert R_RVL_NONE in types_found

    # Decode and verify exact preservation
    parsed = RelFile.from_bytes(raw)
    assert len(parsed.relocations) == 2
    assert parsed.relocations[0].offset == 100
    assert parsed.relocations[1].offset == 140100


def test_rel_analytical_queries():
    header = RelHeader(id=5, version=1, num_sections=3)
    sec0 = RelSection(index=0, is_executable=False, is_bss=False, data=bytearray(), size=0)
    sec1 = RelSection(index=1, is_executable=True, is_bss=False, data=bytearray(0x200), size=0x200)
    sec2 = RelSection(index=2, is_executable=False, is_bss=False, data=bytearray(0x100), size=0x100)

    relocations = [
        RelocationEntry(section_id=1, offset=0x20, type=R_PPC_ADDR32, target_module_id=0, target_section=0, addend=0x80001000),
        RelocationEntry(section_id=1, offset=0x40, type=R_PPC_ADDR32, target_module_id=0, target_section=0, addend=0x80002000),
        RelocationEntry(section_id=1, offset=0x60, type=R_PPC_ADDR32, target_module_id=5, target_section=2, addend=0x50),
        RelocationEntry(section_id=2, offset=0x10, type=R_PPC_ADDR32, target_module_id=0, target_section=7, addend=0x80008100),
    ]

    rel = RelFile(header=header, sections=[sec0, sec1, sec2], relocations=relocations, name="query_test.rel")

    # 1. Filter by section
    sec1_rels = rel.find_relocations(section_id=1)
    assert len(sec1_rels) == 3

    # 2. Filter by range
    range_rels = rel.find_relocations_in_range(section_id=1, start_offset=0x30, end_offset=0x50)
    assert len(range_rels) == 1
    assert range_rels[0].offset == 0x40

    # 3. Find references to symbol
    refs = rel.find_references_to_symbol(target_module_id=0, target_section=0, target_offset=0x80002000)
    assert len(refs) == 1
    assert refs[0].offset == 0x40

    # 4. Summary
    info = rel.summary()
    assert info["module_id"] == 5
    assert info["code_size"] == 0x200
    assert info["data_size"] == 0x100
    assert info["total_relocations"] == 4
    assert info["relocations_by_module"][0] == 3
    assert info["relocations_by_module"][5] == 1


def test_rel_surgical_shift_mutations():
    header = RelHeader(id=1, version=3, num_sections=3)
    sec0 = RelSection(index=0, is_executable=False, is_bss=False, data=bytearray(), size=0)
    sec1 = RelSection(index=1, is_executable=True, is_bss=False, data=bytearray(0x100), size=0x100)
    sec2 = RelSection(index=2, is_executable=False, is_bss=False, data=bytearray(0x100), size=0x100)

    relocations = [
        # Inside section 2, before shift point 0x40
        RelocationEntry(section_id=2, offset=0x20, type=R_PPC_ADDR32, target_module_id=0, target_section=1, addend=0x10),
        # Inside section 2, after shift point 0x40
        RelocationEntry(section_id=2, offset=0x60, type=R_PPC_ADDR32, target_module_id=0, target_section=1, addend=0x20),
        # In section 1, targeting section 2 after 0x40 (addend = 0x80)
        RelocationEntry(section_id=1, offset=0x10, type=R_PPC_ADDR32, target_module_id=1, target_section=2, addend=0x80),
    ]

    rel = RelFile(header=header, sections=[sec0, sec1, sec2], relocations=relocations)

    # Surgically shift section 2 at offset 0x40 by +32 bytes (simulating expanding a text string)
    adjusted_count = rel.shift_relocations(section_id=2, after_offset=0x40, delta=32)
    assert adjusted_count == 2

    # Relocation at 0x20 should remain untouched
    assert rel.relocations[0].offset == 0x20
    # Relocation at 0x60 should shift to 0x80
    assert rel.relocations[1].offset == 0x80
    # Relocation in section 1 targeting section 2 addend 0x80 should shift to 0xA0
    assert rel.relocations[2].addend == 0xA0

    # Add new relocation
    new_rel = RelocationEntry(section_id=1, offset=0x70, type=R_PPC_REL24, target_module_id=0, target_section=0, addend=0)
    rel.add_relocation(new_rel)
    assert len(rel.relocations) == 4

    # Remove relocations in range
    removed = rel.remove_relocations_in_range(section_id=1, start_offset=0x60, end_offset=0x80)
    assert removed == 1
    assert len(rel.relocations) == 3


def test_rel_simulated_resolution_and_dol_link():
    dol = make_dummy_dol()

    header = RelHeader(id=1, version=3, num_sections=2)
    sec0 = RelSection(index=0, is_executable=False, is_bss=False, data=bytearray(), size=0)

    # Section 1 code containing branch placeholder (bl 0) and address placeholder (0)
    code = bytearray(0x40)
    schema.pack_into(">I", code, 0x00, 0x00000000)  # offset 0x00: ADDR32 placeholder
    schema.pack_into(">I", code, 0x04, 0x48000001)  # offset 0x04: bl 0 placeholder
    sec1 = RelSection(index=1, is_executable=True, is_bss=False, data=code, size=len(code))

    relocations = [
        # ADDR32 at 0x00 targeting DOL data section 7 (data 0) + 0x20 (address 0x80008020)
        RelocationEntry(section_id=1, offset=0x00, type=R_PPC_ADDR32, target_module_id=0, target_section=7, addend=0x20),
        # REL24 at 0x04 targeting DOL text section 0 + 0x10 (address 0x80003010)
        RelocationEntry(section_id=1, offset=0x04, type=R_PPC_REL24, target_module_id=0, target_section=0, addend=0x10),
    ]

    rel = RelFile(header=header, sections=[sec0, sec1], relocations=relocations)

    # Link against DOL at simulated REL base 0x80200000
    resolved = rel.link_against_dol(dol, base_address=0x80200000, section_id=1)
    assert len(resolved) == 0x40

    # Check ADDR32: should be 0x80008020
    val_addr32 = schema.unpack_from(">I", resolved, 0x00)[0]
    assert val_addr32 == 0x80008020

    # Check REL24: target is 0x80003010, source is 0x80200004
    # delta = 0x80003010 - 0x80200004
    expected_delta = (0x80003010 - 0x80200004) & 0x03FFFFFC
    inst = schema.unpack_from(">I", resolved, 0x04)[0]
    assert (inst & 0xFC000001) == 0x48000001  # opcode bl preserved
    assert (inst & 0x03FFFFFC) == expected_delta

    # Test reciprocal DOL convenience method
    dol_resolved = dol.resolve_rel(rel, rel_base_address=0x80200000, section_id=1)
    assert dol_resolved == resolved


def test_rel_error_handling():
    with pytest.raises(ParseError):
        RelFile.from_bytes(b"SHORT_DATA")

    # Corrupt section table pointer
    corrupt_hdr = bytearray(0x40)
    schema.pack_into(">12IBBBB3I", corrupt_hdr, 0, 1, 0, 0, 10, 0x100000, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    with pytest.raises(ParseError):
        RelFile.from_bytes(bytes(corrupt_hdr))
