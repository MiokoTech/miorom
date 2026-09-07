import pytest
from miorom.core.memory import MemoryMap, MemoryRegion
from miorom.core.signatures import SignaturePattern, SignatureScanner


def test_memory_map_gba():
    m = MemoryMap.gba()
    # File offset 0 -> RAM 0x08000000
    assert m.file_to_ram(0x0) == 0x08000000
    assert m.file_to_ram(0x1234) == 0x08001234
    assert m.ram_to_file(0x08001234) == 0x1234
    assert m.resolve_pointer(0x08005678) == 0x5678
    assert m.make_pointer(0x5678) == 0x08005678


def test_memory_map_snes_lorom():
    m = MemoryMap.snes_lorom()
    # Bank 0 ($80:8000) -> file 0x0
    assert m.ram_to_file(0x808000) == 0x0
    assert m.file_to_ram(0x0) == 0x808000
    # Bank 1 ($81:8000) -> file 0x8000
    assert m.file_to_ram(0x8000) == 0x818000
    assert m.ram_to_file(0x818000) == 0x8000


def test_signature_pattern():
    data = b"\x55\x89\xE5\x83\xEC\x10\x8B\x45\x08\x83\xC0\x01\x5D\xC3\x90\x90\x55\x89\xE5\x83\xEC\x20"
    pattern = "55 89 E5 83 EC ?? 8B"

    # Find first
    idx = SignatureScanner.find(data, pattern)
    assert idx == 0

    # Find all with wildcard
    pat_func = "55 89 E5 83 EC ??"
    matches = SignatureScanner.find_all(data, pat_func)
    assert matches == [0, 16]


def test_signature_half_byte_wildcards():
    data = b"\x12\x34\x56\x78\x9A\xBC"
    # Matches any 0x3_ byte followed by 0x56
    pat = "12 3? 56"
    assert SignatureScanner.find(data, pat) == 0

    pat2 = "78 ?A BC"
    assert SignatureScanner.find(data, pat2) == 3
