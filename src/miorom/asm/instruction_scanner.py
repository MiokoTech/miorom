"""
miorom.asm.instruction_scanner
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Static instruction-level analysis for discovering hardcoded pointers embedded
directly within executable machine code (PowerPC, MIPS, ARM).

Solves the classic ROM hacking problem where string and data addresses are
split across paired load instructions (e.g. lis/addi in PowerPC, lui/addiu in MIPS).
"""

import struct
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, Union


@dataclass
class CodePointer:
    """Represents a pointer embedded inside CPU instructions."""
    arch: str  # "powerpc", "mips", "arm"
    target_address: int
    lis_offset: int
    addi_offset: int
    reg: int
    is_signed_add: bool

    @property
    def target_hex(self) -> str:
        return f"0x{self.target_address:08X}"

    def calculate_new_pair(self, new_target: int) -> Tuple[int, int]:
        """
        Calculate new 16-bit immediate values (hi, lo) for repointing to new_target.
        Takes into account sign-extension arithmetic for addi/addiu.
        """
        lo = new_target & 0xFFFF
        hi = (new_target >> 16) & 0xFFFF
        if self.is_signed_add and lo >= 0x8000:
            hi = (hi + 1) & 0xFFFF
        return hi, lo

    def patch(self, buffer: bytearray, new_target: int, endian: str = ">") -> None:
        """Patch the paired instructions in the buffer in-place to point to new_target."""
        hi, lo = self.calculate_new_pair(new_target)

        # Patch lis / lui (upper 16-bit immediate)
        fmt = f"{endian}H"
        struct.pack_into(fmt, buffer, self.lis_offset + 2, hi)
        # Patch addi / addiu / ori (lower 16-bit immediate)
        struct.pack_into(fmt, buffer, self.addi_offset + 2, lo)


class PPCInstructionScanner:
    """
    Scanner for PowerPC 750CL / Gekko / Broadway machine code (Wii / GameCube).
    Detects paired 'lis' (load immediate shifted) and 'addi' / 'ori' instructions.
    """

    @classmethod
    def find_split_pointers(
        cls,
        code: bytes,
        min_target: int = 0x80000000,
        max_target: int = 0x81800000,
        base_address: int = 0x80000000,
        max_lookahead: int = 8,
        endian: str = ">",
    ) -> List[CodePointer]:
        results: List[CodePointer] = []
        n = len(code) - 4
        fmt = f"{endian}I"

        for i in range(0, n, 4):
            insn1 = struct.unpack_from(fmt, code, i)[0]
            op1 = insn1 >> 26
            ra1 = (insn1 >> 16) & 0x1F

            # Check for: lis rD, imm16 (opcode 15, rA == 0)
            if op1 == 15 and ra1 == 0:
                rd1 = (insn1 >> 21) & 0x1F
                imm_hi = (insn1 & 0xFFFF) << 16

                # Search forward up to max_lookahead instructions for matching addi/ori with same register
                for j in range(1, max_lookahead + 1):
                    off2 = i + (j * 4)
                    if off2 + 4 > len(code):
                        break

                    insn2 = struct.unpack_from(fmt, code, off2)[0]
                    op2 = insn2 >> 26
                    rd2 = (insn2 >> 21) & 0x1F
                    ra2 = (insn2 >> 16) & 0x1F
                    imm2 = insn2 & 0xFFFF

                    # addi rD, rA, simm16 (opcode 14)
                    if op2 == 14 and ra2 == rd1:
                        lo_signed = imm2 if imm2 < 0x8000 else imm2 - 0x10000
                        resolved = (imm_hi + lo_signed) & 0xFFFFFFFF
                        if min_target <= resolved <= max_target:
                            results.append(CodePointer(
                                arch="powerpc",
                                target_address=resolved,
                                lis_offset=i,
                                addi_offset=off2,
                                reg=rd1,
                                is_signed_add=True,
                            ))
                        break

                    # ori rD, rA, uimm16 (opcode 24)
                    elif op2 == 24 and ra2 == rd1:
                        resolved = imm_hi | imm2
                        if min_target <= resolved <= max_target:
                            results.append(CodePointer(
                                arch="powerpc",
                                target_address=resolved,
                                lis_offset=i,
                                addi_offset=off2,
                                reg=rd1,
                                is_signed_add=False,
                            ))
                        break

                    # If register rd1 is clobbered by another instruction before addi/ori, stop search
                    if rd2 == rd1:
                        break

        return results


