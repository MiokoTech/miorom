import struct
from miorom.platforms.md import (
    MDHeader,
    MDRom,
    calculate_md_checksum,
    deinterleave_smd,
    fix_md_checksum,
    interleave_smd,
    is_smd,
    verify_md_checksum,
)


def test_md_header_and_checksum():
    # Construct a minimal Mega Drive ROM
    # 0x0000..0x0100: Vector table
    # 0x0100..0x0200: Header
    # 0x0200..0x0400: Program code
    rom_data = bytearray(0x0400)

    # Fill vector table
    struct.pack_into(">II", rom_data, 0, 0x00FFFE00, 0x00000200)

    # Build Header at 0x0100
    hdr = MDHeader(
        system_type="SEGA MEGA DRIVE",
        copyright="(C)SEGA 1991.MAY",
        domestic_title="SONIC THE HEDGEHOG",
        overseas_title="SONIC THE HEDGEHOG",
        serial_number="GM MK-1008 -00",
        checksum=0,
        io_support="J",
        rom_start=0x00000000,
        rom_end=0x0007FFFF,
        ram_start=0x00FF0000,
        ram_end=0x00FFFFFF,
        sram_support=False,
        region="JUE",
    )
    rom_data[0x0100:0x0200] = hdr.pack()

    # Fill some dummy program code
    rom_data[0x0200:0x0204] = b"\x4E\x71\x4E\x75"  # NOP; RTS

    # Calculate checksum
    expected_sum = calculate_md_checksum(bytes(rom_data))
    assert expected_sum > 0

    # Fix checksum
    fixed_rom = fix_md_checksum(bytes(rom_data))
    assert verify_md_checksum(fixed_rom) is True

    # Test MDRom wrapper
    rom = MDRom(fixed_rom)
    assert rom.header.system_type == "SEGA MEGA DRIVE"
    assert rom.header.overseas_title == "SONIC THE HEDGEHOG"
    assert rom.verify_checksum() is True

    # Recalculate after mutation
    rom.data[0x0200] = 0x12
    assert rom.verify_checksum() is False
    rom.recalculate_checksum()
    assert rom.verify_checksum() is True


def test_smd_interleaving_and_deinterleaving():
    # 16KB of flat test data
    flat_data = bytes(i % 256 for i in range(16384))

    # Interleave to SMD
    smd_data = interleave_smd(flat_data)
    assert len(smd_data) == 512 + 16384
    assert is_smd(smd_data) is True

    # De-interleave back to flat binary
    recovered = deinterleave_smd(smd_data)
    assert recovered == flat_data


def test_md_sram_preservation_and_configuration():
    # Build minimal Sonic 3 / Phantasy Star IV style ROM with battery-backed SRAM
    rom_data = bytearray(0x0400)
    struct.pack_into(">II", rom_data, 0, 0x00FFFE00, 0x00000200)

    # Official Sega backup SRAM header block at 0x01B0 (64 bytes):
    # 'RA', 0xF8 (backup RAM flags), 0x20, start=0x00200001, end=0x00200FFF
    sram_block = bytearray(0x40)
    sram_block[0:2] = b"RA"
    sram_block[2] = 0xF8
    sram_block[3] = 0x20
    sram_block[4:8] = (0x00200001).to_bytes(4, "big")
    sram_block[8:12] = (0x00200FFF).to_bytes(4, "big")

    hdr = MDHeader(
        system_type="SEGA MEGA DRIVE",
        copyright="(C)SEGA 1994.FEB",
        domestic_title="SONIC THE HEDGEHOG 3",
        overseas_title="SONIC THE HEDGEHOG 3",
        serial_number="GM MK-1079 -00",
        checksum=0,
        io_support="J",
        rom_start=0x00000000,
        rom_end=0x001FFFFF,
        ram_start=0x00FF0000,
        ram_end=0x00FFFFFF,
        sram_support=True,
        region="JUE",
        reserved_b0=bytes(sram_block),
    )
    rom_data[0x0100:0x0200] = hdr.pack()

    # Load into MDRom
    rom = MDRom(bytes(rom_data))
    assert rom.has_sram is True
    assert rom.sram_start == 0x00200001
    assert rom.sram_end == 0x00200FFF

    # Crucial test: When saving or getting bytes, SRAM start/end must NOT be wiped out with zeroes!
    repacked_bytes = rom.to_bytes()
    reloaded = MDRom(repacked_bytes)
    assert reloaded.has_sram is True
    assert reloaded.sram_start == 0x00200001
    assert reloaded.sram_end == 0x00200FFF
    assert reloaded.header.reserved_b0[:12] == bytes(sram_block[:12])

    # Test configure_sram on a non-SRAM ROM
    plain_hdr = MDHeader(
        system_type="SEGA MEGA DRIVE",
        copyright="(C)SEGA 1991",
        domestic_title="TEST",
        overseas_title="TEST",
        serial_number="GM 00000000-00",
        checksum=0,
        io_support="J",
        rom_start=0,
        rom_end=0x7FFFF,
        ram_start=0x00FF0000,
        ram_end=0x00FFFFFF,
        sram_support=False,
        region="JUE",
    )
    plain_rom_data = bytearray(0x0400)
    plain_rom_data[0x0100:0x0200] = plain_hdr.pack()
    plain_rom = MDRom(bytes(plain_rom_data))
    assert plain_rom.has_sram is False

    plain_rom.configure_sram(start_addr=0x00200001, end_addr=0x00201FFF)
    assert plain_rom.has_sram is True
    assert plain_rom.sram_start == 0x00200001
    assert plain_rom.sram_end == 0x00201FFF
    assert plain_rom.data[0x01B0:0x01B2] == b"RA"

