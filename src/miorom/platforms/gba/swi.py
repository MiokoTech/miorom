"""
miorom.platforms.gba.swi
~~~~~~~~~~~~~~~~~~~~~~~~
Game Boy Advance BIOS Software Interrupt (SWI) lookup database and disassembler annotator.

Enables reverse engineering of GBA ROMs by resolving official BIOS system calls
for memory transfers, LZ77/Huffman decompression, math, sound, and multi-boot.
"""

from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional, Tuple

from miorom.result import MioRomResult


GBA_SWI_TABLE: Dict[int, Tuple[str, str]] = {
    0x00: ("SoftReset", "Clears RAM and restarts execution at cartridge header"),
    0x01: ("RegisterRamReset", "Resets select I/O registers and WRAM regions based on flags in R0"),
    0x02: ("Halt", "Enters low-power standby mode until an interrupt occurs"),
    0x03: ("Stop", "Enters deep sleep mode until keypad or cartridge interrupt occurs"),
    0x04: ("IntrWait", "Waits for one or more specific interrupts to fire"),
    0x05: ("VBlankIntrWait", "Waits specifically for the next vertical blank interrupt"),
    0x06: ("Div", "Signed integer division: R0 / R1 -> R0 (quotient), R1 (remainder)"),
    0x07: ("DivArm", "Signed integer division with reversed operands: R1 / R0"),
    0x08: ("Sqrt", "Integer square root: sqrt(R0) -> R0"),
    0x09: ("ArcTan", "Computes arctangent: atan(R0) -> R0"),
    0x0A: ("ArcTan2", "Computes two-variable arctangent: atan2(R0=X, R1=Y) -> R0"),
    0x0B: ("CpuSet", "Block copy or word fill (16-bit or 32-bit transfers)"),
    0x0C: ("CpuFastSet", "High-speed 32-byte block copy or fill using LDMIA/STMIA"),
    0x0D: ("GetBiosChecksum", "Calculates CRC/checksum over 16KB GBA BIOS ROM"),
    0x0E: ("BgAffineSet", "Calculates affine transformation matrices for BG rotation/scaling"),
    0x0F: ("ObjAffineSet", "Calculates affine transformation matrices for sprite rotation/scaling"),
    0x10: ("BitUnPack", "Unpacks bit-packed graphic stream into 1, 2, or 4 bpp VRAM buffers"),
    0x11: ("LZ77UnCompWram", "Decompresses LZ77-0x10 stream into byte-accessible EWRAM/IWRAM"),
    0x12: ("LZ77UnCompVram", "Decompresses LZ77-0x10 stream into halfword-accessible VRAM"),
    0x13: ("HuffUnComp", "Decompresses 4-bit or 8-bit Huffman stream into VRAM/WRAM"),
    0x14: ("RLUnCompWram", "Decompresses Run-Length-0x30 stream into WRAM"),
    0x15: ("RLUnCompVram", "Decompresses Run-Length-0x30 stream into halfword VRAM"),
    0x16: ("Diff8bitUnCompWram", "Applies 8-bit directional filtering delta decompression to WRAM"),
    0x17: ("Diff8bitUnCompVram", "Applies 8-bit directional filtering delta decompression to VRAM"),
    0x18: ("Diff16bitUnComp", "Applies 16-bit directional filtering delta decompression"),
    0x19: ("SoundBiasChange", "Ramps sound bias level up or down to eliminate clicks"),
    0x1A: ("SoundDriverInit", "Initializes the official Nintendo MusicPlayer2000 sound driver"),
    0x1B: ("SoundDriverMode", "Configures sound driver polyphony, reverb, and frequency"),
    0x1C: ("SoundDriverMain", "Main sound driver tick routine executed every frame"),
    0x1D: ("SoundDriverVSync", "Sound driver VBlank synchronization trigger"),
    0x1E: ("SoundChannelClear", "Silences all active DirectSound DMA channels"),
    0x1F: ("MidiKey2Freq", "Translates MIDI key note and pitch bend to sound frequency"),
    0x25: ("MultiBoot", "Initiates link cable multiboot communication to slave GBA units"),
}


class GBASwiResolver(MioRomResult):
    """
    Symbolic annotator and call-site scanner for Game Boy Advance BIOS SWI calls.
    """

    @classmethod
    def resolve(cls, swi_number: int) -> Optional[Tuple[str, str]]:
        """Resolves an SWI call number to its official function name and description."""
        return GBA_SWI_TABLE.get(swi_number)

    @classmethod
    def annotate_thumb_instruction(cls, opcode: int) -> Optional[str]:
        """
        Inspects a 16-bit Thumb instruction word.
        If it is a SWI call (0xDFxx), returns an IDA/Ghidra style annotation string.
        """
        if (opcode & 0xFF00) == 0xDF00:
            swi_num = opcode & 0xFF
            entry = cls.resolve(swi_num)
            if entry:
                name, desc = entry
                return f"; BIOS SWI 0x{swi_num:02X}: {name} ({desc})"
            return f"; BIOS SWI 0x{swi_num:02X}"
        return None

    @classmethod
    def annotate_arm_instruction(cls, opcode: int) -> Optional[str]:
        """
        Inspects a 32-bit ARM instruction word.
        If it is a SWI call (0xEFxxxxxx), returns an annotation string.
        """
        if (opcode & 0x0F000000) == 0x0F000000:
            # GBA SWI opcode encoding
            swi_num = (opcode >> 16) & 0xFF
            if swi_num == 0:
                swi_num = opcode & 0xFF
            entry = cls.resolve(swi_num)
            if entry:
                name, desc = entry
                return f"; BIOS SWI 0x{swi_num:02X}: {name} ({desc})"
            return f"; BIOS SWI 0x{swi_num:02X}"
        return None

    @classmethod
    def scan_swi_calls(
        cls,
        data: bytes,
        thumb_mode: bool = True,
        base_addr: int = 0x08000000,
    ) -> List[Dict[str, Any]]:
        """
        Scans a binary byte sequence for BIOS SWI calls.
        Returns a list of discovered calls with memory offset, SWI number, name, and comment.
        """
        results: List[Dict[str, Any]] = []

        if thumb_mode:
            # 16-bit aligned scan
            limit = len(data) - (len(data) % 2)
            for i in range(0, limit, 2):
                opcode = data[i] | (data[i + 1] << 8)
                if (opcode & 0xFF00) == 0xDF00:
                    swi_num = opcode & 0xFF
                    entry = cls.resolve(swi_num)
                    name = entry[0] if entry else f"Unknown_SWI_{swi_num:02X}"
                    desc = entry[1] if entry else ""
                    results.append({
                        "address": base_addr + i,
                        "offset": i,
                        "swi_number": swi_num,
                        "name": name,
                        "description": desc,
                        "mode": "thumb",
                    })
        else:
            # 32-bit aligned scan
            limit = len(data) - (len(data) % 4)
            for i in range(0, limit, 4):
                opcode = struct.unpack_from("<I", data, i)[0]
                if (opcode & 0x0F000000) == 0x0F000000:
                    swi_num = (opcode >> 16) & 0xFF
                    if swi_num == 0:
                        swi_num = opcode & 0xFF
                    entry = cls.resolve(swi_num)
                    name = entry[0] if entry else f"Unknown_SWI_{swi_num:02X}"
                    desc = entry[1] if entry else ""
                    results.append({
                        "address": base_addr + i,
                        "offset": i,
                        "swi_number": swi_num,
                        "name": name,
                        "description": desc,
                        "mode": "arm",
                    })

        return results
