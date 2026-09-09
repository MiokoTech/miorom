from miorom.result import MioRomResult
from dataclasses import dataclass
from typing import Optional, Tuple, Union
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
        Supported arch values: 'ppc', 'powerpc', 'arm', 'thumb', 'mips', 'mips_le', 'mips_be', 'psx', 'n64', 'psp'.
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
        else:
            raise UnsupportedFormatError(f"Unsupported architecture: '{arch}'. Supported: 'ppc', 'arm', 'thumb', 'mips_le', 'mips_be'.")

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
        min_hook_size = 8 if "mips" in arch.lower() or arch.lower() in ("psx", "n64", "psp") else 4

        # Estimate required cave size: payload + orig + return branch (+ delay slot if mips)
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
