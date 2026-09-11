from typing import Tuple, Sequence, Optional


class SNESBusMapper:
    """
    Pure mathematical bus address and ROM file offset mapper for SNES.
    Supports LoROM (Mode 20), HiROM (Mode 21), ExHiROM (Mode 25), and optional SMC header.
    """

    @staticmethod
    def lorom_to_offset(addr: int, smc_header: bool = False) -> int:
        """
        Translates SNES LoROM 24-bit bus address ($BB:AAAA) to physical ROM file offset.
        ROM data resides in $8000-$FFFF across banks $00-$7D and $80-$FF.
        """
        bank = (addr >> 16) & 0xFF
        word = addr & 0xFFFF

        if word < 0x8000:
            raise ValueError(f"LoROM ROM addresses reside in $8000-$FFFF, got word 0x{word:04X} in bank 0x{bank:02X}")

        bank_idx = bank & 0x7F
        if bank_idx > 0x7D:
            raise ValueError(f"LoROM bank 0x{bank:02X} is outside valid ROM bank range ($00-$7D, $80-$FD)")

        offset = (bank_idx * 0x8000) + (word - 0x8000)
        return offset + (512 if smc_header else 0)

    @staticmethod
    def offset_to_lorom(offset: int, smc_header: bool = False, mirror: bool = True) -> int:
        """
        Translates physical ROM file offset to SNES LoROM 24-bit bus address.
        mirror=True maps into upper mirror banks ($80-$FF), standard in SNES programming.
        """
        if smc_header:
            if offset < 512:
                raise ValueError("Offset is within SMC header")
            offset -= 512

        bank_idx = offset // 0x8000
        word = 0x8000 + (offset % 0x8000)
        bank = (0x80 + bank_idx) if mirror else bank_idx
        return (bank << 16) | word

    @staticmethod
    def hirom_to_offset(addr: int, smc_header: bool = False) -> int:
        """
        Translates SNES HiROM 24-bit bus address ($BB:AAAA) to physical ROM file offset.
        ROM resides in banks $40-$7D and $C0-$FF ($0000-$FFFF).
        """
        bank = (addr >> 16) & 0xFF
        word = addr & 0xFFFF

        if bank in range(0x40, 0x7E) or bank in range(0xC0, 0x100):
            bank_idx = bank & 0x3F
            offset = (bank_idx * 0x10000) + word
        elif (bank in range(0x00, 0x40) or bank in range(0x80, 0xC0)) and word >= 0x8000:
            bank_idx = bank & 0x3F
            offset = (bank_idx * 0x10000) + word
        else:
            raise ValueError(f"Address 0x{addr:06X} does not map to HiROM ROM space")

        return offset + (512 if smc_header else 0)

    @staticmethod
    def offset_to_hirom(offset: int, smc_header: bool = False, mirror: bool = True) -> int:
        """
        Translates physical ROM file offset to SNES HiROM 24-bit bus address.
        mirror=True maps into banks $C0-$FF.
        """
        if smc_header:
            if offset < 512:
                raise ValueError("Offset is within SMC header")
            offset -= 512

        bank_idx = offset // 0x10000
        word = offset % 0x10000
        bank = (0xC0 + bank_idx) if mirror else (0x40 + bank_idx)
        return (bank << 16) | word


