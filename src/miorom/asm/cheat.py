"""
miorom.asm.cheat
~~~~~~~~~~~~~~~~
Universal Cheat Code and Live RAM Patcher Generator.
Generates Gecko Codes (Wii / GameCube), Action Replay (NDS / GBA),
and CWCheat / GameShark (PSX / PSP) from memory edits and binary diffs.
"""

from miorom.result import MioRomResult
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union


@dataclass
class CheatEntry(MioRomResult):
    entry_type: str  # "write32", "write16", "write8", "c2_asm", "raw"
    address: int
    value: int = 0
    payload: bytes = b""
    comment: Optional[str] = None


class GeckoCode:
    """
    Gecko Code format encoder for Nintendo Wii and GameCube (Dolphin, Ocarina, Gecko OS).
    """

    @classmethod
    def format_write32(cls, address: int, value: int) -> str:
        # 04XXXXXX YYYYYYYY
        off = address & 0x01FFFFFF
        return f"04{off:06X} {value:08X}"

    @classmethod
    def format_write16(cls, address: int, value: int) -> str:
        # 02XXXXXX 0000YYYY
        off = address & 0x01FFFFFF
        return f"02{off:06X} {value & 0xFFFF:08X}"

    @classmethod
    def format_write8(cls, address: int, value: int) -> str:
        # 00XXXXXX 000000YY
        off = address & 0x01FFFFFF
        return f"00{off:06X} {value & 0xFF:08X}"

    @classmethod
    def format_c2_asm(cls, address: int, asm_bytes: bytes) -> List[str]:
        """
        Formats a C2 Gecko Code (Insert Assembly).
        Gecko will allocate memory in its code handler, copy the instructions,
        and place a branch at address to the injected code, then branch back.

        C2XXXXXX NNNNNNNN
        IIIIIIII IIIIIIII
        ...
        60000000 00000000 (padding if odd number of instructions)
        """
        off = address & 0x01FFFFFF
        pad_needed = (len(asm_bytes) % 8) != 0
        padded = bytearray(asm_bytes)
        if pad_needed:
            # PowerPC NOP padding (ori r0, r0, 0 = 0x60000000)
            rem = 8 - (len(asm_bytes) % 8)
            if rem == 4:
                padded.extend(b"\x60\x00\x00\x00")
            else:
                padded.extend(b"\x00" * rem)

        lines_count = len(padded) // 8
        lines = [f"C2{off:06X} {lines_count:08X}"]

        for i in range(lines_count):
            w1 = struct.unpack_from(">I", padded, i * 8)[0]
            w2 = struct.unpack_from(">I", padded, i * 8 + 4)[0]
            lines.append(f"{w1:08X} {w2:08X}")

        return lines

    @classmethod
    def to_gct(cls, code_lines: List[str]) -> bytes:
        """
        Build raw binary .gct file from list of 8-char + 8-char hex code lines.
        Header: 00D0C0DE 00D0C0DE
        Footer: F0000000 00000000
        """
        out = bytearray()
        # Header
        out.extend(b"\x00\xD0\xC0\xDE\x00\xD0\xC0\xDE")

        for line in code_lines:
            line_clean = line.split("#")[0].strip()
            if not line_clean or line_clean.startswith("$") or line_clean.startswith("["):
                continue
            parts = line_clean.split()
            if len(parts) == 2 and len(parts[0]) == 8 and len(parts[1]) == 8:
                w1 = int(parts[0], 16)
                w2 = int(parts[1], 16)
                out.extend(struct.pack(">II", w1, w2))

        # Footer
        out.extend(b"\xF0\x00\x00\x00\x00\x00\x00\x00")
        return bytes(out)


class ActionReplayCode:
    """
    Action Replay Code format encoder for Nintendo DS and Game Boy Advance.
    """

    @classmethod
    def format_write32(cls, address: int, value: int) -> str:
        w1 = (0 << 28) | (address & 0x0FFFFFFF)
        return f"{w1:08X} {value:08X}"

    @classmethod
    def format_write16(cls, address: int, value: int) -> str:
        w1 = (1 << 28) | (address & 0x0FFFFFFF)
        return f"{w1:08X} {value & 0xFFFF:08X}"

    @classmethod
    def format_write8(cls, address: int, value: int) -> str:
        w1 = (2 << 28) | (address & 0x0FFFFFFF)
        return f"{w1:08X} {value & 0xFF:08X}"


class CWCheatCode:
    """
    CWCheat format encoder for Sony PSP.
    """

    @classmethod
    def format_write32(cls, address: int, value: int) -> str:
        w1 = (2 << 28) | (address & 0x0FFFFFFF)
        return f"_L 0x{w1:08X} 0x{value:08X}"

    @classmethod
    def format_write16(cls, address: int, value: int) -> str:
        w1 = (1 << 28) | (address & 0x0FFFFFFF)
        return f"_L 0x{w1:08X} 0x{value & 0xFFFF:08X}"

    @classmethod
    def format_write8(cls, address: int, value: int) -> str:
        w1 = (0 << 28) | (address & 0x0FFFFFFF)
        return f"_L 0x{w1:08X} 0x{value & 0xFF:08X}"


class GameSharkCode:
    """
    GameShark format encoder for Sony PlayStation 1 (PSX).
    """

    @classmethod
    def format_write16(cls, address: int, value: int) -> str:
        off = address & 0x00FFFFFF
        return f"80{off:06X} {value & 0xFFFF:04X}"

    @classmethod
    def format_write8(cls, address: int, value: int) -> str:
        off = address & 0x00FFFFFF
        return f"30{off:06X} {value & 0xFF:04X}"