class MIPSInstructionScanner:
    """
    Scanner for MIPS R3000A / VR4300 machine code (PS1 / N64).
    Detects paired 'lui' (load upper immediate) and 'addiu' / 'ori' instructions.
    """

    @classmethod
    def find_split_pointers(
        cls,
        code: bytes,
        min_target: int = 0x80000000,
        max_target: int = 0x80400000,
        max_lookahead: int = 8,
        endian: str = ">",
    ) -> List[CodePointer]:
        results: List[CodePointer] = []
        n = len(code) - 4
        fmt = f"{endian}I"

        for i in range(0, n, 4):
            insn1 = struct.unpack_from(fmt, code, i)[0]
            op1 = insn1 >> 26
            rs1 = (insn1 >> 21) & 0x1F

            # lui $rt, imm16 (opcode 15, rs == 0)
            if op1 == 15 and rs1 == 0:
                rt1 = (insn1 >> 16) & 0x1F
                imm_hi = (insn1 & 0xFFFF) << 16

                for j in range(1, max_lookahead + 1):
                    off2 = i + (j * 4)
                    if off2 + 4 > len(code):
                        break

                    insn2 = struct.unpack_from(fmt, code, off2)[0]
                    op2 = insn2 >> 26
                    rs2 = (insn2 >> 21) & 0x1F
                    rt2 = (insn2 >> 16) & 0x1F
                    imm2 = insn2 & 0xFFFF

                    # addiu $rt, $rs, simm16 (opcode 9)
                    if op2 == 9 and rs2 == rt1:
                        lo_signed = imm2 if imm2 < 0x8000 else imm2 - 0x10000
                        resolved = (imm_hi + lo_signed) & 0xFFFFFFFF
                        if min_target <= resolved <= max_target:
                            results.append(CodePointer(
                                arch="mips",
                                target_address=resolved,
                                lis_offset=i,
                                addi_offset=off2,
                                reg=rt1,
                                is_signed_add=True,
                            ))
                        break

                    # ori $rt, $rs, uimm16 (opcode 13)
                    elif op2 == 13 and rs2 == rt1:
                        resolved = imm_hi | imm2
                        if min_target <= resolved <= max_target:
                            results.append(CodePointer(
                                arch="mips",
                                target_address=resolved,
                                lis_offset=i,
                                addi_offset=off2,
                                reg=rt1,
                                is_signed_add=False,
                            ))
                        break

                    if rt2 == rt1:
                        break

        return results


@dataclass
class ARMLiteralPointer:
    """Represents a pointer loaded via PC-relative literal pool (LDR Rd, [PC, #imm])."""
    insn_offset: int
    insn_address: int
    pool_offset: int
    pool_address: int
    target_address: int
    reg: int
    mode: str = "arm"  # "arm" (32-bit) or "thumb" (16-bit)

    @property
    def target_hex(self) -> str:
        return f"0x{self.target_address:08X}"

    def patch(self, buffer: bytearray, new_target: int, endian: str = "<") -> None:
        """Patch the literal pool entry in the buffer in-place."""
        fmt = f"{endian}I"
        struct.pack_into(fmt, buffer, self.pool_offset, new_target)
        self.target_address = new_target


