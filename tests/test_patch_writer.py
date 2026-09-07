import struct
import pytest
from miorom.patch.patch_writer import PatchWriter, PatchRecord
from miorom.patch.ips import IpsPatcher


def test_patch_writer_fluent_chaining():
    buf = bytearray(0x50)
    w = PatchWriter(buf, endian="<")

    (w.seek_to(0x04)
     .write_u32(0x12345678)
     .write_u16(0xCAFE)
     .write_u8(0xFF)
     .align_to(4)
     .write_str("MIO", null_terminated=True)
     .write_arm_nop(count=2))

    # Verification:
    # 0x04: 0x12345678 (4 bytes) -> cursor = 0x08
    # 0x08: 0xCAFE (2 bytes) -> cursor = 0x0A
    # 0x0A: 0xFF (1 byte) -> cursor = 0x0B
    # align_to(4) -> cursor pads 1 byte to 0x0C
    # 0x0C: "MIO\0" (4 bytes) -> cursor = 0x10
    # 0x10: 2 NOPs (8 bytes) -> cursor = 0x18
    assert w.cursor == 0x18
    assert struct.unpack_from("<I", buf, 0x04)[0] == 0x12345678
    assert struct.unpack_from("<H", buf, 0x08)[0] == 0xCAFE
    assert buf[0x0A] == 0xFF
    assert buf[0x0C:0x10] == b"MIO\x00"
    assert struct.unpack_from("<I", buf, 0x10)[0] == 0xE1A00000
    assert struct.unpack_from("<I", buf, 0x14)[0] == 0xE1A00000


def test_patch_writer_ips_export():
    buf = bytearray(0x30)
    w = PatchWriter(buf)
    w.seek_to(0x10).write_bytes(b"HELLO")

    ips_data = w.generate_ips()
    assert ips_data.startswith(b"PATCH")
    assert ips_data.endswith(b"EOF")

    # Apply generated IPS to clean buffer and check fidelity
    clean = bytearray(0x30)
    patched = IpsPatcher.apply(bytes(clean), ips_data)
    assert patched[0x10:0x15] == b"HELLO"