class CheatCodeGenerator:
    """
    Universal cheat code and live patch generator.
    Allows testing patches, hooks, and string replacements live in emulators
    (Dolphin, DeSmuME, PCSX, PPSSPP) without repackaging the ROM/ISO.
    """

    def __init__(self, title: str = "MioROM Live Patch"):
        self.title = title
        self.entries: List[CheatEntry] = []

    def add_write_u32(self, address: int, value: int, comment: Optional[str] = None) -> "CheatCodeGenerator":
        self.entries.append(CheatEntry(entry_type="write32", address=address, value=value, comment=comment))
        return self

    def add_write_u16(self, address: int, value: int, comment: Optional[str] = None) -> "CheatCodeGenerator":
        self.entries.append(CheatEntry(entry_type="write16", address=address, value=value, comment=comment))
        return self

    def add_write_u8(self, address: int, value: int, comment: Optional[str] = None) -> "CheatCodeGenerator":
        self.entries.append(CheatEntry(entry_type="write8", address=address, value=value, comment=comment))
        return self

    def add_c2_asm(self, address: int, asm_bytes: bytes, comment: Optional[str] = None) -> "CheatCodeGenerator":
        self.entries.append(CheatEntry(entry_type="c2_asm", address=address, payload=asm_bytes, comment=comment))
        return self

    def add_bytes(self, address: int, data: bytes, comment: Optional[str] = None) -> "CheatCodeGenerator":
        """Write raw data bytes as 32-bit, 16-bit, and 8-bit writes."""
        p = 0
        n = len(data)
        while p + 4 <= n:
            val = struct.unpack(">I", data[p:p+4])[0]
            self.add_write_u32(address + p, val, comment=comment if p == 0 else None)
            p += 4
        if p + 2 <= n:
            val = struct.unpack(">H", data[p:p+2])[0]
            self.add_write_u16(address + p, val)
            p += 2
        if p < n:
            self.add_write_u8(address + p, data[p])
            p += 1
        return self

    def to_gecko(self, title: Optional[str] = None, game_id: Optional[str] = None) -> str:
        """
        Generate Gecko code text formatted for Dolphin / Gecko OS.
        """
        name = title or self.title
        lines = []
        if game_id:
            lines.append(f"[{game_id}]")
        lines.append(f"${name}")

        for e in self.entries:
            if e.comment:
                lines.append(f"# {e.comment}")
            if e.entry_type == "write32":
                lines.append(GeckoCode.format_write32(e.address, e.value))
            elif e.entry_type == "write16":
                lines.append(GeckoCode.format_write16(e.address, e.value))
            elif e.entry_type == "write8":
                lines.append(GeckoCode.format_write8(e.address, e.value))
            elif e.entry_type == "c2_asm":
                lines.extend(GeckoCode.format_c2_asm(e.address, e.payload))

        return "\n".join(lines)

    def to_gct(self) -> bytes:
        """
        Export Gecko codes as a raw binary .gct file.
        """
        gecko_txt = self.to_gecko()
        return GeckoCode.to_gct(gecko_txt.splitlines())

    def to_action_replay(self, title: Optional[str] = None) -> str:
        """
        Generate Action Replay code text formatted for NDS / GBA.
        """
        name = title or self.title
        lines = [f"::{name}"]
        for e in self.entries:
            if e.comment:
                lines.append(f"// {e.comment}")
            if e.entry_type == "write32":
                lines.append(ActionReplayCode.format_write32(e.address, e.value))
            elif e.entry_type == "write16":
                lines.append(ActionReplayCode.format_write16(e.address, e.value))
            elif e.entry_type == "write8":
                lines.append(ActionReplayCode.format_write8(e.address, e.value))
        lines.append("D2000000 00000000")
        return "\n".join(lines)

    def to_cwcheat(self, title: Optional[str] = None, game_id: Optional[str] = None) -> str:
        """
        Generate CWCheat code text formatted for PSP emulators (PPSSPP).
        """
        name = title or self.title
        lines = []
        if game_id:
            lines.append(f"_S {game_id}")
            lines.append(f"_G {name}")
        lines.append(f"_C0 {name}")
        for e in self.entries:
            if e.entry_type == "write32":
                lines.append(CWCheatCode.format_write32(e.address, e.value))
            elif e.entry_type == "write16":
                lines.append(CWCheatCode.format_write16(e.address, e.value))
            elif e.entry_type == "write8":
                lines.append(CWCheatCode.format_write8(e.address, e.value))
        return "\n".join(lines)

    def to_gameshark(self, title: Optional[str] = None) -> str:
        """
        Generate GameShark code text formatted for PSX (ePSXe, DuckStation).
        """
        name = title or self.title
        lines = [f"// {name}"]
        for e in self.entries:
            if e.entry_type in ("write32", "write16"):
                lines.append(GameSharkCode.format_write16(e.address, e.value))
            elif e.entry_type == "write8":
                lines.append(GameSharkCode.format_write8(e.address, e.value))
        return "\n".join(lines)

    @classmethod
    def from_diff(
        cls,
        orig_data: bytes,
        mod_data: bytes,
        base_address: int = 0x80000000,
        title: str = "Binary Diff Patch",
    ) -> "CheatCodeGenerator":
        """
        Compare original and modified binaries, generating live memory write
        codes for every detected byte difference.
        """
        gen = cls(title=title)
        n = min(len(orig_data), len(mod_data))
        i = 0

        while i < n:
            if orig_data[i] != mod_data[i]:
                start = i
                while i < n and orig_data[i] != mod_data[i]:
                    i += 1
                diff_chunk = mod_data[start:i]
                gen.add_bytes(base_address + start, diff_chunk)
            else:
                i += 1

        return gen
