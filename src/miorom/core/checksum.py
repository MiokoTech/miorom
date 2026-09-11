import struct
from typing import Optional, Tuple


class RetroChecksum:
    """
    Pure-Python retro cyclic and additive checksum primitives.
    Bitwise-exact algorithms for cartridge ROMs and save files.
    """

    @staticmethod
    def crc16_ccitt(data: bytes, init: int = 0xFFFF, poly: int = 0x1021) -> int:
        """Standard 16-bit CRC-CCITT (MSB-first)."""
        crc = init
        for b in data:
            crc ^= (b << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ poly) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
        return crc

    @staticmethod
    def crc16_xmodem(data: bytes) -> int:
        """CRC-16 XMODEM (CCITT with initial value 0x0000)."""
        return RetroChecksum.crc16_ccitt(data, init=0x0000, poly=0x1021)

    @staticmethod
    def crc16_arc(data: bytes) -> int:
        """CRC-16-IBM / ARC (reflected polynomial 0xA001, initial value 0x0000)."""
        crc = 0x0000
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    @staticmethod
    def crc16_modbus(data: bytes) -> int:
        """CRC-16 Modbus (reflected polynomial 0xA001, initial value 0xFFFF)."""
        crc = 0xFFFF
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    @staticmethod
    def crc32_pure(data: bytes, init: int = 0xFFFFFFFF) -> int:
        """Pure-Python IEEE 802.3 CRC32 without external C extensions."""
        crc = init
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xEDB88320
                else:
                    crc >>= 1
        return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF

    @staticmethod
    def adler32_pure(data: bytes) -> int:
        """Pure-Python Adler-32 dual 16-bit accumulator checksum."""
        MOD_ADLER = 65521
        a = 1
        b = 0
        for byte in data:
            a = (a + byte) % MOD_ADLER
            b = (b + a) % MOD_ADLER
        return (b << 16) | a

    @staticmethod
    def fletcher16(data: bytes) -> int:
        """Fletcher-16 checksum modulo 255."""
        sum1 = 0
        sum2 = 0
        for byte in data:
            sum1 = (sum1 + byte) % 255
            sum2 = (sum2 + sum1) % 255
        return (sum2 << 8) | sum1

    @staticmethod
    def genesis_checksum(data: bytes, start: int = 0x200, end: Optional[int] = None) -> int:
        """
        Sega Genesis / Mega Drive 16-bit big-endian additive word sum.
        Accumulates 16-bit words from offset 0x200 (after 512-byte header) to end of ROM.
        """
        if end is None:
            end = len(data)
        if len(data) < 0x200:
            return 0

        total = 0
        for i in range(start, end - 1, 2):
            total = (total + ((data[i] << 8) | data[i + 1])) & 0xFFFF

        # If odd byte remains at end
        if (end - start) % 2 != 0:
            total = (total + (data[end - 1] << 8)) & 0xFFFF

        return total

    @staticmethod
    def snes_checksum(data: bytes) -> Tuple[int, int]:
        """
        Calculates SNES cartridge 16-bit sum and complement pair.
        Handles standard Nintendo mirroring for non-power-of-two ROM capacities.
        Returns (checksum, complement) where checksum + complement == 0xFFFF.
        """
        if not data:
            return 0, 0xFFFF

        # If ROM has 512-byte SMC header, skip it
        if len(data) % 1024 == 512:
            data = data[512:]

        rom_len = len(data)
        # Check power of two
        is_pow2 = (rom_len & (rom_len - 1)) == 0

        if is_pow2:
            raw_sum = sum(data)
        else:
            # Find largest power of 2 smaller than rom_len
            largest_pow2 = 1 << ((rom_len.bit_length() - 1))
            remainder = rom_len - largest_pow2
            # How many times remainder mirrors to fill power of two
            next_pow2_rem = 1 << (remainder - 1).bit_length()
            mult = max(1, next_pow2_rem // remainder)

            sum_base = sum(data[:largest_pow2])
            sum_rem = sum(data[largest_pow2:]) * mult
            raw_sum = sum_base + sum_rem

        chk = raw_sum & 0xFFFF
        comp = (~chk) & 0xFFFF
        return chk, comp

    @staticmethod
    def gameboy_header_checksum(rom_data: bytes) -> int:
        """
        Calculates Nintendo Game Boy cartridge header complement checksum.
        Computed over bytes 0x0134 through 0x014C.
        """
        if len(rom_data) < 0x014D:
            raise ValueError("ROM data too short for Game Boy header checksum")

        chk = 0
        for i in range(0x0134, 0x014D):
            chk = (chk - rom_data[i] - 1) & 0xFF
        return chk

    @staticmethod
    def gameboy_global_checksum(rom_data: bytes) -> int:
        """
        Calculates Nintendo Game Boy 16-bit big-endian global checksum.
        Sums all bytes in ROM excluding header bytes 0x014E and 0x014F.
        """
        total = 0
        for i, b in enumerate(rom_data):
            if i in (0x014E, 0x014F):
                continue
            total = (total + b) & 0xFFFF
        return total
