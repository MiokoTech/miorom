import struct
from dataclasses import dataclass
from typing import Optional, Tuple, Union
from miorom.result import MioRomResult
from miorom.asm.branch import ARMBranch, ThumbBranch, PowerPCBranch, MIPSBranch
from miorom.asm.codecave import CodeCaveFinder


from miorom.errors import ParseError, RelocationError, UnsupportedFormatError
@dataclass
class HookRecord(MioRomResult):
    arch: str
    hook_ram_addr: int
    cave_ram_addr: int
    hook_bytes: bytes
    cave_bytes: bytes
    hook_file_offset: Optional[int] = None
    cave_file_offset: Optional[int] = None

    @property
    def hook_size(self) -> int:
        return len(self.hook_bytes)

    @property
    def cave_size(self) -> int:
        return len(self.cave_bytes)


class TrampolineHook:
    """
    Generates function hooks and trampolines across multiple architectures:
    ARM (GBA/NDS), Thumb (GBA/NDS), PowerPC (Wii/GameCube), and MIPS (PSX/N64/PSP).

    Replaces instruction(s) at the hook site with a branch/jump to custom payload
    code in a code cave, executes the payload, runs displaced instruction(s),
    and branches cleanly back to the game routine.
    """

    @classmethod
    def create_arm_hook(
        cls,
        hook_ram_addr: int,
        original_instr_bytes: bytes,
        custom_payload_bytes: bytes,
        cave_ram_addr: int,
    ) -> Tuple[bytes, bytes]:
        """
        Creates a 32-bit ARM function hook (GBA / NDS).
        Returns:
            hook_bytes: 4-byte B instruction to write at hook_ram_addr.
            cave_bytes: Custom payload + original displaced instruction + return branch.
        """
        if len(original_instr_bytes) != 4:
            raise RelocationError("ARM original instruction must be exactly 4 bytes.")

        hook_bytes = ARMBranch.encode_b(source_pc=hook_ram_addr, target_addr=cave_ram_addr)

        cave_bytes = bytearray(custom_payload_bytes)
        cave_bytes.extend(original_instr_bytes)

        cur_cave_pc = cave_ram_addr + len(cave_bytes)
        ret_branch = ARMBranch.encode_b(source_pc=cur_cave_pc, target_addr=hook_ram_addr + 4)
        cave_bytes.extend(ret_branch)

        return hook_bytes, bytes(cave_bytes)

    @classmethod
    def create_thumb_hook(
        cls,
        hook_ram_addr: int,
        original_instr_bytes: bytes,
        custom_payload_bytes: bytes,
        cave_ram_addr: int,
    ) -> Tuple[bytes, bytes]:
        """
        Creates a 16-bit Thumb function hook (GBA / NDS).
        Returns (hook_bytes, cave_bytes).
        """
        if len(original_instr_bytes) != 2:
            raise RelocationError("Thumb original instruction must be exactly 2 bytes.")

        hook_bytes = ThumbBranch.encode_b(source_pc=hook_ram_addr, target_addr=cave_ram_addr)

        cave_bytes = bytearray(custom_payload_bytes)
        cave_bytes.extend(original_instr_bytes)

        cur_cave_pc = cave_ram_addr + len(cave_bytes)
        ret_branch = ThumbBranch.encode_b(source_pc=cur_cave_pc, target_addr=hook_ram_addr + 2)
        cave_bytes.extend(ret_branch)

        return hook_bytes, bytes(cave_bytes)

    @classmethod
    def create_ppc_hook(
        cls,
        hook_ram_addr: int,
        original_instr_bytes: bytes,
        custom_payload_bytes: bytes,
        cave_ram_addr: int,
        link: bool = False,
    ) -> Tuple[bytes, bytes]:
        """
        Creates a 32-bit PowerPC function hook (Nintendo GameCube / Wii).
        Returns (hook_bytes, cave_bytes).
        """
        if len(original_instr_bytes) != 4:
            raise RelocationError("PowerPC original instruction must be exactly 4 bytes.")

        hook_bytes = PowerPCBranch.encode_b(
            source_pc=hook_ram_addr,
            target_addr=cave_ram_addr,
            link=link
        )

        cave_bytes = bytearray(custom_payload_bytes)
        cave_bytes.extend(original_instr_bytes)

        cur_cave_pc = cave_ram_addr + len(cave_bytes)
        ret_branch = PowerPCBranch.encode_b(
            source_pc=cur_cave_pc,
            target_addr=hook_ram_addr + 4,
            link=False
        )
        cave_bytes.extend(ret_branch)

        return hook_bytes, bytes(cave_bytes)

    @classmethod
    def create_mips_hook(
        cls,
        hook_ram_addr: int,
        original_instr_bytes: bytes,
        custom_payload_bytes: bytes,
        cave_ram_addr: int,
        endian: str = "<",
    ) -> Tuple[bytes, bytes]:
        """
        Creates a 32-bit MIPS function hook with branch delay-slot handling (PSX / N64 / PSP).
        MIPS requires an 8-byte hook site (jump + delay slot).
        Returns (hook_bytes, cave_bytes).
        """
        if len(original_instr_bytes) not in (4, 8):
            raise ParseError("MIPS original instructions must be 4 or 8 bytes (instruction + delay slot).")

        # Encode jump to cave
        j_instr = MIPSBranch.encode_j(source_pc=hook_ram_addr, target_addr=cave_ram_addr, endian=endian)
        nop = MIPSBranch.nop(endian=endian)

        hook_bytes = j_instr + nop

        cave_bytes = bytearray(custom_payload_bytes)
        # Execute original displaced instruction(s)
        cave_bytes.extend(original_instr_bytes)

        # Return jump back to hook_ram_addr + len(original_instr_bytes)
        return_target = hook_ram_addr + max(8, len(original_instr_bytes))
        cur_cave_pc = cave_ram_addr + len(cave_bytes)
        ret_j = MIPSBranch.encode_j(source_pc=cur_cave_pc, target_addr=return_target, endian=endian)
        cave_bytes.extend(ret_j)
        cave_bytes.extend(nop)  # Delay slot for return jump

        return hook_bytes, bytes(cave_bytes)

    @classmethod
    def create_6502_hook(
        cls,
        hook_ram_addr: int,
        original_instr_bytes: bytes,
        custom_payload_bytes: bytes,
        cave_ram_addr: int,
    ) -> Tuple[bytes, bytes]:
        """
        Creates an 8-bit MOS 6502 function hook (NES).
        Requires at least 3 bytes at hook site for JMP $xxxx (0x4C).
        Returns (hook_bytes, cave_bytes).
        """
        if len(original_instr_bytes) < 3:
            raise RelocationError("MOS 6502 hook site must be at least 3 bytes for JMP instruction.")

        hook_bytes = b"\x4C" + struct.pack("<H", cave_ram_addr & 0xFFFF)
        if len(original_instr_bytes) > 3:
            hook_bytes += b"\xEA" * (len(original_instr_bytes) - 3)

        cave_bytes = bytearray(custom_payload_bytes)
        cave_bytes.extend(original_instr_bytes)

        return_target = (hook_ram_addr + len(original_instr_bytes)) & 0xFFFF
        cave_bytes.append(0x4C)
        cave_bytes.extend(struct.pack("<H", return_target))

        return hook_bytes, bytes(cave_bytes)

    @classmethod
    def create_snes_hook(
        cls,
        hook_ram_addr: int,
        original_instr_bytes: bytes,
        custom_payload_bytes: bytes,
        cave_ram_addr: int,
        mode: str = "jml",
    ) -> Tuple[bytes, bytes]:
        """
        Creates a 16-bit W65C816 function hook (SNES).
        Requires at least 4 bytes at hook site for JML (0x5C) or JSL (0x22).
        Returns (hook_bytes, cave_bytes).
        """
        if len(original_instr_bytes) < 4:
            raise RelocationError("SNES (W65C816) hook site must be at least 4 bytes for JML/JSL instruction.")

        mode_norm = mode.lower()
        opcode = 0x22 if mode_norm == "jsl" else 0x5C

        target_24 = struct.pack("<I", cave_ram_addr & 0xFFFFFF)[:3]
        hook_bytes = bytes([opcode]) + target_24
        if len(original_instr_bytes) > 4:
            hook_bytes += b"\xEA" * (len(original_instr_bytes) - 4)

        cave_bytes = bytearray(custom_payload_bytes)
        cave_bytes.extend(original_instr_bytes)

        if mode_norm == "jsl":
            cave_bytes.append(0x6B)  # RTL
        else:
            return_target = (hook_ram_addr + len(original_instr_bytes)) & 0xFFFFFF
            cave_bytes.append(0x5C)  # JML
            cave_bytes.extend(struct.pack("<I", return_target)[:3])

        return hook_bytes, bytes(cave_bytes)

    @classmethod
    def create_hook(
        cls,
        arch: str,
        hook_ram_addr: int,
        original_instr_bytes: bytes,
        custom_payload_bytes: bytes,
        cave_ram_addr: int,
        endian: Optional[str] = None,
    ) -> Tuple[bytes, bytes]:
        """
        Unified hook constructor.
        Supported arch values: 'ppc', 'arm', 'thumb', 'mips', '6502', 'snes', etc.
        """
        arch_norm = arch.lower()
        if arch_norm in ("ppc", "powerpc", "wii", "gc", "gamecube"):
            return cls.create_ppc_hook(hook_ram_addr, original_instr_bytes, custom_payload_bytes, cave_ram_addr)
        elif arch_norm in ("arm", "arm32", "gba_arm", "nds_arm"):
            return cls.create_arm_hook(hook_ram_addr, original_instr_bytes, custom_payload_bytes, cave_ram_addr)
        elif arch_norm in ("thumb", "arm_thumb", "gba_thumb"):
            return cls.create_thumb_hook(hook_ram_addr, original_instr_bytes, custom_payload_bytes, cave_ram_addr)
        elif arch_norm in ("mips", "mips_le", "psx", "psp"):
            end = endian or "<"
            return cls.create_mips_hook(hook_ram_addr, original_instr_bytes, custom_payload_bytes, cave_ram_addr, endian=end)
        elif arch_norm in ("mips_be", "n64"):
            end = endian or ">"
            return cls.create_mips_hook(hook_ram_addr, original_instr_bytes, custom_payload_bytes, cave_ram_addr, endian=end)
        elif arch_norm in ("6502", "nes"):
            return cls.create_6502_hook(hook_ram_addr, original_instr_bytes, custom_payload_bytes, cave_ram_addr)
        elif arch_norm in ("snes", "65816", "w65c816"):
            return cls.create_snes_hook(hook_ram_addr, original_instr_bytes, custom_payload_bytes, cave_ram_addr)
        else:
            raise UnsupportedFormatError(f"Unsupported architecture: '{arch}'.")

    @classmethod
    def auto_hook(
        cls,
        data: Union[bytearray, bytes],
        hook_file_offset: int,
        hook_ram_addr: int,
        original_instr_bytes: bytes,
        custom_payload_bytes: bytes,
        arch: str = "ppc",
        cave_file_offset: Optional[int] = None,
        cave_ram_addr: Optional[int] = None,
        ram_base_offset: int = 0,
        endian: Optional[str] = None,
    ) -> Tuple[bytearray, HookRecord]:
        """
        Automatically locates or uses a code cave, builds the trampoline hook,
        patches the buffer in-place, and returns (patched_buffer, hook_record).
        """
        buf = bytearray(data)
        arch_l = arch.lower()
        if "mips" in arch_l or arch_l in ("psx", "n64", "psp"):
            min_hook_size = 8
        elif arch_l in ("6502", "nes"):
            min_hook_size = 3
        elif arch_l in ("thumb", "arm_thumb", "gba_thumb"):
            min_hook_size = 2
        else:
            min_hook_size = 4

        # Estimate required cave size
        est_cave_size = len(custom_payload_bytes) + len(original_instr_bytes) + 8

        if cave_file_offset is None:
            # Find a code cave in the binary
            caves = CodeCaveFinder.find_caves(bytes(buf), min_size=est_cave_size)
            if not caves:
                raise RuntimeError(f"Could not locate an unused code cave of size >= {est_cave_size} bytes.")
            cave_file_offset = caves[0].offset

        if cave_ram_addr is None:
            cave_ram_addr = cave_file_offset + ram_base_offset

        hook_bytes, cave_bytes = cls.create_hook(
            arch=arch,
            hook_ram_addr=hook_ram_addr,
            original_instr_bytes=original_instr_bytes,
            custom_payload_bytes=custom_payload_bytes,
            cave_ram_addr=cave_ram_addr,
            endian=endian,
        )

        # Write hook
        buf[hook_file_offset:hook_file_offset + len(hook_bytes)] = hook_bytes

        # Write cave
        buf[cave_file_offset:cave_file_offset + len(cave_bytes)] = cave_bytes

        record = HookRecord(
            arch=arch,
            hook_ram_addr=hook_ram_addr,
            cave_ram_addr=cave_ram_addr,
            hook_bytes=hook_bytes,
            cave_bytes=cave_bytes,
            hook_file_offset=hook_file_offset,
            cave_file_offset=cave_file_offset,
        )

        return buf, record
