import struct
from miorom.errors import RelocationError
from typing import Tuple, Optional


class DualSlotSave:
    """
    Dual-Slot Wear-Leveling Save Manager.
    Handles save formats (such as Pokémon, Rune Factory, Zelda) where games alternate
    between Slot A and Slot B using an incrementing counter to protect Flash/EEPROM from corruption.
    """

    @classmethod
    def detect_active_slot(
        cls,
        data: bytes,
        slot_size: int,
        counter_offset: int = 0,
        counter_size: int = 4,
        endian: str = "<",
    ) -> Tuple[int, bytes, int]:
        """
        Detects which of the two slots contains the most recent valid save data.
        Returns:
            active_slot_index: 0 for Slot A, 1 for Slot B.
            slot_data: Bytes of the active slot.
            save_counter: The counter value found in the active slot.
        """
        if len(data) < slot_size * 2:
            raise RelocationError(f"Save data too small for dual slots of {slot_size} bytes each.")

        slot_a = data[0:slot_size]
        slot_b = data[slot_size : slot_size * 2]

        fmt = f"{endian}{'I' if counter_size == 4 else 'H'}"
        cnt_a = struct.unpack_from(fmt, slot_a, counter_offset)[0]
        cnt_b = struct.unpack_from(fmt, slot_b, counter_offset)[0]

        # Check for uninitialized / wiped memory (0xFFFFFFFF or 0)
        max_val = 0xFFFFFFFF if counter_size == 4 else 0xFFFF
        valid_a = cnt_a != max_val
        valid_b = cnt_b != max_val

        if valid_a and not valid_b:
            return 0, slot_a, cnt_a
        elif valid_b and not valid_a:
            return 1, slot_b, cnt_b
        elif not valid_a and not valid_b:
            # Both uninitialized, default to Slot A
            return 0, slot_a, 0

        # Pick higher counter
        if cnt_a >= cnt_b:
            return 0, slot_a, cnt_a
        else:
            return 1, slot_b, cnt_b

    @classmethod
    def write_to_next_slot(
        cls,
        data: bytearray,
        new_slot_data: bytes,
        slot_size: int,
        counter_offset: int = 0,
        counter_size: int = 4,
        endian: str = "<",
    ) -> int:
        """
        Writes modified save data into the alternate (older) slot with an incremented counter.
        Returns the index of the newly written slot (0 or 1).
        """
        active_idx, _, cur_counter = cls.detect_active_slot(
            bytes(data),
            slot_size=slot_size,
            counter_offset=counter_offset,
            counter_size=counter_size,
            endian=endian,
        )

        next_idx = 1 if active_idx == 0 else 0
        target_offset = next_idx * slot_size

        slot_buf = bytearray(new_slot_data[:slot_size].ljust(slot_size, b"\x00"))
        new_counter = (cur_counter + 1) & (0xFFFFFFFF if counter_size == 4 else 0xFFFF)
        fmt = f"{endian}{'I' if counter_size == 4 else 'H'}"
        struct.pack_into(fmt, slot_buf, counter_offset, new_counter)

        data[target_offset : target_offset + slot_size] = slot_buf
        return next_idx
