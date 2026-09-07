import struct
import pytest
from miorom.debug.buffer_analyzer import (
    RuntimeBufferAnalyzer,
    BufferRiskReport,
    BufferPatcher,
)


def test_analyze_arm_stack_frame():
    # Build a small ARM function prologue:
    # 0x00: PUSH {r4, lr}        (0xE92D4010)
    # 0x04: SUB SP, SP, #64      (0xE24DD040)
    # 0x08: MOV r0, #0           (0xE3A00000)
    code = bytearray()
    code.extend(struct.pack("<I", 0xE92D4010))
    code.extend(struct.pack("<I", 0xE24DD040))
    code.extend(struct.pack("<I", 0xE3A00000))

    frame_size = RuntimeBufferAnalyzer.analyze_arm_stack_frame(
        code=bytes(code),
        func_offset=0,
        base_address=0x02000000,
        max_instructions=10,
    )
    assert frame_size == 64


def test_buffer_safety_verification():
    # Safe case: max string is 20 bytes, capacity 64
    safe_strings = ["Halo!", "Selamat Pagi!", "Dunia Baru"]
    report_safe = RuntimeBufferAnalyzer.verify_buffer_safety(
        function_address=0x02001000,
        buffer_capacity=64,
        translated_strings=safe_strings,
    )
    assert not report_safe.is_overflow_risk
    assert report_safe.overflow_bytes == 0
    assert "SAFE" in report_safe.warning_message

    # Overflow case: string is 85 bytes, capacity 64
    long_string = "Ini adalah terjemahan bahasa Indonesia yang sangat panjang sekali melebihi buffer stack!"
    assert len(long_string.encode("utf-8")) > 64

    report_overflow = RuntimeBufferAnalyzer.verify_buffer_safety(
        function_address=0x02001000,
        buffer_capacity=64,
        translated_strings=[long_string],
    )
    assert report_overflow.is_overflow_risk
    assert report_overflow.overflow_bytes == len(long_string.encode("utf-8")) - 64
    assert "ALERT" in report_overflow.warning_message


def test_buffer_patcher():
    code = bytearray()
    code.extend(struct.pack("<I", 0xE24DD040))  # SUB SP, SP, #64

    # Patch from 64 to 128 bytes
    success = BufferPatcher.patch_arm_stack_allocation(
        code=code,
        instr_offset=0,
        new_frame_size=128,
    )
    assert success is True

    # Verify updated opcode reads as 128 bytes
    updated_frame = RuntimeBufferAnalyzer.analyze_arm_stack_frame(
        code=bytes(code),
        func_offset=0,
        base_address=0,
    )
    assert updated_frame == 128

    # Test invalid frame size (> 255)
    fail = BufferPatcher.patch_arm_stack_allocation(
        code=code,
        instr_offset=0,
        new_frame_size=300,
    )
    assert fail is False
