from miorom.result import MioRomResult
import struct
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple


@dataclass
class CryptoMatch(MioRomResult):
    """
    Representation of a cryptographic primitive detected in binary data.
    """
    algorithm: str
    pattern_type: str  # "S-Box", "Hash Constants", "Lookup Table", "Delta"
    offset: int
    size: int
    confidence: float
    details: str = ""
    xrefs: List[int] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"0x{self.offset:08X}: [{self.algorithm}] {self.pattern_type} "
            f"({self.size} bytes, Confidence: {self.confidence * 100:.0f}%) - {self.details}"
        )


@dataclass
class CryptoReport(MioRomResult):
    total_bytes: int
    matches: List[CryptoMatch] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "==================================================",
            "         CryptoHunter Binary Scanner Report       ",
            "==================================================",
            f"  Total Data Scanned : {self.total_bytes} bytes",
            f"  Detected Primitives: {len(self.matches)}",
        ]
        if self.matches:
            lines.append("  Detected Cryptographic Signatures:")
            for m in self.matches:
                lines.append(f"    - {m.summary()}")
        else:
            lines.append("  No known cryptographic primitives detected.")
        lines.append("==================================================")
        return "\n".join(lines)


class CryptoScanner:
    """
    Scans binary ROMs for cryptographic S-Boxes, initialization vectors,
    hashing constants, and encryption algorithm lookup tables.
    """

    # AES Rijndael Forward S-Box prefix (first 16 bytes)
    AES_SBOX_PREFIX = bytes([
        0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5,
        0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
    ])

    # AES Rijndael Inverse S-Box prefix
    AES_INV_SBOX_PREFIX = bytes([
        0x52, 0x09, 0x6A, 0xD5, 0x30, 0x36, 0xA5, 0x38,
        0xBF, 0x40, 0xA3, 0x9E, 0x81, 0xF3, 0xD7, 0xFB,
    ])

    # MD5 Invariant State Constants (A, B, C, D)
    MD5_CONSTANTS_LE = struct.pack("<4I", 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476)
    MD5_CONSTANTS_BE = struct.pack(">4I", 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476)

    # SHA-1 / SHA-256 Invariant State Constants (A, B, C, D, E)
    SHA1_CONSTANTS_LE = struct.pack("<5I", 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0)
    SHA1_CONSTANTS_BE = struct.pack(">5I", 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0)

    # TEA / XTEA Golden Ratio Delta Constant (0x9E3779B9)
    TEA_DELTA_LE = struct.pack("<I", 0x9E3779B9)
    TEA_DELTA_BE = struct.pack(">I", 0x9E3779B9)

    # CRC32 IEEE lookup table prefix
    CRC32_IEEE_PREFIX = bytes([
        0x00, 0x00, 0x00, 0x00, 0x96, 0x30, 0x07, 0x77,
        0x2C, 0x61, 0x0E, 0xEE, 0xBA, 0x51, 0x09, 0x99,
    ])

    @classmethod
    def scan(
        cls,
        data: bytes,
        base_address: int = 0,
        scan_xrefs: bool = True,
    ) -> CryptoReport:
        return CryptoReport(total_bytes=len(data), matches=list(cls.iter_matches(data, base_address=base_address, scan_xrefs=scan_xrefs)))

    @classmethod
    def iter_matches(
        cls,
        data: bytes,
        base_address: int = 0,
        scan_xrefs: bool = True,
    ) -> Iterator[CryptoMatch]:
        """Yield cryptographic primitives as they are found."""
        # AES S-Box constants
        pos = 0
        while True:
            idx = data.find(cls.AES_SBOX_PREFIX, pos)
            if idx == -1:
                break
            yield CryptoMatch(
                    algorithm="AES",
                    pattern_type="Forward S-Box",
                    offset=base_address + idx,
                    size=256,
                    confidence=1.0,
                    details="Rijndael AES Encryption Substitution Box",
                )
            pos = idx + 1

        # AES Inverse S-Box constants
        pos = 0
        while True:
            idx = data.find(cls.AES_INV_SBOX_PREFIX, pos)
            if idx == -1:
                break
            yield CryptoMatch(
                    algorithm="AES",
                    pattern_type="Inverse S-Box",
                    offset=base_address + idx,
                    size=256,
                    confidence=1.0,
                    details="Rijndael AES Decryption Substitution Box",
                )
            pos = idx + 1

        # MD5 constants
        for sig, end_name in ((cls.MD5_CONSTANTS_LE, "Little-Endian"), (cls.MD5_CONSTANTS_BE, "Big-Endian")):
            pos = 0
            while True:
                idx = data.find(sig, pos)
                if idx == -1:
                    break
                yield CryptoMatch(
                        algorithm="MD5",
                        pattern_type="Hash Constants",
                        offset=base_address + idx,
                        size=16,
                        confidence=0.95,
                        details=f"MD5 State Initializers ({end_name})",
                    )
                pos = idx + 1

        # SHA-1 constants
        for sig, end_name in ((cls.SHA1_CONSTANTS_LE, "Little-Endian"), (cls.SHA1_CONSTANTS_BE, "Big-Endian")):
            pos = 0
            while True:
                idx = data.find(sig, pos)
                if idx == -1:
                    break
                yield CryptoMatch(
                        algorithm="SHA-1",
                        pattern_type="Hash Constants",
                        offset=base_address + idx,
                        size=20,
                        confidence=0.98,
                        details=f"SHA-1 Initial Digest Vector ({end_name})",
                    )
                pos = idx + 1

        # TEA delta constant (0x9E3779B9)
        for sig, end_name in ((cls.TEA_DELTA_LE, "Little-Endian"), (cls.TEA_DELTA_BE, "Big-Endian")):
            pos = 0
            while True:
                idx = data.find(sig, pos)
                if idx == -1:
                    break
                yield CryptoMatch(
                        algorithm="TEA/XTEA",
                        pattern_type="Golden Ratio Delta",
                        offset=base_address + idx,
                        size=4,
                        confidence=0.85,
                        details=f"TEA / XTEA Key Schedule Delta 0x9E3779B9 ({end_name})",
                    )
                pos = idx + 1

        # CRC32 polynomial lookup table
        pos = 0
        while True:
            idx = data.find(cls.CRC32_IEEE_PREFIX, pos)
            if idx == -1:
                break
            yield CryptoMatch(
                    algorithm="CRC32",
                    pattern_type="Lookup Table",
                    offset=base_address + idx,
                    size=1024,
                    confidence=0.99,
                    details="IEEE 802.3 CRC32 Lookup Table (Polynomial 0xEDB88320)",
                )
            pos = idx + 1