@dataclass
class ARMMovPairPointer:
    """Represents a 32-bit immediate loaded via paired movw / movt instructions (ARMv7)."""
    movw_offset: int
    movt_offset: int
    movw_address: int
    movt_address: int
    target_address: int
    reg: int

    @property
    def target_hex(self) -> str:
        return f"0x{self.target_address:08X}"

    def patch(self, buffer: bytearray, new_target: int, endian: str = "<") -> None:
        """Patch the movw and movt instructions in the buffer in-place."""
        lo = new_target & 0xFFFF
        hi = (new_target >> 16) & 0xFFFF
        fmt = f"{endian}I"

        # movw: imm4 at [19:16], imm12 at [11:0]
        movw_val = struct.unpack_from(fmt, buffer, self.movw_offset)[0]
        imm4_lo = (lo >> 12) & 0xF
        imm12_lo = lo & 0xFFF
        movw_val = (movw_val & 0xFFF0F000) | (imm4_lo << 16) | imm12_lo
        struct.pack_into(fmt, buffer, self.movw_offset, movw_val)

        # movt: imm4 at [19:16], imm12 at [11:0]
        movt_val = struct.unpack_from(fmt, buffer, self.movt_offset)[0]
        imm4_hi = (hi >> 12) & 0xF
        imm12_hi = hi & 0xFFF
        movt_val = (movt_val & 0xFFF0F000) | (imm4_hi << 16) | imm12_hi
        struct.pack_into(fmt, buffer, self.movt_offset, movt_val)

        self.target_address = new_target