class NESBusMapper:
    """
    Pure mathematical bus address and ROM file offset mapper for NES.
    Supports NROM, MMC1, and MMC3 PRG/CHR banking configurations.
    """

    @staticmethod
    def nrom_to_offset(addr: int, prg_rom_size: int = 32768, header_size: int = 16) -> int:
        """
        Translates NES NROM CPU bus address ($8000-$FFFF) to iNES ROM file offset.
        Supports 16KB PRG (mirrored at $8000 and $C000) and 32KB PRG.
        """
        if not (0x8000 <= addr <= 0xFFFF):
            raise ValueError(f"NES PRG address must be between $8000 and $FFFF, got 0x{addr:04X}")

        if prg_rom_size <= 16384:
            rel = (addr - 0x8000) % 0x4000
        else:
            rel = addr - 0x8000

        return header_size + rel

    @staticmethod
    def offset_to_nrom(offset: int, header_size: int = 16) -> int:
        """Translates iNES ROM file offset to NROM CPU address ($8000-$FFFF)."""
        if offset < header_size:
            raise ValueError("Offset is within iNES header")
        rel = offset - header_size
        return 0x8000 + (rel & 0x7FFF)

    @staticmethod
    def mmc1_prg_to_offset(
        addr: int,
        bank_16k: int,
        prg_rom_size: int = 131072,
        header_size: int = 16,
        fixed_high: bool = True,
    ) -> int:
        """
        Translates CPU address to iNES offset under MMC1 16KB PRG banking.
        fixed_high=True: $8000-$BFFF switchable, $C000-$FFFF fixed to last 16KB bank.
        """
        if not (0x8000 <= addr <= 0xFFFF):
            raise ValueError(f"NES PRG address must be in $8000-$FFFF, got 0x{addr:04X}")

        total_16k_banks = max(1, prg_rom_size // 0x4000)
        last_bank = total_16k_banks - 1

        if fixed_high:
            if addr < 0xC000:
                selected_bank = bank_16k % total_16k_banks
                rel = (selected_bank * 0x4000) + (addr - 0x8000)
            else:
                rel = (last_bank * 0x4000) + (addr - 0xC000)
        else:
            if addr < 0xC000:
                rel = addr - 0x8000
            else:
                selected_bank = bank_16k % total_16k_banks
                rel = (selected_bank * 0x4000) + (addr - 0xC000)

        return header_size + rel

    @staticmethod
    def mmc3_prg_to_offset(
        addr: int,
        r6_bank: int,
        r7_bank: int,
        prg_rom_size: int,
        header_size: int = 16,
        prg_mode: int = 0,
    ) -> int:
        """
        Translates CPU address to iNES offset under MMC3 8KB PRG banking.
        prg_mode=0: $8000=R6, $A000=R7, $C000=(-2), $E000=(-1)
        prg_mode=1: $8000=(-2), $A000=R7, $C000=R6, $E000=(-1)
        """
        if not (0x8000 <= addr <= 0xFFFF):
            raise ValueError(f"NES PRG address must be in $8000-$FFFF, got 0x{addr:04X}")

        total_8k_banks = max(1, prg_rom_size // 8192)
        second_last = total_8k_banks - 2
        last_bank = total_8k_banks - 1

        slot = (addr - 0x8000) // 8192
        slot_offset = addr % 8192

        if prg_mode == 0:
            if slot == 0:
                bank = r6_bank % total_8k_banks
            elif slot == 1:
                bank = r7_bank % total_8k_banks
            elif slot == 2:
                bank = second_last
            else:
                bank = last_bank
        else:
            if slot == 0:
                bank = second_last
            elif slot == 1:
                bank = r7_bank % total_8k_banks
            elif slot == 2:
                bank = r6_bank % total_8k_banks
            else:
                bank = last_bank

        return header_size + (bank * 8192) + slot_offset


class GameBoyBusMapper:
    """
    Pure mathematical bus address and ROM file offset mapper for Game Boy.
    Supports fixed Bank 0 ($0000-$3FFF) and switched Bank 1..N ($4000-$7FFF) for MBC1/3/5.
    """

    @staticmethod
    def mbc_to_offset(addr: int, bank: int = 1, mbc_type: str = "mbc1") -> int:
        """
        Translates Game Boy 16-bit CPU address to raw ROM file offset.
        Handles MBC1 bank 0 translation quirk ($00, $20, $40, $60 map to +1).
        """
        if not (0x0000 <= addr <= 0x7FFF):
            raise ValueError(f"Game Boy cartridge ROM address must be in $0000-$7FFF, got 0x{addr:04X}")

        if addr < 0x4000:
            return addr

        mbc = mbc_type.lower()
        effective_bank = bank
        if mbc == "mbc1":
            if effective_bank in (0, 0x20, 0x40, 0x60):
                effective_bank += 1
        elif effective_bank == 0:
            effective_bank = 1

        return (effective_bank * 0x4000) + (addr - 0x4000)

    @staticmethod
    def offset_to_mbc(offset: int) -> Tuple[int, int]:
        """
        Translates ROM file offset to Game Boy (bank, cpu_address) pair.
        """
        if offset < 0:
            raise ValueError(f"Offset cannot be negative: {offset}")

        if offset < 0x4000:
            return 0, offset

        bank = offset // 0x4000
        cpu_addr = 0x4000 + (offset % 0x4000)
        return bank, cpu_addr
