import hashlib
from enum import Enum
from miorom.core.schema import BinaryStruct, U32
from typing import Optional, Tuple


class N64EntryPointStruct(BinaryStruct):
    _endian = ">"
    entrypoint = U32()


class N64CrcStruct(BinaryStruct):
    _endian = ">"
    crc1 = U32()
    crc2 = U32()


N64Word = U32(endian=">")


class N64CIC(Enum):
    CIC_6101 = "6101"
    CIC_6102_7101 = "6102"
    CIC_7102 = "7102"
    CIC_6103_7103 = "6103"
    CIC_6105_7105 = "6105"
    CIC_6106_7106 = "6106"
    CIC_5101 = "5101"


# IPL3 bootcode MD5 hash map
IPL3_MD5_MAP = {
    "900b4a5b68edb71f4c7ed52acd814fc5": N64CIC.CIC_6101,
    "e24dd796b2fa16511521139d28c8356b": N64CIC.CIC_6102_7101,
    "955894c2e40a698bf98a67b78a4e28fa": N64CIC.CIC_7102,
    "319038097346e12c26c3c21b56f86f23": N64CIC.CIC_6103_7103,
    "ff22a296e55d34ab0a077dc2ba5f5796": N64CIC.CIC_6105_7105,
    "6460387749ac0bd925aa5430bc7864fe": N64CIC.CIC_6106_7106,
    "711f8c3ac54fc70a42626bf6c171443d": N64CIC.CIC_5101,
}

CIC_SEEDS = {
    N64CIC.CIC_6101: 0x3F,
    N64CIC.CIC_6102_7101: 0x3F,
    N64CIC.CIC_7102: 0x3F,
    N64CIC.CIC_6103_7103: 0x78,
    N64CIC.CIC_6105_7105: 0x91,
    N64CIC.CIC_6106_7106: 0x85,
    N64CIC.CIC_5101: 0xAC,
}

CIC_MAGICS = {
    N64CIC.CIC_6101: 0x5D588B65,
    N64CIC.CIC_6102_7101: 0x5D588B65,
    N64CIC.CIC_7102: 0x5D588B65,
    N64CIC.CIC_6103_7103: 0x6C078965,
    N64CIC.CIC_6105_7105: 0x5D588B65,
    N64CIC.CIC_6106_7106: 0x6C078965,
    N64CIC.CIC_5101: 0x6C078965,
}


def detect_cic(rom_bytes: bytes) -> Optional[N64CIC]:
    """
    Detect the CIC chip variant from the ROM's IPL3 bootcode (offset 0x40 to 0x1000).
    Requires big-endian (.z64) ROM format.
    """
    if len(rom_bytes) < 0x1000:
        return None
    bootcode = rom_bytes[0x40:0x1000]
    md5_hash = hashlib.md5(bootcode).hexdigest()
    return IPL3_MD5_MAP.get(md5_hash)


def calculate_n64_checksum(
    rom_bytes: bytes,
    cic: Optional[N64CIC] = None,
) -> Tuple[int, int]:
    """
    Calculate the 64-bit IPL3 checksum (CRC1 and CRC2) for a big-endian N64 ROM.
    If cic is None, it is auto-detected from the bootcode, defaulting to CIC_6102_7101.
    """
    if cic is None:
        cic = detect_cic(rom_bytes) or N64CIC.CIC_6102_7101

    entrypoint = (
        N64EntryPointStruct.from_bytes(rom_bytes, offset=8).entrypoint
        if len(rom_bytes) >= N64EntryPointStruct.sizeof() + 8
        else 0x80000400
    )
    bytes_to_check = 0x100000  # 1 MiB standard
    if cic == N64CIC.CIC_5101 and entrypoint == 0x80000400:
        bytes_to_check = 0x3FE000

    min_required = 0x1000 + bytes_to_check
    if len(rom_bytes) < min_required:
        # Pad with zeros for short ROM buffers
        rom_bytes = rom_bytes.ljust(min_required, b"\x00")

    seed = CIC_SEEDS[cic]
    magic = CIC_MAGICS[cic]

    v0 = (seed * magic + 1) & 0xFFFFFFFF
    a3 = v0
    t2 = v0
    t3 = v0
    s0 = v0
    a2 = v0
    t4 = v0

    is_6105 = (cic == N64CIC.CIC_6105_7105)

    words_count = bytes_to_check // N64Word.get_size()
    for i in range(words_count):
        offset = 0x1000 + i * N64Word.get_size()
        word = N64Word.unpack(rom_bytes, offset, ">")[0]
        a1 = (a3 + word) & 0xFFFFFFFF
        if a1 < a3:
            t2 = (t2 + 1) & 0xFFFFFFFF
        a3 = a1

        sh = word & 0x1F
        a0 = ((word << sh) | (word >> (32 - sh))) & 0xFFFFFFFF if sh else word

        t3 ^= word
        s0 = (s0 + a0) & 0xFFFFFFFF

        if a2 < word:
            a2 ^= a3 ^ word
        else:
            a2 ^= a0

        if is_6105:
            temp = (i & 0x3F) | 0x80
            disp_offset = (temp + 0x154) * 4
            t7 = N64Word.unpack(rom_bytes, disp_offset, ">")[0]
            t4 = (t4 + (word ^ t7)) & 0xFFFFFFFF
        else:
            t4 = (t4 + (word ^ s0)) & 0xFFFFFFFF

    if cic in (N64CIC.CIC_6103_7103, N64CIC.CIC_5101):
        crc1 = ((a3 ^ t2) + t3) & 0xFFFFFFFF
        crc2 = ((s0 ^ a2) + t4) & 0xFFFFFFFF
    elif cic == N64CIC.CIC_6106_7106:
        crc1 = (((a3 * t2) & 0xFFFFFFFF) + t3) & 0xFFFFFFFF
        crc2 = (((s0 * a2) & 0xFFFFFFFF) + t4) & 0xFFFFFFFF
    else:
        crc1 = (a3 ^ t2 ^ t3) & 0xFFFFFFFF
        crc2 = (s0 ^ a2 ^ t4) & 0xFFFFFFFF

    return crc1, crc2


def verify_n64_checksum(
    rom_bytes: bytes,
    cic: Optional[N64CIC] = None,
) -> bool:
    """
    Verify whether the CRC1 and CRC2 in the ROM header match the calculated values.
    """
    if len(rom_bytes) < 0x18:
        return False
    crc = N64CrcStruct.from_bytes(rom_bytes, offset=0x10)
    expected_crc1, expected_crc2 = crc.crc1, crc.crc2
    actual_crc1, actual_crc2 = calculate_n64_checksum(rom_bytes, cic)
    return (expected_crc1 == actual_crc1) and (expected_crc2 == actual_crc2)


def fix_n64_checksum(
    rom_bytes: bytes,
    cic: Optional[N64CIC] = None,
    preserve_database_crc: bool = False,
) -> bytes:
    """
    Recalculate the N64 header checksum and patch CRC1 & CRC2 at offsets 0x10..0x18.
    If preserve_database_crc=True, leaves header CRC intact to maintain emulator metadata.
    Returns the patched ROM bytes.
    """
    if preserve_database_crc:
        return rom_bytes
    crc1, crc2 = calculate_n64_checksum(rom_bytes, cic)
    ba = bytearray(rom_bytes)
    ba[0x10:0x18] = N64CrcStruct(crc1=crc1, crc2=crc2).to_bytes()
    return bytes(ba)