class ARMInstructionScanner:
    """
    Scanner for ARM (ARMv4T / ARMv5TE / ARMv7) and Thumb machine code (GBA / NDS / 3DS).
    Detects:
    1. PC-relative literal pool loads (LDR Rd, [PC, #imm]) in ARM and Thumb modes.
    2. Paired 'movw' and 'movt' instructions in ARMv7 mode.
    3. Cross-references (XREFs) to memory addresses from code.
    """

    @classmethod
    def find_literal_pointers(
        cls,
        code: bytes,
        min_target: int = 0x02000000,
        max_target: int = 0x02400000,
        base_address: int = 0x02000000,
        mode: str = "arm",
        endian: str = "<",
    ) -> List[ARMLiteralPointer]:
        """
        Scans code for PC-relative literal pool loads.
        mode can be "arm" (32-bit instructions) or "thumb" (16-bit instructions).
        """
        results: List[ARMLiteralPointer] = []
        fmt32 = f"{endian}I"
        code_len = len(code)

        if mode.lower() == "thumb":
            fmt16 = f"{endian}H"
            for i in range(0, code_len - 1, 2):
                insn = struct.unpack_from(fmt16, code, i)[0]
                # Thumb LDR Rd, [PC, #imm8]: 0100 1 Rd(3) imm8(8) -> (insn & 0xF800) == 0x4800
                if (insn & 0xF800) == 0x4800:
                    rd = (insn >> 8) & 0x7
                    imm8 = insn & 0xFF
                    insn_addr = base_address + i
                    # In Thumb, PC = (insn_addr + 4) & ~3
                    effective_pc = (insn_addr + 4) & ~3
                    pool_addr = effective_pc + (imm8 * 4)
                    pool_off = pool_addr - base_address
                    if 0 <= pool_off <= code_len - 4:
                        target = struct.unpack_from(fmt32, code, pool_off)[0]
                        if min_target <= target <= max_target:
                            results.append(ARMLiteralPointer(
                                insn_offset=i,
                                insn_address=insn_addr,
                                pool_offset=pool_off,
                                pool_address=pool_addr,
                                target_address=target,
                                reg=rd,
                                mode="thumb",
                            ))
        else:
            # ARM 32-bit mode
            for i in range(0, code_len - 3, 4):
                insn = struct.unpack_from(fmt32, code, i)[0]
                # ARM LDR Rd, [PC, #+/-imm12]:
                # bits [27:25] == 010 (immediate data transfer)
                # bit 22 == 0 (word transfer)
                # bit 20 == 1 (load)
                # bits [19:16] == 1111 (Rn == PC)
                # Mask: 0x0E5F0000, value: 0x041F0000
                if (insn & 0x0E5F0000) == 0x041F0000:
                    p = (insn >> 24) & 1
                    u = (insn >> 23) & 1
                    rd = (insn >> 12) & 0xF
                    imm12 = insn & 0xFFF
                    insn_addr = base_address + i
                    # In ARM, PC = insn_addr + 8
                    effective_pc = insn_addr + 8
                    pool_addr = (effective_pc + imm12) if u else (effective_pc - imm12)
                    pool_off = pool_addr - base_address
                    if 0 <= pool_off <= code_len - 4:
                        target = struct.unpack_from(fmt32, code, pool_off)[0]
                        if min_target <= target <= max_target:
                            results.append(ARMLiteralPointer(
                                insn_offset=i,
                                insn_address=insn_addr,
                                pool_offset=pool_off,
                                pool_address=pool_addr,
                                target_address=target,
                                reg=rd,
                                mode="arm",
                            ))

        return results

    @classmethod
    def find_mov_pairs(
        cls,
        code: bytes,
        min_target: int = 0x02000000,
        max_target: int = 0x02400000,
        base_address: int = 0x02000000,
        max_lookahead: int = 8,
        endian: str = "<",
    ) -> List[ARMMovPairPointer]:
        """
        Scans ARM code for paired 'movw' and 'movt' instructions loading a 32-bit address (ARMv7).
        """
        results: List[ARMMovPairPointer] = []
        fmt = f"{endian}I"
        code_len = len(code)

        for i in range(0, code_len - 3, 4):
            insn1 = struct.unpack_from(fmt, code, i)[0]
            # movw Rd, #imm16: bits [27:20] == 0011 0000 -> (insn & 0x0FF00000) == 0x03000000
            if (insn1 & 0x0FF00000) == 0x03000000:
                rd1 = (insn1 >> 12) & 0xF
                imm4_1 = (insn1 >> 16) & 0xF
                imm12_1 = insn1 & 0xFFF
                imm_lo = (imm4_1 << 12) | imm12_1

                for j in range(1, max_lookahead + 1):
                    off2 = i + (j * 4)
                    if off2 + 4 > code_len:
                        break
                    insn2 = struct.unpack_from(fmt, code, off2)[0]
                    # movt Rd, #imm16: bits [27:20] == 0011 0100 -> (insn & 0x0FF00000) == 0x03400000
                    if (insn2 & 0x0FF00000) == 0x03400000:
                        rd2 = (insn2 >> 12) & 0xF
                        if rd2 == rd1:
                            imm4_2 = (insn2 >> 16) & 0xF
                            imm12_2 = insn2 & 0xFFF
                            imm_hi = (imm4_2 << 12) | imm12_2
                            resolved = (imm_hi << 16) | imm_lo
                            if min_target <= resolved <= max_target:
                                results.append(ARMMovPairPointer(
                                    movw_offset=i,
                                    movt_offset=off2,
                                    movw_address=base_address + i,
                                    movt_address=base_address + off2,
                                    target_address=resolved,
                                    reg=rd1,
                                ))
                            break
                    # If register is overwritten before movt, break
                    if ((insn2 >> 12) & 0xF) == rd1:
                        break

        return results

    @classmethod
    def find_code_pointers(
        cls,
        code: bytes,
        min_target: int = 0x02000000,
        max_target: int = 0x02400000,
        base_address: int = 0x02000000,
        mode: str = "arm",
        endian: str = "<",
    ) -> List[Union[ARMLiteralPointer, ARMMovPairPointer]]:
        """Unified scan discovering all ARM code-embedded pointers (literal pools + movw/movt pairs)."""
        literals = cls.find_literal_pointers(code, min_target, max_target, base_address, mode, endian)
        if mode.lower() == "arm":
            movs = cls.find_mov_pairs(code, min_target, max_target, base_address, endian=endian)
            all_ptrs: List[Union[ARMLiteralPointer, ARMMovPairPointer]] = list(literals) + list(movs)
            all_ptrs.sort(key=lambda p: getattr(p, "insn_address", getattr(p, "movw_address", 0)))
            return all_ptrs
        return literals

    @classmethod
    def find_xrefs(
        cls,
        code: bytes,
        target_address: int,
        base_address: int = 0x02000000,
        mode: str = "arm",
        endian: str = "<",
    ) -> List[int]:
        """
        Finds all instruction addresses that reference target_address in code.
        """
        ptrs = cls.find_code_pointers(
            code,
            min_target=target_address,
            max_target=target_address,
            base_address=base_address,
            mode=mode,
            endian=endian,
        )
        addrs = []
        for p in ptrs:
            if isinstance(p, ARMLiteralPointer):
                addrs.append(p.insn_address)
            elif isinstance(p, ARMMovPairPointer):
                addrs.append(p.movw_address)
        return sorted(set(addrs))


