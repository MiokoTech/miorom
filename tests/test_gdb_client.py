import pytest

from miorom.debug.gdb_client import GDBEmulatorClient, GDBProtocolMock, StopReason


def test_gdb_client_memory_read_write():
    client = GDBEmulatorClient.with_mock(ram_size=1024 * 1024, base_address=0x02000000)

    # Write bytes to RAM at 0x02001000
    test_data = b"\x12\x34\x56\x78\xAA\xBB\xCC\xDD"
    client.write_bytes(0x02001000, test_data)

    # Read bytes back
    read_back = client.read_bytes(0x02001000, len(test_data))
    assert read_back == test_data

    # Read and write string
    client.write_string(0x02002000, "Live Dialogue Test", encoding="utf-8")
    str_read = client.read_string(0x02002000, encoding="utf-8")
    assert str_read == "Live Dialogue Test"


def test_gdb_client_registers():
    client = GDBEmulatorClient.with_mock(ram_size=1024 * 1024, base_address=0x02000000)

    # Write R0 = 0x12345678
    client.write_register(0, 0x12345678)
    r0 = client.read_register(0)
    assert r0 == 0x12345678

    # Write PC (R15) = 0x02005000
    client.write_register(15, 0x02005000)
    pc = client.read_register(15)
    assert pc == 0x02005000


def test_gdb_client_watchpoints_and_halt():
    client = GDBEmulatorClient.with_mock(ram_size=1024 * 1024, base_address=0x02000000)

    # Set write watchpoint on text buffer at 0x0205BA80
    ok = client.set_watchpoint(0x0205BA80, size=4, kind="write")
    assert ok is True

    # Continue execution until halt
    stop = client.continue_execution()
    assert stop.signal == 5
    assert stop.reason == "watchpoint_hit"
    assert stop.address == 0x0205BA80

    # Remove watchpoint
    ok_rm = client.remove_watchpoint(0x0205BA80, size=4, kind="write")
    assert ok_rm is True
