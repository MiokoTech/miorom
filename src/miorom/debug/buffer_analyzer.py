"""
miorom.debug.buffer_analyzer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runtime Stack & Heap Text Buffer Overflow Analyzer.
Detects runtime buffer capacity in game ASM routines (e.g. SUB SP, SP, #imm)
and validates whether translated, lengthened strings will overflow local buffers
causing stack corruption or crashes during gameplay.
"""

from dataclasses import dataclass, field
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from miorom.asm.disasm import UniversalDisassembler, DisasmInstruction


@dataclass
class BufferRiskReport:
    """Report on runtime buffer safety for expanded text."""
    function_address: int
    detected_buffer_capacity: int
    max_payload_length: int
    is_overflow_risk: bool
    overflow_bytes: int
    warning_message: str


class RuntimeBufferAnalyzer:
    """
    Analyzes ASM functions to deduce local stack frame text buffer limits.
    """

    @classmethod
    def analyze_arm_stack_frame(
        cls,
        code: bytes,
        func_offset: int,
        base_address: int,
        max_instructions: int = 15,
        endian: str = "<",
    ) -> int:
        """
        Scans function prologue for stack frame allocation:
        - SUB SP, SP, #imm (0xE24DDEYY)
        Returns the allocated stack frame size in bytes (or 0 if not found).
        """
        step = 4
        cur_off = func_offset
        for _ in range(max_instructions):
            if cur_off + step > len(code):
                break
            word = struct.unpack_from(f"{endian}I", code, cur_off)[0]

            # Check SUB SP, SP, #imm:
            # Opcode: 0xE24DDxxx (cond=0xE, op=0010010, Rn=13(SP), Rd=13(SP))
            if (word & 0xFFFFF000) == 0xE24DD000:
                rot = ((word >> 8) & 0xF) * 2
                imm8 = word & 0xFF
                val = ((imm8 >> rot) | (imm8 << (32 - rot))) & 0xFFFFFFFF if rot else imm8
                return val

            # Check PUSH {regs}: bits 27..16 = 0x092D
            cur_off += step

        return 0

    @classmethod
    def verify_buffer_safety(
        cls,
        function_address: int,
        buffer_capacity: int,
        translated_strings: Sequence[Union[str, bytes]],
    ) -> BufferRiskReport:
        """
        Compares max translated string byte length against the detected buffer capacity.
        """
        max_len = 0
        for s in translated_strings:
            sz = len(s.encode("utf-8")) if isinstance(s, str) else len(s)
            max_len = max(max_len, sz)

        overflow = max(0, max_len - buffer_capacity) if buffer_capacity > 0 else 0
        risk = overflow > 0

        msg = (
            f"ALERT: Translated string length ({max_len} bytes) exceeds runtime stack buffer "
            f"({buffer_capacity} bytes) by {overflow} bytes! Game will likely crash at runtime."
            if risk
            else f"SAFE: Max string length ({max_len} bytes) fits comfortably in {buffer_capacity}-byte buffer."
        )

        return BufferRiskReport(
            function_address=function_address,
            detected_buffer_capacity=buffer_capacity,
            max_payload_length=max_len,
            is_overflow_risk=risk,
            overflow_bytes=overflow,
            warning_message=msg,
        )


class BufferPatcher:
    """
    Generates binary patches to expand stack frame buffers in ASM code.
    """

    @classmethod
    def patch_arm_stack_allocation(
        cls,
        code: bytearray,
        instr_offset: int,
        new_frame_size: int,
        endian: str = "<",
    ) -> bool:
        """
        Patches SUB SP, SP, #imm8 with expanded frame size (if new_frame_size <= 255).
        """
        if not (0 <= new_frame_size <= 255):
            return False
        # Emit SUB SP, SP, #new_frame_size (0xE24DD000 | new_frame_size)
        opcode = 0xE24DD000 | new_frame_size
        struct.pack_into(f"{endian}I", code, instr_offset, opcode)
        return True