class UniversalInstructionScanner:
    """
    Unified architectural facade for instruction-level pointer discovery across
    ARM (GBA/NDS/3DS), PowerPC (GameCube/Wii), and MIPS (PS1/N64).
    """

    @classmethod
    def find_code_pointers(
        cls,
        code: bytes,
        arch: str = "arm",
        min_target: int = 0x02000000,
        max_target: int = 0x02400000,
        base_address: int = 0x02000000,
        mode: str = "arm",
        endian: Optional[str] = None,
    ) -> List[Any]:
        """
        Discovers code-embedded pointers across ARM, Thumb, PowerPC, or MIPS machine code.
        """
        arch_norm = arch.lower()
        if arch_norm in ("arm", "thumb"):
            end = endian or "<"
            m = "thumb" if arch_norm == "thumb" else mode
            return ARMInstructionScanner.find_code_pointers(
                code,
                min_target=min_target,
                max_target=max_target,
                base_address=base_address,
                mode=m,
                endian=end,
            )
        elif arch_norm in ("ppc", "powerpc"):
            end = endian or ">"
            return PPCInstructionScanner.find_split_pointers(
                code,
                min_target=min_target,
                max_target=max_target,
                base_address=base_address,
                endian=end,
            )
        elif arch_norm == "mips":
            end = endian or ">"
            return MIPSInstructionScanner.find_split_pointers(
                code,
                min_target=min_target,
                max_target=max_target,
                endian=end,
            )
        else:
            raise ValueError(f"Unsupported architecture: '{arch}'. Choose 'arm', 'thumb', 'ppc', or 'mips'.")

    @classmethod
    def find_xrefs(
        cls,
        code: bytes,
        target_address: int,
        arch: str = "arm",
        base_address: int = 0x02000000,
        mode: str = "arm",
        endian: Optional[str] = None,
    ) -> List[int]:
        """
        Finds cross-references (instruction addresses) targeting target_address across architectures.
        """
        arch_norm = arch.lower()
        if arch_norm in ("arm", "thumb"):
            end = endian or "<"
            m = "thumb" if arch_norm == "thumb" else mode
            return ARMInstructionScanner.find_xrefs(
                code,
                target_address=target_address,
                base_address=base_address,
                mode=m,
                endian=end,
            )
        else:
            ptrs = cls.find_code_pointers(
                code,
                arch=arch,
                min_target=target_address,
                max_target=target_address,
                base_address=base_address,
                mode=mode,
                endian=endian,
            )
            addrs = []
            for p in ptrs:
                if hasattr(p, "lis_offset"):
                    addrs.append(base_address + p.lis_offset)
                elif hasattr(p, "insn_address"):
                    addrs.append(p.insn_address)
            return sorted(set(addrs))


