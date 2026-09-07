import pytest
import struct
from miorom.save.checksum import SaveChecksum
from miorom.save.slots import DualSlotSave


def test_save_checksum_algorithms():
    data = b"MioROM Save Game Integrity Test 1234567890"

    crc_ccitt = SaveChecksum.crc16_ccitt(data)
    assert isinstance(crc_ccitt, int) and 0 <= crc_ccitt <= 0xFFFF

    crc_xmodem = SaveChecksum.crc16_xmodem(data)
    assert isinstance(crc_xmodem, int) and 0 <= crc_xmodem <= 0xFFFF

    crc_arc = SaveChecksum.crc16_arc(data)
    assert isinstance(crc_arc, int) and 0 <= crc_arc <= 0xFFFF

    fletcher = SaveChecksum.fletcher16(data)
    assert isinstance(fletcher, int) and 0 <= fletcher <= 0xFFFF

    mod16 = SaveChecksum.modulo_sum16(data)
    assert isinstance(mod16, int) and 0 <= mod16 <= 0xFFFF

    mod32 = SaveChecksum.modulo_sum32(data)
    assert isinstance(mod32, int) and 0 <= mod32 <= 0xFFFFFFFF


def test_dual_slot_save_detection_and_rotation():
    slot_size = 0x1000
    save_data = bytearray(slot_size * 2)

    # Setup Slot A with counter = 5
    struct.pack_into("<I", save_data, 0, 5)
    save_data[4:20] = b"SLOT A SAVE DATA"

    # Setup Slot B with counter = 6 (more recent!)
    struct.pack_into("<I", save_data, slot_size, 6)
    save_data[slot_size + 4 : slot_size + 20] = b"SLOT B SAVE DATA"

    active_idx, slot_bytes, counter = DualSlotSave.detect_active_slot(
        bytes(save_data), slot_size=slot_size, counter_offset=0, counter_size=4
    )

    assert active_idx == 1
    assert counter == 6
    assert b"SLOT B" in slot_bytes

    # Write new save data -> should overwrite Slot A with counter = 7
    new_data = b"\x00" * 4 + b"NEW SAVE GAME DATA"
    next_idx = DualSlotSave.write_to_next_slot(
        save_data, new_data, slot_size=slot_size, counter_offset=0, counter_size=4
    )
    assert next_idx == 0

    # Verify that Slot A is now active with counter = 7
    active_now, slot_now, cnt_now = DualSlotSave.detect_active_slot(
        bytes(save_data), slot_size=slot_size, counter_offset=0, counter_size=4
    )
    assert active_now == 0
    assert cnt_now == 7
    assert b"NEW SAVE GAME" in slot_now
