import pytest

from miorom.patch.slack import SlackSpaceManager, SlackBlock


def test_slack_space_manager_scan_and_allocate():
    # Buffer with two slack blocks:
    # 0x00..0x1F (32 bytes data)
    # 0x20..0x5F (64 bytes 0x00 slack)
    # 0x60..0x9F (64 bytes data)
    # 0xA0..0xDF (64 bytes 0xFF slack)
    buf = bytearray(b"\x12" * 32 + b"\x00" * 64 + b"\x34" * 64 + b"\xFF" * 64)

    mgr = SlackSpaceManager(buf, min_slack_size=32)
    assert len(mgr.slack_blocks) == 2
    assert mgr.slack_blocks[0].offset == 32
    assert mgr.slack_blocks[0].size == 64
    assert mgr.slack_blocks[0].filler_byte == 0x00

    assert mgr.slack_blocks[1].offset == 160
    assert mgr.slack_blocks[1].size == 64
    assert mgr.slack_blocks[1].filler_byte == 0xFF

    # Allocate 24 bytes (alignment=4) in first slack block
    alloc1 = mgr.allocate(24, alignment=4, allow_eof_growth=False)
    assert alloc1 == 32
    assert alloc1 % 4 == 0

    # Next allocation should take remaining space in first block (if fits) or move to second
    alloc2 = mgr.allocate(32, alignment=4, allow_eof_growth=False)
    assert alloc2 == 56 or alloc2 == 160


def test_slack_space_manager_inject_and_eof_growth():
    buf = bytearray(b"\xAA" * 64)
    mgr = SlackSpaceManager(buf, min_slack_size=16)
    assert len(mgr.slack_blocks) == 0

    # Injecting 32 bytes should grow at EOF with alignment
    payload = b"NEW_EXPANDED_PAYLOAD_HERE_12345"  # 32 bytes
    offset = mgr.inject_payload(payload, alignment=16, allow_eof_growth=True)

    assert offset >= 64
    assert offset % 16 == 0
    assert buf[offset : offset + len(payload)] == payload
