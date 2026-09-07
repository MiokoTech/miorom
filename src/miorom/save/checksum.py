import struct
import zlib


class SaveChecksum:
    """
    Common checksum algorithms used across console save files and EEPROM/Flash data.
    """

    @classmethod
    def crc16_ccitt(cls, data: bytes, init: int = 0xFFFF) -> int:
        """CRC-16-CCITT (Polynomial 0x1021, default init 0xFFFF)."""
        crc = init
        for byte in data:
            crc ^= (byte << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x1021) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
        return crc

    @classmethod
    def crc16_xmodem(cls, data: bytes) -> int:
        """CRC-16-XMODEM (Polynomial 0x1021, init 0x0000)."""
        return cls.crc16_ccitt(data, init=0x0000)

    @classmethod
    def crc16_arc(cls, data: bytes) -> int:
        """CRC-16/ARC (Polynomial 0x8005, reflected in & out, init 0x0000)."""
        crc = 0x0000
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    @classmethod
    def crc32(cls, data: bytes) -> int:
        """Standard IEEE 802.3 CRC-32."""
        return zlib.crc32(data) & 0xFFFFFFFF

    @classmethod
    def fletcher16(cls, data: bytes) -> int:
        """Fletcher-16 checksum (used in Nintendo & SimCity saves)."""
        sum1 = 0
        sum2 = 0
        for byte in data:
            sum1 = (sum1 + byte) % 255
            sum2 = (sum2 + sum1) % 255
        return (sum2 << 8) | sum1

    @classmethod
    def modulo_sum16(cls, data: bytes, endian: str = "<") -> int:
        """16-bit word addition modulo 65536."""
        total = 0
        fmt = f"{endian}H"
        for i in range(0, len(data) - 1, 2):
            val = struct.unpack_from(fmt, data, i)[0]
            total = (total + val) & 0xFFFF
        return total

    @classmethod
    def modulo_sum32(cls, data: bytes, endian: str = "<") -> int:
        """32-bit word addition modulo 2^32."""
        total = 0
        fmt = f"{endian}I"
        for i in range(0, len(data) - 3, 4):
            val = struct.unpack_from(fmt, data, i)[0]
            total = (total + val) & 0xFFFFFFFF
        return total
